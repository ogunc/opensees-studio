"""Steel frame check (AISC 360-16) and storey drift check over analysis results.

The equations are in :mod:`core.design.aisc360`; this module finds the demands.

Demands. Every static case contributes its internal force diagrams (axial,
shears, moments) sampled at :data:`STATIONS` points along each member, span
loads included (:func:`services.element_forces.extract_diagram_data`). A load
combination is expanded into linear sums of cases: *Linear Add* adds its terms,
*Envelope* keeps each term as an alternative, and a response spectrum case
enters as ±its peak (the sign of a combined peak is unknown), linear between the
two ends. *Absolute Add* and *SRSS* combinations are reported as not checked.

Per member and load set the check evaluates every station with that station's
axial force (with its sign: tension or compression; the diagrams draw compression
positive), moments and shears, so the H1 interaction uses forces that act at the
same place. ``Cb`` comes from the major-axis diagram (F1-1) unless the user set
it. The governing ratio over all stations and load sets is reported with the
equation that produced it and the station where it occurred.

The shape. A member is checked when its section's name is an AISC v16 shape
of a family the check covers (W, M, S, HP, C, MC, WT, MT, ST, equal-leg L,
rectangular and round HSS, pipe), or when the user names one for it. The shape's
tabulated properties (scaled to the project's units) give the capacity; the
analysis keeps using the section's own values, and a difference in area of
more than 2 % is reported.

No Qt. OpenSees is not needed: the results come in.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from functools import lru_cache
from types import SimpleNamespace
from typing import Any

import numpy as np

from opensees_studio.core.aisc import SOURCE_UNITS, get_shape, load_shapes
from opensees_studio.core.analysis import ResponseSpectrumCase, StaticCase
from opensees_studio.core.combinations import guess_load_role
from opensees_studio.core.design.aisc341 import (
    JointBeam,
    JointColumn,
    Role,
    ca,
    continuity_plate_thickness,
    continuity_tlim,
    expected_brace_strength,
    joint_scwb,
    member_limits,
    ocbf_brace_slenderness_limit,
    panel_zone_demand,
    panel_zone_strength,
)
from opensees_studio.core.design.aisc360 import (
    I_SHAPE_FAMILIES,
    BuiltUpIShape,
    Demand,
    IShape,
    MemberCheck,
    Steel,
    SteelShape,
    cb_from_moments,
    check_member,
)
from opensees_studio.core.design.aisc360_shapes import (
    ANGLE_FAMILIES,
    CHANNEL_FAMILIES,
    HSS_DESIGN_THICKNESS,
    RECT_HSS_FAMILIES,
    ROUND_HSS_FAMILIES,
    TEE_FAMILIES,
    Channel,
    EqualLegAngle,
    RectHSS,
    RoundHSS,
    Tee,
)
from opensees_studio.core.design.brace_connections import (
    brace_connection_demands,
    critical_plastic_modulus,
    gusset_weld_check,
    gusset_weld_required_leg,
)
from opensees_studio.core.design.built_up import built_up_ishape
from opensees_studio.core.design.built_up_model import BuiltUpShape
from opensees_studio.core.design.calc import CalcStep, LimitStateCheck
from opensees_studio.core.design.chapter_j import (
    bearing_strength,
    block_shear_strength,
    bolt_bearing_strength,
    bolt_shear_strength,
    bolt_tension_strength,
    concrete_bearing_strength,
    fillet_weld_strength,
    flange_local_bending,
    plate_shear_rupture,
    plate_shear_yielding,
    slip_critical_strength,
    splice_strength,
    web_compression_buckling,
    web_local_crippling,
    web_local_yielding,
    web_sidesway_buckling,
)
from opensees_studio.core.design.connections import (
    rbs_flexure_ratio,
    rbs_geometry,
    rbs_mpe,
    rbs_mpr,
    rbs_protected_zone,
)
from opensees_studio.core.design.direct_analysis import is_direct_analysis_case
from opensees_studio.core.design.gussets import gusset_checks
from opensees_studio.core.design.members import (
    DesignMember,
    design_members,
    direction_role,
    members_by_element,
)
from opensees_studio.core.design.rbs_web import web_connection_checks
from opensees_studio.core.design.scbf_joints import (
    column_splice_demand,
    scbf_beam_column_moment,
)
from opensees_studio.core.design.settings import (
    CHECKED_SEISMIC_SYSTEMS,
    DesignLoadSet,
    DesignSettings,
    SteelMemberDesign,
)
from opensees_studio.core.design.steel_grades import STEEL_GRADES, grade_stresses
from opensees_studio.core.geometry.elements import FRAME_ELEMENT_CLASSES
from opensees_studio.core.sections import ElasticSection
from opensees_studio.core.units import UnitSystem, length_scale, stress_scale
from opensees_studio.services.element_forces import ForceComponent, extract_diagram_data
from opensees_studio.services.results import ResponseSpectrumResults, StaticResults

#: Points along each member where the demands are read (ends included).
STATIONS = 25

_GRID = np.linspace(0.0, 1.0, STATIONS)
_COMPONENTS = (
    ForceComponent.N,
    ForceComponent.V2,
    ForceComponent.V3,
    ForceComponent.T,
    ForceComponent.M2,
    ForceComponent.M3,
)
_FY_KSI = 50.0
_FU_KSI = 65.0

#: localForce index of (component, end) for the response spectrum peaks.
_PEAK_INDEX_3D = {
    "N": (0, 6),
    "V2": (1, 7),
    "V3": (2, 8),
    "T": (3, 9),
    "M2": (4, 10),
    "M3": (5, 11),
}
_PEAK_INDEX_2D = {"N": (0, 3), "V2": (1, 4), "M3": (2, 5)}


class UnsupportedLoadSetError(ValueError):
    """A combination the steel check cannot expand into linear sums."""


# ──────────────────────────── load sets ────────────────────────────
Alternative = dict[int, float]
"""Case id → factor; a response spectrum case's factor carries the ± of its peak."""


def default_load_sets(project: Any) -> list[DesignLoadSet]:
    """The direct analysis strength cases, else every combination, else every static case.

    A direct analysis case is a whole combination solved to second order, so when
    they exist they are the demands; their first-order twins are left out.
    """
    direct = [
        DesignLoadSet(source="case", ref_id=c.id)
        for c in project.analyses
        if is_direct_analysis_case(c) and c.direct_analysis.order == "second"
    ]
    if direct:
        return direct
    if project.combinations:
        return [DesignLoadSet(source="combination", ref_id=c.id) for c in project.combinations]
    return [
        DesignLoadSet(source="case", ref_id=c.id)
        for c in project.analyses
        if isinstance(c, StaticCase)
    ]


def load_set_label(project: Any, load_set: DesignLoadSet) -> str:
    pool = project.analyses if load_set.source == "case" else project.combinations
    item = next((x for x in pool if x.id == load_set.ref_id), None)
    kind = "Case" if load_set.source == "case" else "Combination"
    return f"{kind} {item.name or item.id}" if item is not None else f"{kind} {load_set.ref_id}"


def expand(
    project: Any, source: str, ref_id: int, _seen: frozenset[int] = frozenset()
) -> list[Alternative]:
    """The linear sums of cases a case or a combination stands for."""
    if source == "case":
        case = next((c for c in project.analyses if c.id == ref_id), None)
        if isinstance(case, StaticCase):
            return [{ref_id: 1.0}]
        if isinstance(case, ResponseSpectrumCase):
            return [{ref_id: 1.0}, {ref_id: -1.0}]
        name = getattr(case, "name", ref_id)
        raise UnsupportedLoadSetError(f"case {name} is not a static or response spectrum case")
    if ref_id in _seen:
        raise UnsupportedLoadSetError(f"combination {ref_id} refers to itself")
    combination = next((c for c in project.combinations if c.id == ref_id), None)
    if combination is None:
        raise UnsupportedLoadSetError(f"combination {ref_id} does not exist")
    kind = combination.combination_type
    terms = [
        [
            {cid: f * term.factor for cid, f in alt.items()}
            for alt in expand(project, term.source, term.ref_id, _seen | {ref_id})
        ]
        for term in combination.terms
    ]
    if kind == "Envelope":
        return [alt for options in terms for alt in options]
    if kind == "LinearAdd":
        out: list[Alternative] = []
        for choice in itertools.product(*terms):
            total: Alternative = {}
            for alt in choice:
                for cid, f in alt.items():
                    total[cid] = total.get(cid, 0.0) + f
            out.append(total)
        return out
    raise UnsupportedLoadSetError(
        f"combination {combination.name or ref_id} is {kind}, which has no signed demands"
    )


# ──────────────────────────── station fields ────────────────────────────
Field = dict[str, dict[int, np.ndarray]]
"""Component name → element id → values at the stations."""


def static_field(project: Any, results: StaticResults) -> Field:
    """The diagrams of a static case at the stations, in the diagram sign convention."""
    out: Field = {}
    for component in _COMPONENTS:
        try:
            data = extract_diagram_data(project, results, component, stations=True)
        except (KeyError, ValueError, IndexError):
            continue
        values: dict[int, np.ndarray] = {}
        for k, eid in enumerate(data.element_ids):
            eid = int(eid)
            if eid in data.stations:
                s, v = data.stations[eid]
                values[eid] = np.interp(_GRID, s, v)
            else:
                values[eid] = data.values_i[k] + (data.values_j[k] - data.values_i[k]) * _GRID
        out[component.value] = values
    return out


def spectrum_field(project: Any, results: ResponseSpectrumResults) -> Field:
    """Peak magnitudes of a response spectrum case, linear between the ends."""
    out: Field = {}
    for eid, forces in results.element_forces.items():
        row = np.abs(np.atleast_2d(np.asarray(forces, dtype=float))[-1])
        index = _PEAK_INDEX_3D if row.size >= 12 else _PEAK_INDEX_2D
        for name, (i, j) in index.items():
            if j < row.size:
                out.setdefault(name, {})[int(eid)] = row[i] + (row[j] - row[i]) * _GRID
    del project
    return out


# ──────────────────────────── shapes ────────────────────────────
def shape_name(name: str) -> str:
    """The table's name of ``name``: ``w 14 x 90`` → ``W14X90``, ``C12x20.7`` → ``C12X20_7``.

    Case, spaces and the table's ``_`` for ``.`` and ``/`` do not matter
    (``HSS8x8x1/2``, ``pipe10std``). An unknown name comes back upper-cased.
    """
    compact = "".join(name.split())
    key = compact.upper().replace(".", "_").replace("/", "_")
    return _names_by_key().get(key, compact.upper())


@lru_cache(maxsize=1)
def _names_by_key() -> dict[str, str]:
    return {n.upper(): n for n in load_shapes()}


def ishape_in_units(name: str, units: Any) -> IShape:
    """The AISC shape ``name`` with its properties in the project's ``units``.

    Raises:
        KeyError: not an AISC v16 shape.
        ValueError: a shape these provisions do not cover.
    """
    shape = get_shape(shape_name(name))
    if shape.family not in I_SHAPE_FAMILIES:
        raise ValueError(f"{shape.name} is a {shape.family} shape; only W, M, S and HP are checked")
    f = length_scale(SOURCE_UNITS, units)
    values = {
        "d": shape.d,
        "bf": shape.bf,
        "tw": shape.tw,
        "tf": shape.tf,
        "zx": shape.zx,
        "zy": shape.zy,
        "sx": shape.sx,
        "sy": shape.sy,
        "rx": shape.rx,
        "ry": shape.ry,
        "iy": shape.iy,
        "j": shape.j,
        "cw": shape.cw,
    }
    missing = [k for k, v in values.items() if v is None]
    if missing:
        raise ValueError(f"{shape.name} lacks {', '.join(missing)} in the table")
    v: dict[str, float] = {k: float(x) for k, x in values.items() if x is not None}
    return IShape(
        name=shape.name,
        A=shape.area * f**2,
        d=v["d"] * f,
        bf=v["bf"] * f,
        tw=v["tw"] * f,
        tf=v["tf"] * f,
        Ix=shape.ix * f**4,
        Iy=v["iy"] * f**4,
        Zx=v["zx"] * f**3,
        Zy=v["zy"] * f**3,
        Sx=v["sx"] * f**3,
        Sy=v["sy"] * f**3,
        rx=v["rx"] * f,
        ry=v["ry"] * f,
        J=v["j"] * f**4,
        Cw=v["cw"] * f**6,
    )


#: Every family the check covers.
CHECKED_FAMILIES = (
    I_SHAPE_FAMILIES
    | CHANNEL_FAMILIES
    | TEE_FAMILIES
    | ANGLE_FAMILIES
    | RECT_HSS_FAMILIES
    | ROUND_HSS_FAMILIES
)


def shape_in_units(
    name: str, units: Any, built_up: Mapping[str, BuiltUpShape] | None = None
) -> SteelShape:
    """The AISC shape ``name`` as the class of its family, in the project's ``units``.

    ``built_up`` maps upper-case names to the project's built-up shapes
    (``DesignSettings.built_up_by_name()``); a name found there is that welded
    I-shape, already in project units.

    Raises:
        KeyError: not an AISC v16 shape (nor a built-up one).
        ValueError: a shape these provisions do not cover, or a table row
            missing a property the family needs.
    """
    if built_up:
        found = built_up.get(name.strip().upper())
        if found is not None:
            return built_up_ishape(found)
    shape = get_shape(shape_name(name))
    family = shape.family
    if family in I_SHAPE_FAMILIES:
        return ishape_in_units(name, units)
    if family not in CHECKED_FAMILIES:
        raise ValueError(f"{shape.name} is a {family} shape, which the check does not cover")
    f = length_scale(SOURCE_UNITS, units)

    def need(*keys: str) -> dict[str, float]:
        values = {k: getattr(shape, k) for k in keys}
        missing = [k for k, v in values.items() if v is None]
        if missing:
            raise ValueError(f"{shape.name} lacks {', '.join(missing)} in the table")
        return {k: float(v) for k, v in values.items()}

    if family in ROUND_HSS_FAMILIES:
        v = need("od", "tnom", "zx", "sx", "rx", "j")
        return RoundHSS(
            name=shape.name,
            A=shape.area * f**2,
            D=v["od"] * f,
            t=HSS_DESIGN_THICKNESS * v["tnom"] * f,
            Ix=shape.ix * f**4,
            Z=v["zx"] * f**3,
            S=v["sx"] * f**3,
            r=v["rx"] * f,
            J=v["j"] * f**4,
        )
    if family in RECT_HSS_FAMILIES:
        v = need("d", "bf", "tnom", "zx", "zy", "sx", "sy", "rx", "ry", "iy", "j")
        return RectHSS(
            name=shape.name,
            A=shape.area * f**2,
            H=v["d"] * f,
            B=v["bf"] * f,
            t=HSS_DESIGN_THICKNESS * v["tnom"] * f,
            Ix=shape.ix * f**4,
            Iy=v["iy"] * f**4,
            Zx=v["zx"] * f**3,
            Zy=v["zy"] * f**3,
            Sx=v["sx"] * f**3,
            Sy=v["sy"] * f**3,
            rx=v["rx"] * f,
            ry=v["ry"] * f,
            J=v["j"] * f**4,
        )
    if family in ANGLE_FAMILIES:
        v = need("d", "bf", "tw", "sx", "sy", "rx", "ry", "iy", "j", "cw")
        if abs(v["d"] - v["bf"]) > 1e-9:
            raise ValueError(
                f"{shape.name} has unequal legs: its flexure about the principal axes "
                "(F10) is not covered"
            )
        return EqualLegAngle(
            name=shape.name,
            A=shape.area * f**2,
            b=v["d"] * f,
            t=v["tw"] * f,
            Ix=shape.ix * f**4,
            Iy=v["iy"] * f**4,
            Sx=v["sx"] * f**3,
            Sy=v["sy"] * f**3,
            rx=v["rx"] * f,
            ry=v["ry"] * f,
            J=v["j"] * f**4,
            Cw=v["cw"] * f**6,
        )
    v = need("d", "bf", "tw", "tf", "zx", "zy", "sx", "sy", "rx", "ry", "iy", "j", "cw")
    kind = Channel if family in CHANNEL_FAMILIES else Tee
    return kind(
        name=shape.name,
        A=shape.area * f**2,
        d=v["d"] * f,
        bf=v["bf"] * f,
        tw=v["tw"] * f,
        tf=v["tf"] * f,
        Ix=shape.ix * f**4,
        Iy=v["iy"] * f**4,
        Zx=v["zx"] * f**3,
        Zy=v["zy"] * f**3,
        Sx=v["sx"] * f**3,
        Sy=v["sy"] * f**3,
        rx=v["rx"] * f,
        ry=v["ry"] * f,
        J=v["j"] * f**4,
        Cw=v["cw"] * f**6,
    )


def shape_family(shape: Any) -> str:
    """The steel grade family of a checked shape: ``BU`` for a built-up one, else its table family."""
    if isinstance(shape, BuiltUpIShape):
        return "BU"
    return get_shape(shape.name).family


def member_steel(
    settings: DesignSettings, family: str, member: SteelMemberDesign, units: Any
) -> tuple[float, float, str]:
    """``(Fy, Fu, grade label)`` of a member: its own grade, its family's, or the project's.

    The grade label is empty when the project's Fy and Fu (or their 50 / 65 ksi
    defaults) apply.
    """
    key = member.grade or settings.steel_grades.get(family)
    if key in STEEL_GRADES:
        fy, fu = grade_stresses(key, family, units)
        return fy, fu, STEEL_GRADES[key].label
    fy = settings.fy if settings.fy is not None else default_fy(units)
    fu = settings.fu if settings.fu is not None else default_fu(units)
    return fy, fu, ""


def project_steel(settings: DesignSettings, units: Any) -> tuple[float, float]:
    """``(Fy, Fu)`` of the checks that take one value for the whole frame.

    The project's Fy and Fu when set, else the W-shape grade when one is chosen,
    else 50 / 65 ksi. The joint, connection and capacity-design checks use it.
    """
    if settings.fy is None and "W" in settings.steel_grades:
        key = settings.steel_grades["W"]
        if key in STEEL_GRADES:
            return grade_stresses(key, "W", units)
    fy = settings.fy if settings.fy is not None else default_fy(units)
    fu = settings.fu if settings.fu is not None else default_fu(units)
    return fy, fu


def default_fy(units: Any) -> float:
    """50 ksi in the project's stress unit."""
    return _FY_KSI * stress_scale(SOURCE_UNITS, units)


def default_fu(units: Any) -> float:
    """65 ksi in the project's stress unit."""
    return _FU_KSI * stress_scale(SOURCE_UNITS, units)


# ──────────────────────────── the check ────────────────────────────
@dataclass
class MemberResult:
    """The governing outcome of one member over every load set."""

    element_id: int
    shape: str = ""
    status: str = "not designed"
    """``OK``, ``NG`` (over the limit) or ``not designed``."""
    ratio: float = 0.0
    check: str = ""
    equation: str = ""
    load_set: str = ""
    station: float = 0.0
    """Fraction of the member length where the governing check was evaluated."""
    ratios: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    checks: list[LimitStateCheck] = field(default_factory=list)
    capacity_ratio: float = 0.0
    """Worst ratio of the SCBF capacity-design alternative (AISC 341-22 F2.3)."""
    grade: str = ""
    """The steel grade the member was checked with; empty for the project's Fy / Fu."""
    member_id: int = 0
    """The physical member (its first element) the element belongs to."""
    unbraced: tuple[float, float, float] = (0.0, 0.0, 0.0)
    """``(Lx, Ly, Lb)`` the check used: from the bracing points, or the overrides."""


@dataclass
class JointResult:
    """The E3.4a outcome of one beam-to-column joint."""

    node_id: int
    ratio: float = 0.0
    """``sum M*pc / sum M*be``; E3-1 requires more than 1.0."""
    load_set: str = ""
    status: str = "not checked"
    columns: int = 0
    beams: int = 0
    panel_ratio: float = 0.0
    """Panel-zone demand over available strength, J10.6; must be at most 1.0."""
    panel_status: str = ""
    panel_demand: float = 0.0
    panel_capacity: float = 0.0
    continuity_required: bool = False
    continuity_status: str = ""
    continuity_tcf: float = 0.0
    continuity_tlim: float = 0.0
    continuity_plate_t: float = 0.0


@dataclass
class ConnectionResult:
    """One AISC 358 RBS connection, its geometry and probable moment."""

    connection_id: int
    beam_element_id: int
    column_element_id: int
    shape: str = ""
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    sh: float = 0.0
    z_rbs: float = 0.0
    mpr: float = 0.0
    protected_from: float = 0.0
    protected_to: float = 0.0
    joint_node: int = 0
    zone_clear: bool = True
    vh: float = 0.0
    mf: float = 0.0
    mpe: float = 0.0
    flexure_ratio: float = 0.0
    flexure_status: str = ""
    span_ratio: float = 0.0
    span_limit: float = 0.0
    span_status: str = ""
    shear_demand: float = 0.0
    shear_capacity: float = 0.0
    shear_ratio: float = 0.0
    shear_status: str = ""
    web_ratio: float = 0.0
    web_status: str = ""
    web_checks: list[LimitStateCheck] = field(default_factory=list)
    status: str = "not checked"
    notes: list[str] = field(default_factory=list)


@dataclass
class ProtectedZone:
    """The SCBF protected zones of one brace and whether they are clear."""

    element_id: int
    ranges: tuple[tuple[float, float], ...] = ()
    """Fractions of the member length: the centre quarter and the ends."""
    zone_clear: bool = True
    notes: list[str] = field(default_factory=list)


@dataclass
class GussetResult:
    """One SCBF gusset plate, its connection demands and its checks."""

    gusset_id: int
    brace_element_id: int
    shape: str = ""
    t: float = 0.0
    b: float = 0.0
    lw: float = 0.0
    free_length: float = 0.0
    demand: float = 0.0
    tension_demand: float = 0.0
    compression_demand: float = 0.0
    flexure_demand: float = 0.0
    weld_leg: float = 0.0
    weld_required_leg: float = 0.0
    weld_ratio: float = 0.0
    weld_status: str = ""
    ratio: float = 0.0
    status: str = "not checked"
    checks: list[LimitStateCheck] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class CapacityDesign:
    """One load set's SCBF capacity-design amplification (AISC 341-22 F2.3)."""

    load_set: str
    brace_element_id: int
    shape: str = ""
    state: str = ""
    """``tension`` or ``compression`` of the governing brace."""
    analysis_force: float = 0.0
    """Brace force from the seismic terms of the load set."""
    expected_force: float = 0.0
    """Expected brace strength for that state (F2.3)."""
    factor: float = 1.0
    """``max(1, expected / analysis)`` applied to the seismic terms."""
    skipped: list[int] = field(default_factory=list)
    """Braces with no seismic force, left out of the factor."""
    notes: list[str] = field(default_factory=list)


@dataclass
class ScbfJointResult:
    """One SCBF beam-to-column joint and its F2.6b required moment."""

    node_id: int
    beam_element_id: int
    column_element_ids: list[int] = field(default_factory=list)
    brace_element_id: int = 0
    beam_moment: float = 0.0
    column_moment: float = 0.0
    required_moment: float = 0.0
    available_moment: float = 0.0
    ratio: float = 0.0
    status: str = "not checked"
    notes: list[str] = field(default_factory=list)


@dataclass
class ColumnSpliceResult:
    """One SCBF column splice and its F2.6d required moment and shear."""

    splice_id: int
    node_id: int
    top_element_id: int
    bottom_element_id: int
    shape_top: str = ""
    shape_bottom: str = ""
    clear_height: float = 0.0
    moment: float = 0.0
    shear: float = 0.0
    status: str = "not checked"
    steps: list[CalcStep] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class ChapterJResult:
    """One saved AISC 360 Chapter J check and its outcome."""

    check_id: int
    name: str
    check_type: str
    demand: float = 0.0
    nominal: float = 0.0
    available: float = 0.0
    ratio: float = 0.0
    status: str = "not checked"
    equation: str = ""
    steps: list[CalcStep] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class DesignReport:
    members: list[MemberResult] = field(default_factory=list)
    joints: list[JointResult] = field(default_factory=list)
    connections: list[ConnectionResult] = field(default_factory=list)
    protected_zones: list[ProtectedZone] = field(default_factory=list)
    gussets: list[GussetResult] = field(default_factory=list)
    capacity_design: list[CapacityDesign] = field(default_factory=list)
    scbf_joints: list[ScbfJointResult] = field(default_factory=list)
    column_splices: list[ColumnSpliceResult] = field(default_factory=list)
    chapter_j: list[ChapterJResult] = field(default_factory=list)
    load_sets: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def failing(self) -> list[MemberResult]:
        return [m for m in self.members if m.status == "NG"]

    def summary(self) -> str:
        designed = [m for m in self.members if m.status != "not designed"]
        worst = max(designed, key=lambda m: m.ratio, default=None)
        text = (
            f"{len(designed)} member(s) checked, {len(self.failing)} over the limit, "
            f"{len(self.members) - len(designed)} not designed"
        )
        if worst is not None:
            text += f"; largest ratio {worst.ratio:.3f} (element {worst.element_id})"
        if self.joints:
            below = [j for j in self.joints if j.status == "NG"]
            panels = [j for j in self.joints if j.panel_status == "NG"]
            text += (
                f"; {len(self.joints)} joint(s) checked, {len(below)} below 1.0, "
                f"{len(panels)} panel zone(s) over capacity"
            )
        return text + "."


def _axes(project: Any, section: Any, shape: SteelShape) -> tuple[str, str, str, str, bool]:
    """(major moment, major shear, minor moment, minor shear, bent about the major axis)."""
    if project.ndm == 2:
        iz = float(getattr(section, "Iz", shape.Ix) or shape.Ix)
        major = abs(iz - shape.Ix) <= abs(iz - shape.Iy)
        return ("M3", "V2", "", "", True) if major else ("", "", "M3", "V2", False)
    iy = float(getattr(section, "Iy", 0.0) or 0.0)
    iz = float(getattr(section, "Iz", 0.0) or 0.0)
    if iy >= iz:
        return "M2", "V3", "M3", "V2", True
    return "M3", "V2", "M2", "V3", True


def _length(project: Any, element: Any) -> float:
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    return float(np.linalg.norm(coords[element.nodes[1]] - coords[element.nodes[0]]))


def _member_role(project: Any, element: Any, settings: DesignSettings) -> Role:
    """The role the user gave the element, else ``column``, ``beam`` or ``brace`` by direction.

    A member within 20% of vertical is a column; within 20% of horizontal is a
    beam (a plan diagonal in 3D is a brace); anything else is a brace.
    """
    chosen = settings.member(element.id).role
    if chosen is not None:
        return chosen
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    return direction_role(project, coords[element.nodes[0]], coords[element.nodes[1]])


def _design_members(project: Any, settings: DesignSettings) -> dict[int, DesignMember]:
    """Element id -> its physical member, with the roles the user chose."""
    roles = {m.element_id: m.role for m in settings.members if m.role is not None}
    return members_by_element(design_members(project, roles))


@dataclass(frozen=True)
class MemberLengths:
    """What Design → Member Classification shows for one frame element."""

    element_id: int
    member_id: int
    element_ids: tuple[int, ...]
    """Every element of the physical member."""
    role: str
    role_from_user: bool
    length: float
    """The physical member's length."""
    unbraced: tuple[float, float, float]
    """``(Lx, Ly, Lb)`` from the bracing points, before any override."""


def member_lengths(project: Any, settings: DesignSettings | None = None) -> list[MemberLengths]:
    """Physical member, role and automatic unbraced lengths of every frame element.

    The major axis comes from the AISC shape when the section names one, else
    from the larger of the section's two moments of inertia.
    """
    settings = settings or DesignSettings()
    physical = _design_members(project, settings)
    sections = {s.id: s for s in project.sections}
    out: list[MemberLengths] = []
    for element in project.elements:
        member = physical.get(element.id)
        if member is None:
            continue
        section = sections.get(getattr(element, "section_id", -1))
        name = settings.member(element.id).shape or (getattr(section, "name", "") or "")
        try:
            shape: Any = shape_in_units(name, project.meta.units, settings.built_up_by_name())
        except (KeyError, ValueError):
            iz = float(getattr(section, "Iz", 1.0) or 1.0)
            iy = float(getattr(section, "Iy", 0.0) or 0.0)
            shape = SimpleNamespace(Ix=max(iy, iz) or 1.0, Iy=min(iy, iz))
        m_major, _vx, m_minor, _vy, _about = _axes(project, section, shape)
        out.append(
            MemberLengths(
                element_id=element.id,
                member_id=member.id,
                element_ids=member.element_ids,
                role=member.role,
                role_from_user=settings.member(element.id).role is not None,
                length=member.length,
                unbraced=_unbraced(member, element, m_major, m_minor, member.length),
            )
        )
    return out


def _bending_axes(m_major: str, m_minor: str) -> tuple[str, str]:
    """``(major, minor)``: the local axis each buckling mode moves the member along.

    ``M3`` bends towards local y, ``M2`` towards z. A 2D member bent about its
    minor axis has no major moment: in-plane (y) is then its minor axis.
    """
    toward = {"M3": "y", "M2": "z"}
    major = toward[m_major] if m_major else ("z" if toward.get(m_minor, "y") == "y" else "y")
    return major, ("z" if major == "y" else "y")


def _segment_cb(
    member: DesignMember,
    element_id: int,
    axis: str,
    moments: Mapping[int, np.ndarray],
    elements: Mapping[int, Any],
) -> float | None:
    """F1-1 Cb over the laterally unbraced segment that holds ``element_id``.

    ``moments`` maps element id to its major-axis moment at the stations, for one
    load alternative. The segment's diagram is put together from its elements in
    order along the member (an element pointing the other way is read backwards);
    Cb takes absolute values, so the sign convention does not matter. None when an
    element of the segment has no diagram.
    """
    first, last = member.segment(element_id, axis)  # type: ignore[arg-type]
    xs: list[np.ndarray] = []
    ms: list[np.ndarray] = []
    for k in range(first, last):
        eid = member.element_ids[k]
        values = moments.get(eid)
        if values is None:
            return None
        values = np.abs(np.asarray(values, dtype=float))
        if int(elements[eid].nodes[0]) != member.node_ids[k]:
            values = values[::-1]
        xs.append(member.stations[k] + _GRID * (member.stations[k + 1] - member.stations[k]))
        ms.append(values)
    x = np.concatenate(xs)
    m = np.concatenate(ms)
    start, end = member.stations[first], member.stations[last]
    quarter = [float(np.interp(start + f * (end - start), x, m)) for f in (0.25, 0.5, 0.75)]
    peak = float(np.max(m))
    return cb_from_moments(peak, *quarter) if peak > 0.0 else 1.0


def _unbraced(
    member: DesignMember | None, element: Any, m_major: str, m_minor: str, fallback: float
) -> tuple[float, float, float]:
    """``(Lx, Ly, Lb)`` of ``element`` from its member's bracing points.

    Major-axis buckling moves the member along the local axis its major moment
    bends it towards (``M3`` → y, ``M2`` → z); lateral-torsional buckling moves
    the compression flange along the other one, so ``Lb`` is the minor-axis
    unbraced length. Without a member, every length is ``fallback``.
    """
    if member is None:
        return fallback, fallback, fallback
    major, minor = _bending_axes(m_major, m_minor)
    lx = member.unbraced_length(element.id, major)  # type: ignore[arg-type]
    ly = member.unbraced_length(element.id, minor)  # type: ignore[arg-type]
    return lx, ly, ly


def _case_role(case: Any) -> str | None:
    """The load role a case name suggests (``EX`` → ``E``)."""
    return guess_load_role(getattr(case, "name", "") or "")


def _capacity_alternatives(
    project: Any,
    fields: Mapping[int, Field],
    alternatives: list[tuple[str, Alternative]],
    settings: DesignSettings,
    units: Any,
    *,
    fy: float,
    fu: float,
) -> tuple[list[tuple[str, Alternative]], list[CapacityDesign], list[str]]:
    """AISC 341-22 F2.3: capacity-limited seismic terms of each load set.

    The capacity-limited seismic load effect is the frame's response with every
    brace at its expected strength. For a linear analysis the response is
    proportional to the brace force, so the seismic terms of a load set are
    scaled by the largest ``expected / analysis`` ratio of its braces. Every
    brace then reaches at least its expected strength: this is conservative
    with respect to both F2.3 analyses (compression at expected strength is
    more severe than at 0.3 of it). Gravity terms are not scaled. The factor
    is never below 1.0, so the check cannot reduce the analysis demand.
    """
    if settings.seismic_system != "SCBF":
        return [], [], []
    cases = {c.id: c for c in project.analyses}
    sections = {s.id: s for s in project.sections}
    braces: list[tuple[Any, Any, tuple[float, float], Any]] = []
    notes: list[str] = []
    physical = _design_members(project, settings)
    for element in project.elements:
        if not isinstance(element, FRAME_ELEMENT_CLASSES):
            continue
        if _member_role(project, element, settings) != "brace":
            continue
        overrides = settings.member(element.id)
        section = sections.get(getattr(element, "section_id", -1))
        name = overrides.shape or (getattr(section, "name", "") or "")
        try:
            shape = shape_in_units(name, units, settings.built_up_by_name())
        except (KeyError, ValueError) as exc:
            notes.append(f"Capacity design: brace {element.id} has no AISC shape ({exc}).")
            continue
        m_major, _v_major, m_minor, _v_minor, _about = _axes(project, section, shape)
        lx, ly, _lb = _unbraced(
            physical.get(element.id), element, m_major, m_minor, _length(project, element)
        )
        lengths = (overrides.length_major or lx, overrides.length_minor or ly)
        braces.append((element, shape, lengths, overrides))
    if not braces:
        return [], [], notes

    out: list[tuple[str, Alternative]] = []
    records: list[CapacityDesign] = []
    for label, alt in alternatives:
        seismic = {cid: factor for cid, factor in alt.items() if _case_role(cases.get(cid)) == "E"}
        if not seismic:
            continue
        best: CapacityDesign | None = None
        skipped: list[int] = []
        for element, shape, lengths, overrides in braces:
            total = np.zeros(STATIONS)
            peak = False
            for cid, factor in seismic.items():
                per_case = fields.get(cid, {}).get("N", {}).get(element.id)
                if per_case is not None:
                    total = total + factor * per_case
                if isinstance(cases.get(cid), ResponseSpectrumCase):
                    peak = True
            force = float(total[int(np.argmax(np.abs(total)))])
            if abs(force) <= 1e-9:
                skipped.append(element.id)
                continue
            section = sections.get(getattr(element, "section_id", -1))
            e = float(getattr(section, "E", 0.0) or 0.0) or 29000.0 * stress_scale(
                SOURCE_UNITS, units
            )
            g = float(getattr(section, "G", 0.0) or 0.0) or e / 2.6
            expected = expected_brace_strength(
                shape,
                Steel(Fy=fy, E=e, G=g, Fu=fu),
                ry=settings.ry,
                length_x=lengths[0],
                length_y=lengths[1],
                k_x=overrides.k_major,
                k_y=overrides.k_minor,
                method=settings.method,
            )
            if peak or force < 0.0:
                state, magnitude = "tension", expected.tension
            else:
                state, magnitude = "compression", expected.compression
            record = CapacityDesign(
                load_set=label,
                brace_element_id=element.id,
                shape=shape.name,
                state=state,
                analysis_force=force,
                expected_force=magnitude,
                factor=max(1.0, magnitude / abs(force)),
            )
            if best is None or record.factor > best.factor:
                best = record
        if best is None:
            continue
        best.skipped = skipped
        if skipped:
            best.notes.append(
                "No seismic force, left out of the factor: braces "
                + ", ".join(str(eid) for eid in skipped)
                + "."
            )
        if best.factor > 1.0:
            out.append(
                (
                    f"{label} (SCBF capacity)",
                    {
                        cid: value * best.factor if cid in seismic else value
                        for cid, value in alt.items()
                    },
                )
            )
        records.append(best)
    return out, records, notes


def _prefix_check(check: MemberCheck, prefix: str) -> None:
    """Name every limit state of ``check`` under the capacity-design prefix."""
    check.ratios = {prefix + key: value for key, value in check.ratios.items()}
    check.equations = {prefix + key: value for key, value in check.equations.items()}
    check.checks = [replace(item, name=prefix + item.name) for item in check.checks]


def _value(value: float | int | None, name: str) -> float:
    if value is None:
        raise ValueError(f"Missing {name} for this Chapter J check.")
    return float(value)


def _filler_constants(units: Any) -> tuple[float, float]:
    """J5.2 threshold and slope in the project's length units."""
    if units == UnitSystem.SI_MM_N:
        return 6.0, 0.0154
    if units == UnitSystem.SI_M_N:
        return 0.006, 15.4
    if units == UnitSystem.US_FT_KIP:
        return 0.25 / 12.0, 4.8
    return 0.25, 0.4


def _sidesway_cr(units: Any) -> tuple[float, float]:
    """J10.4 Cr (low, high) in the project's stress unit."""
    if units == UnitSystem.SI_MM_N:
        return 3.3e6, 6.6e6
    if units == UnitSystem.SI_M_N:
        return 3.3e12, 6.6e12
    if units == UnitSystem.US_FT_KIP:
        return 480_000.0 * 144.0, 960_000.0 * 144.0
    return 480_000.0, 960_000.0


def _chapter_j_strength(check: Any, method: Any, *, units: Any) -> Any:
    """Dispatch one saved Chapter J check to its strength function."""
    kind = check.check_type
    filler_threshold, filler_slope = _filler_constants(units)
    if kind == "fillet_weld":
        return fillet_weld_strength(
            fexx=_value(check.fexx, "fexx"),
            leg=_value(check.weld_leg, "weld_leg"),
            length=_value(check.weld_length, "weld_length"),
            both_sides=check.weld_both_sides,
            filler_thickness=check.filler_thickness,
            filler_transfers_force=check.filler_transfers_force,
            method=method,
        )
    if kind == "bolt_shear":
        return bolt_shear_strength(
            fnv=_value(check.fn, "fn"),
            diameter=_value(check.bolt_diameter, "bolt_diameter"),
            count=int(_value(check.bolt_count, "bolt_count")),
            filler_thickness=check.filler_thickness,
            filler_threshold=filler_threshold,
            filler_slope=filler_slope,
            method=method,
        )
    if kind == "bolt_tension":
        return bolt_tension_strength(
            fnt=_value(check.fn, "fn"),
            diameter=_value(check.bolt_diameter, "bolt_diameter"),
            count=int(_value(check.bolt_count, "bolt_count")),
            method=method,
        )
    if kind == "bolt_bearing":
        return bolt_bearing_strength(
            fu=_value(check.fu, "fu"),
            thickness=_value(check.thickness, "thickness"),
            diameter=_value(check.bolt_diameter, "bolt_diameter"),
            count=int(_value(check.bolt_count, "bolt_count")),
            edge_distance=_value(check.edge_distance, "edge_distance"),
            hole_diameter=check.hole_diameter,
            deformation=check.deformation,
            method=method,
        )
    if kind == "slip_critical":
        return slip_critical_strength(
            mu=_value(check.mu, "mu"),
            tb=_value(check.tb, "tb"),
            ns=int(_value(check.slip_planes, "slip_planes")),
            count=int(_value(check.bolt_count, "bolt_count")),
            hole_type=check.hole_type,
            method=method,
        )
    if kind == "plate_shear_yielding":
        return plate_shear_yielding(
            fy=_value(check.fy, "fy"), agv=_value(check.agv, "agv"), method=method
        )
    if kind == "plate_shear_rupture":
        return plate_shear_rupture(
            fu=_value(check.fu, "fu"), anv=_value(check.anv, "anv"), method=method
        )
    if kind == "block_shear":
        return block_shear_strength(
            fy=_value(check.fy, "fy"),
            fu=_value(check.fu, "fu"),
            agv=_value(check.agv, "agv"),
            anv=_value(check.anv, "anv"),
            ant=float(check.ant or 0.0),
            uniform_tension=check.uniform_tension,
            method=method,
        )
    if kind == "bearing_strength":
        return bearing_strength(
            fy=_value(check.fy, "fy"),
            apb=_value(check.apb, "apb"),
            method=method,
        )
    if kind == "concrete_bearing":
        return concrete_bearing_strength(
            fc=_value(check.fc, "fc"),
            a1=_value(check.a1, "a1"),
            a2=check.a2,
            method=method,
        )
    if kind == "splice":
        return splice_strength(
            nominal=_value(check.splice_nominal, "splice_nominal"),
            method=method,
        )
    if kind == "flange_local_bending":
        return flange_local_bending(
            fyf=_value(check.fy, "fy"),
            tf=_value(check.flange_thickness, "flange_thickness"),
            bf=_value(check.flange_width, "flange_width"),
            lb=_value(check.bearing_length, "bearing_length"),
            distance_to_end=_value(check.distance_to_end, "distance_to_end"),
            method=method,
        )
    if kind == "web_local_yielding":
        return web_local_yielding(
            fyw=_value(check.fy, "fy"),
            tw=_value(check.web_thickness, "web_thickness"),
            k=_value(check.fillet_k, "fillet_k"),
            lb=_value(check.bearing_length, "bearing_length"),
            d=_value(check.member_depth, "member_depth"),
            distance_to_end=_value(check.distance_to_end, "distance_to_end"),
            method=method,
        )
    if kind == "web_local_crippling":
        return web_local_crippling(
            fyw=_value(check.fy, "fy"),
            e=_value(check.elastic_modulus, "elastic_modulus"),
            tw=_value(check.web_thickness, "web_thickness"),
            tf=_value(check.flange_thickness, "flange_thickness"),
            d=_value(check.member_depth, "member_depth"),
            lb=_value(check.bearing_length, "bearing_length"),
            distance_to_end=_value(check.distance_to_end, "distance_to_end"),
            qf=check.chord_factor,
            method=method,
        )
    if kind == "web_sidesway_buckling":
        cr_low, cr_high = _sidesway_cr(units)
        return web_sidesway_buckling(
            fy=_value(check.fy, "fy"),
            sx=_value(check.section_modulus, "section_modulus"),
            mr=_value(check.required_moment, "required_moment"),
            tw=_value(check.web_thickness, "web_thickness"),
            tf=_value(check.flange_thickness, "flange_thickness"),
            h=_value(check.clear_web_height, "clear_web_height"),
            bf=_value(check.flange_width, "flange_width"),
            lb=_value(check.bearing_length, "bearing_length"),
            restrained=check.flange_restrained,
            cr_low=cr_low,
            cr_high=cr_high,
            method=method,
        )
    if kind == "web_compression_buckling":
        return web_compression_buckling(
            e=_value(check.elastic_modulus, "elastic_modulus"),
            fyw=_value(check.fy, "fy"),
            tw=_value(check.web_thickness, "web_thickness"),
            h=_value(check.clear_web_height, "clear_web_height"),
            qf=check.chord_factor,
            distance_to_end=_value(check.distance_to_end, "distance_to_end"),
            d=_value(check.member_depth, "member_depth"),
            method=method,
        )
    raise ValueError(f"Unknown Chapter J check type {kind!r}.")


def _chapter_j_results(project: Any, settings: DesignSettings) -> list[ChapterJResult]:
    """Run every saved Chapter J check with the design method."""
    out: list[ChapterJResult] = []
    for check in project.chapter_j_checks:
        result = ChapterJResult(
            check_id=check.id,
            name=check.name,
            check_type=check.check_type,
            demand=check.demand,
        )
        try:
            strength = _chapter_j_strength(
                check,
                settings.method,
                units=project.meta.units,
            )
        except ValueError as exc:
            result.status = "invalid"
            result.notes.append(str(exc))
            out.append(result)
            continue
        result.nominal = strength.nominal
        result.available = strength.available
        if strength.available <= 0.0 and strength.nominal <= 0.0:
            result.status = "not required"
            result.ratio = 0.0
        else:
            result.ratio = (
                check.demand / strength.available if strength.available > 0.0 else math.inf
            )
            result.status = "OK" if result.ratio <= 1.0 else "NG"
        result.equation = strength.equation
        result.steps = list(strength.steps)
        result.notes = list(strength.notes)
        out.append(result)
    return out


def steel_frame_check(
    project: Any,
    results: Mapping[int, Any],
    settings: DesignSettings | None = None,
) -> DesignReport:
    """Check every frame member against AISC 360-16 over the chosen load sets.

    ``results`` maps case id to the static or response spectrum results of the
    project as it is now (the window's case results cache).
    """
    settings = settings or DesignSettings()
    report = DesignReport()
    units = project.meta.units
    fy, fu = project_steel(settings, units)
    direct = settings.stability_method == "direct"
    if direct:
        report.notes.append(
            "Direct Analysis Method (AISC 360-16 C1, C3): K = 1 for every member, and B1 "
            "amplifies the moments of members in compression for P-delta (C2.1b)."
        )
    if settings.seismic_system not in CHECKED_SEISMIC_SYSTEMS:
        report.notes.append(
            f"Seismic system {settings.seismic_system}: its AISC 341 provisions are not "
            "checked here; the members are checked against AISC 360 only."
        )
    seismic_check = (
        settings.seismic_system if settings.seismic_system in CHECKED_SEISMIC_SYSTEMS else "none"
    )

    # Station fields of every case a load set needs, read once.
    fields: dict[int, Field] = {}
    alternatives: list[tuple[str, Alternative]] = []
    for load_set in settings.load_sets or default_load_sets(project):
        label = load_set_label(project, load_set)
        try:
            options = expand(project, load_set.source, load_set.ref_id)
        except UnsupportedLoadSetError as exc:
            report.notes.append(f"{label} not checked: {exc}.")
            continue
        needed = sorted({cid for alt in options for cid in alt})
        missing = [cid for cid in needed if cid not in results]
        if missing:
            names = ", ".join(
                load_set_label(project, DesignLoadSet(source="case", ref_id=c)) for c in missing
            )
            report.notes.append(f"{label} not checked: run {names} first.")
            continue
        for cid in needed:
            if cid not in fields:
                found = results[cid]
                fields[cid] = (
                    spectrum_field(project, found)
                    if isinstance(found, ResponseSpectrumResults)
                    else static_field(project, found)
                )
        report.load_sets.append(label)
        alternatives += [(label, alt) for alt in options]

    capacity, capacity_records, capacity_notes = _capacity_alternatives(
        project,
        fields,
        alternatives,
        settings,
        units,
        fy=fy,
        fu=fu,
    )
    report.capacity_design = capacity_records
    report.notes.extend(capacity_notes)
    evaluations: list[tuple[str, Alternative, str]] = [
        (label, alt, "") for label, alt in alternatives
    ]
    evaluations += [(label, alt, "SCBF capacity ") for label, alt in capacity]
    if settings.seismic_system == "OCBF":
        report.notes.append(
            "OCBF F1.5b limits V/inverted-V brace slenderness to 4 sqrt(E/Fy); "
            "F1.5c and F1.6a require the overstrength seismic load for beams and "
            "brace connections."
        )
        report.notes.append(
            "OCBF F1.5c: "
            + (
                "the O0 overstrength combinations are included in the envelope."
                if any("O0:" in label for label in report.load_sets)
                else "no O0 overstrength combination is selected; add it to design "
                "the beams and their connections."
            )
        )
        report.notes.append(
            "OCBF F1.4b: K-braced frames are not permitted; the model does not identify K-bracing."
        )
        report.notes.append(
            "OCBF F1.4c: the multi-tiered OCBF requirements (opposing brace pairs, "
            "struts, column torsional bracing, 1.5Emh connections/struts/columns "
            "and notional loads) are not checked."
        )
        report.notes.append(
            "OCBF F1.5a: braces are checked as moderately ductile members per D1.1."
        )

    frame_elements = [
        element for element in project.elements if isinstance(element, FRAME_ELEMENT_CLASSES)
    ]
    element_roles = {
        element.id: _member_role(project, element, settings) for element in frame_elements
    }
    elements_at_node: dict[int, list[Any]] = {}
    for element in frame_elements:
        for node_id in element.nodes:
            elements_at_node.setdefault(int(node_id), []).append(element)
    overstrength = any("O0:" in label for label in report.load_sets)
    physical = _design_members(project, settings)
    elements_by_id = {e.id: e for e in project.elements}

    sections = {s.id: s for s in project.sections}
    for element in project.elements:
        if not isinstance(element, FRAME_ELEMENT_CLASSES):
            continue
        result = MemberResult(element_id=element.id)
        report.members.append(result)
        overrides = settings.member(element.id)
        section = sections.get(getattr(element, "section_id", -1))
        name = overrides.shape or (getattr(section, "name", "") or "")
        try:
            shape = shape_in_units(name, units, settings.built_up_by_name())
        except (KeyError, ValueError) as exc:
            reason = exc.args[0] if exc.args else str(exc)
            result.notes.append(f"No AISC shape to check with: {reason}")
            continue
        result.shape = shape.name
        member_fy, member_fu, result.grade = member_steel(
            settings, shape_family(shape), overrides, units
        )
        k_major, k_minor = overrides.k_major, overrides.k_minor
        if direct and (k_major != 1.0 or k_minor != 1.0):
            result.notes.append(
                f"K = {k_major:g} / {k_minor:g} entered; the direct analysis method uses K = 1."
            )
            k_major = k_minor = 1.0
        if isinstance(section, ElasticSection) and abs(section.A - shape.A) > 0.02 * shape.A:
            result.notes.append(
                f"The analysis section's area differs from {shape.name}'s by "
                f"{abs(section.A - shape.A) / shape.A:.0%}."
            )
        e = float(getattr(section, "E", 0.0) or 0.0) or 29000.0 * stress_scale(SOURCE_UNITS, units)
        g = float(getattr(section, "G", 0.0) or 0.0) or e / 2.6
        steel = Steel(Fy=member_fy, E=e, G=g, Fu=member_fu)
        role = _member_role(project, element, settings)
        m_major, v_major, m_minor, v_minor, about_major = _axes(project, section, shape)
        if not about_major:
            result.notes.append("Bent about the shape's minor axis in this 2D model.")
        member = physical.get(element.id)
        if member is not None:
            result.member_id = member.id
        auto_x, auto_y, auto_b = _unbraced(
            member, element, m_major, m_minor, _length(project, element)
        )
        lx = overrides.length_major or auto_x
        ly = overrides.length_minor or auto_y
        lb = overrides.length_ltb or auto_b
        result.unbraced = (lx, ly, lb)
        if not alternatives:
            result.notes.append("No load set with results.")
            continue
        worst: tuple[float, MemberCheck, str, float] | None = None
        worst_capacity = 0.0
        max_ratios: dict[str, float] = {}
        for label, alt, prefix in evaluations:
            if prefix and role == "brace":
                continue
            values: dict[str, np.ndarray] = {}
            for component in ("N", "V2", "V3", "M2", "M3"):
                total = np.zeros(STATIONS)
                for cid, factor in alt.items():
                    per_case = fields[cid].get(component, {}).get(element.id)
                    if per_case is not None:
                        total = total + factor * per_case
                values[component] = total
            major_moment = values[m_major] if m_major else np.zeros(STATIONS)
            cb = overrides.cb
            if cb is None and m_major and member is not None and len(member.element_ids) > 1:
                # Cb over the whole laterally unbraced segment, not this element alone.
                segment_moments = {
                    eid: sum(
                        (
                            factor * fields[cid].get(m_major, {}).get(eid, np.zeros(STATIONS))
                            for cid, factor in alt.items()
                        ),
                        np.zeros(STATIONS),
                    )
                    for eid in member.element_ids
                }
                lateral = _bending_axes(m_major, m_minor)[1]
                cb = _segment_cb(member, element.id, lateral, segment_moments, elements_by_id)
            if cb is None:
                quarter = [float(np.interp(s, _GRID, major_moment)) for s in (0.25, 0.5, 0.75)]
                peak = float(np.max(np.abs(major_moment)))
                cb = cb_from_moments(peak, *quarter)
            # The diagrams draw compression positive (OpenSees' end-i axial force);
            # the check takes tension positive. Evaluate every station with the
            # axial force, moments and shears of that same station, so the H1
            # interaction is not built from maxima at different places.
            for k, station_value in enumerate(_GRID):
                demand = Demand(
                    axial=-float(values["N"][k]),
                    moment_major=float(values[m_major][k]) if m_major else 0.0,
                    moment_minor=float(values[m_minor][k]) if m_minor else 0.0,
                    shear_major=float(values[v_major][k]) if v_major else 0.0,
                    shear_minor=float(values[v_minor][k]) if v_minor else 0.0,
                    cb=cb,
                )
                if not about_major:
                    demand = Demand(
                        axial=-float(values["N"][k]),
                        moment_major=0.0,
                        moment_minor=float(values["M3"][k]),
                        shear_major=0.0,
                        shear_minor=float(values["V2"][k]),
                    )
                check = check_member(
                    shape,
                    steel,
                    settings.method,
                    demand,
                    length_x=lx,
                    length_y=ly,
                    length_ltb=lb,
                    k_x=k_major,
                    k_y=k_minor,
                    net_area=overrides.net_area,
                    shear_lag=overrides.shear_lag,
                    p_delta=settings.p_delta or direct,
                )
                if seismic_check != "none":
                    ca_value = ca(
                        max(0.0, -demand.axial),
                        settings.ry,
                        steel.Fy,
                        shape.A,
                        method=settings.method,
                    )
                    for item in member_limits(
                        shape,
                        role=role,
                        system=seismic_check,
                        e=steel.E,
                        ry=settings.ry,
                        fy=steel.Fy,
                        ca_value=ca_value,
                    ):
                        key = f"AISC 341 {item.element} (case {item.case})"
                        check.ratios[key] = item.utilization
                        check.equations[key] = f"AISC 341-22 D1.1 case {item.case}"
                        check.checks.append(
                            LimitStateCheck(
                                key,
                                f"AISC 341-22 D1.1 case {item.case}",
                                item.ratio,
                                item.limit,
                                item.utilization,
                                (
                                    CalcStep(
                                        "Element slenderness",
                                        "lambda = b/t or h/tw",
                                        f"{item.ratio:.6g}",
                                        item.ratio,
                                    ),
                                    CalcStep(
                                        "Ductility limit",
                                        f"D1.1 case {item.case}",
                                        f"{item.limit:.6g}",
                                        item.limit,
                                    ),
                                ),
                            )
                        )
                if settings.seismic_system == "SCBF" and role == "brace":
                    radius = min(
                        float(getattr(shape, "rx", math.inf)),
                        float(getattr(shape, "ry", math.inf)),
                        float(getattr(shape, "rz", math.inf)),
                    )
                    if radius > 0.0 and math.isfinite(radius):
                        lc = max(
                            k_major * lx,
                            k_minor * ly,
                        )
                        slenderness = lc / radius
                        key = "SCBF brace slenderness (F2.5b)"
                        check.ratios[key] = slenderness / 200.0
                        check.equations[key] = "AISC 341-22 F2.5b"
                        check.checks.append(
                            LimitStateCheck(
                                key,
                                "AISC 341-22 F2.5b",
                                slenderness,
                                200.0,
                                slenderness / 200.0,
                                (
                                    CalcStep(
                                        "Brace slenderness",
                                        "Lc/r <= 200 (Lc = KL)",
                                        f"{slenderness:.6g}",
                                        slenderness,
                                    ),
                                ),
                            )
                        )
                    if overrides.net_area is None:
                        note = (
                            "SCBF F2.5b(c): the effective net area needs An; "
                            "Ae >= Ag is not checked."
                        )
                        if note not in check.notes:
                            check.notes.append(note)
                    else:
                        effective = overrides.shear_lag * overrides.net_area
                        key = "SCBF brace net area (F2.5b(c))"
                        check.ratios[key] = shape.A / effective if effective > 0 else math.inf
                        check.equations[key] = "AISC 341-22 F2.5b(c)"
                        check.checks.append(
                            LimitStateCheck(
                                key,
                                "AISC 341-22 F2.5b(c)",
                                shape.A,
                                effective,
                                shape.A / effective if effective > 0 else math.inf,
                                (
                                    CalcStep(
                                        "Effective net area",
                                        "Ae = U An",
                                        f"{effective:.6g}",
                                        effective,
                                    ),
                                    CalcStep(
                                        "Brace gross area",
                                        "Ag",
                                        f"{shape.A:.6g}",
                                        shape.A,
                                    ),
                                ),
                            )
                        )
                    expected = settings.ry * steel.Fy * shape.A
                    note = (
                        f"SCBF expected brace yield strength Ry Fy Ag = {expected:.6g}; "
                        "use it for the brace connections."
                    )
                    if note not in check.notes:
                        check.notes.append(note)
                elif settings.seismic_system == "OCBF" and role == "brace":
                    radius = min(
                        float(getattr(shape, "rx", math.inf)),
                        float(getattr(shape, "ry", math.inf)),
                        float(getattr(shape, "rz", math.inf)),
                    )
                    if radius > 0.0 and math.isfinite(radius):
                        lc = max(
                            k_major * lx,
                            k_minor * ly,
                        )
                        slenderness = lc / radius
                        limit = ocbf_brace_slenderness_limit(steel.E, steel.Fy)
                        key = "OCBF brace slenderness (F1.5b)"
                        check.ratios[key] = slenderness / limit
                        check.equations[key] = "AISC 341-22 F1.5b"
                        check.checks.append(
                            LimitStateCheck(
                                key,
                                "AISC 341-22 F1.5b",
                                slenderness,
                                limit,
                                slenderness / limit,
                                (
                                    CalcStep(
                                        "Brace slenderness",
                                        "Lc/r <= 4 sqrt(E/Fy)",
                                        f"{slenderness:.6g}",
                                        slenderness,
                                    ),
                                    CalcStep(
                                        "OCBF limit",
                                        "4 sqrt(E/Fy)",
                                        f"{limit:.6g}",
                                        limit,
                                    ),
                                ),
                            )
                        )
                    note = (
                        "OCBF F1.5b applies to braces in V or inverted-V "
                        "configurations; this check applies it to every OCBF brace "
                        "(conservative). F1.6a: brace connections shall use the "
                        "overstrength seismic load; the exception caps tension at "
                        "Ry Fy Ag/alpha_s and compression at the expected "
                        "compression/alpha_s."
                    )
                    if note not in check.notes:
                        check.notes.append(note)
                elif settings.seismic_system == "OCBF" and role == "beam":
                    note = (
                        "OCBF F1.5c: beams and their connections shall be designed "
                        "with the overstrength seismic load. "
                        + (
                            "The O0 overstrength combinations are included in the envelope."
                            if overstrength
                            else "No O0 overstrength combination is selected; the "
                            "beam is not checked for F1.5c."
                        )
                    )
                    if note not in check.notes:
                        check.notes.append(note)
                    intersections = [
                        node_id
                        for node_id in element.nodes
                        if any(
                            element_roles[other.id] == "brace"
                            for other in elements_at_node.get(int(node_id), [])
                        )
                        and not any(
                            element_roles[other.id] == "column"
                            for other in elements_at_node.get(int(node_id), [])
                        )
                    ]
                    if intersections:
                        note = (
                            "OCBF F1.4a: a brace intersects this beam away from a "
                            f"beam-column connection at node(s) {intersections}; the "
                            "beam must be continuous between columns and braced at "
                            "the intersection (one set of lateral braces) to D1.2a. "
                            "The model does not check the continuity or the lateral "
                            "brace."
                        )
                        if note not in check.notes:
                            check.notes.append(note)
                if prefix:
                    _prefix_check(check, prefix)
                ratio = check.governing[1]
                if prefix:
                    worst_capacity = max(worst_capacity, ratio)
                for name, value in check.ratios.items():
                    max_ratios[name] = max(max_ratios.get(name, 0.0), value)
                if worst is None or ratio > worst[0]:
                    worst = (ratio, check, label, float(station_value))
        if worst_capacity:
            result.capacity_ratio = worst_capacity
        assert worst is not None
        ratio, check, label, station = worst
        key = check.governing[0]
        result.ratio = ratio
        result.check = key
        result.equation = check.equations.get(key, "")
        result.load_set = label
        result.station = station
        result.ratios = max_ratios
        result.checks = list(check.checks)
        result.notes.extend(dict.fromkeys(check.notes))
        result.status = "NG" if ratio > settings.ratio_limit else "OK"
    if settings.seismic_system == "SMF":
        report.joints = _strong_column_weak_beam(
            project,
            fields,
            alternatives,
            settings,
            units,
            fy=fy,
            fu=fu,
        )
    if project.connections:
        report.connections = _connection_results(
            project,
            settings,
            units,
            fy=fy,
            fu=fu,
            fields=fields,
            alternatives=alternatives,
        )
    if settings.seismic_system == "SCBF":
        report.protected_zones = _scbf_protected_zones(project, settings, units)
        report.scbf_joints = _scbf_beam_column_joints(project, settings, units, fy=fy)
    if project.gussets:
        report.gussets = _gusset_results(project, settings, units, fy=fy)
    if project.column_splices:
        report.column_splices = _column_splice_results(project, settings, units, fy=fy)
    if project.chapter_j_checks:
        report.chapter_j = _chapter_j_results(project, settings)
    return report


# ──────────────────────────── storey drift ────────────────────────────
@dataclass
class DriftRow:
    storey: str
    height: float
    drift: tuple[float, ...]
    """Drift ratio per lateral axis, amplified."""
    ratio: float
    """Largest amplified drift over the allowable one."""


@dataclass
class DriftReport:
    load_set: str
    limit: float
    amplification: float
    rows: list[DriftRow] = field(default_factory=list)

    @property
    def worst(self) -> float:
        return max((row.ratio for row in self.rows), default=0.0)


def storey_drift_check(
    project: Any, results: Any, settings: DesignSettings | None = None
) -> DriftReport | None:
    """Amplified storey drift ratios of one static or response spectrum result.

    ``None`` when the project has no storeys or the result kind has no drift.
    """
    from opensees_studio.core.mass_source import effective_nodal_masses
    from opensees_studio.core.storey_results import combine_storey_response, storey_profile

    settings = settings or DesignSettings()
    if not project.storeys:
        return None
    case = next((c for c in project.analyses if c.id == results.case_id), None)
    label = f"Case {case.name}" if case is not None else f"Case {results.case_id}"
    if isinstance(results, StaticResults):
        last = {nid: np.atleast_2d(v)[-1] for nid, v in results.node_disp.items()}
        profile = storey_profile(project, last)
        levels, drift = profile.levels, profile.drift
    elif isinstance(results, ResponseSpectrumResults):
        modes = [m for m in results.modes if m.modal_peak_disp]
        combined = combine_storey_response(
            project,
            [m.modal_peak_disp for m in modes],
            [m.angular_frequency for m in modes],
            effective_nodal_masses(project),
            method=results.combination,
            damping=results.damping_ratio,
        )
        levels, drift = combined.levels, combined.drift
    else:
        return None
    report = DriftReport(label, settings.drift_limit, settings.drift_amplification)
    for level, row in zip(levels, drift, strict=True):
        amplified = tuple(abs(float(v)) * settings.drift_amplification for v in row)
        worst = max(amplified, default=0.0)
        report.rows.append(
            DriftRow(
                storey=level.storey.name or str(level.storey.id),
                height=float(level.height),
                drift=amplified,
                ratio=worst / settings.drift_limit if settings.drift_limit > 0 else math.inf,
            )
        )
    return report


def _joint_station(element: Any, node_id: int) -> int:
    """The station of ``element`` at ``node_id``: 0 at its first node, else the end."""
    return 0 if element.nodes[0] == node_id else STATIONS - 1


def _ishape_members(
    project: Any, settings: DesignSettings, units: Any
) -> dict[int, tuple[IShape, str, float, float]]:
    """Element id -> (I-shape, role, length, depth) for the E3.4a joints."""
    sections = {s.id: s for s in project.sections}
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    out: dict[int, tuple[IShape, str, float, float]] = {}
    for element in project.elements:
        if not isinstance(element, FRAME_ELEMENT_CLASSES):
            continue
        overrides = settings.member(element.id)
        section = sections.get(getattr(element, "section_id", -1))
        name = overrides.shape or (getattr(section, "name", "") or "")
        try:
            shape = shape_in_units(name, units, settings.built_up_by_name())
        except (KeyError, ValueError):
            continue
        if not isinstance(shape, IShape):
            continue
        length = float(np.linalg.norm(coords[element.nodes[1]] - coords[element.nodes[0]]))
        out[element.id] = (shape, _member_role(project, element, settings), length, shape.d)
    return out


def _strong_column_weak_beam(
    project: Any,
    fields: dict[int, Field],
    alternatives: list[tuple[str, Alternative]],
    settings: DesignSettings,
    units: Any,
    *,
    fy: float,
    fu: float,
) -> list[JointResult]:
    """E3.4a at every joint of a 2D frame, over the load sets with results.

    The smallest E3-1 ratio over the load sets is reported. The E3.4a
    exception for light columns in one-story or top-story buildings is not
    applied: every joint is checked, which is conservative.
    """
    if project.ndm != 2 or settings.seismic_system != "SMF" or not alternatives:
        return []
    members = _ishape_members(project, settings, units)
    rbs: dict[int, tuple[float, float]] = {}
    for connection in project.connections:
        if connection.beam_element_id not in members:
            continue
        shape = members[connection.beam_element_id][0]
        try:
            geometry = rbs_geometry(connection, shape)
        except ValueError:
            continue
        rbs[connection.beam_element_id] = (
            rbs_mpr(geometry, ry=settings.ry, fy=fy, fu=fu or None),
            geometry.sh,
        )
    out: list[JointResult] = []
    for node in project.nodes:
        incident = [
            element
            for element in project.elements
            if isinstance(element, FRAME_ELEMENT_CLASSES) and node.id in element.nodes
        ]
        columns = [
            element
            for element in incident
            if members.get(element.id, (None, "", 0, 0))[1] == "column"
        ]
        beams = [
            element
            for element in incident
            if members.get(element.id, (None, "", 0, 0))[1] == "beam"
        ]
        if not columns or not beams:
            continue
        result = JointResult(node_id=node.id, columns=len(columns), beams=len(beams))
        beam_shapes = [members[element.id][0] for element in beams]
        column_shapes = [members[element.id][0] for element in columns]
        result.continuity_tcf = min(shape.tf for shape in column_shapes)
        result.continuity_tlim = continuity_tlim(max(shape.bf for shape in beam_shapes))
        result.continuity_required = result.continuity_tcf < result.continuity_tlim
        result.continuity_plate_t = continuity_plate_thickness(
            [shape.tf for shape in beam_shapes], two_sided=len(beams) >= 2
        )
        result.continuity_status = "required" if result.continuity_required else "check E3.6f.1(a)"
        for label, alt in alternatives:
            joint_columns = []
            column_shears = []
            for element in columns:
                shape, _, _, depth = members[element.id]
                pr = 0.0
                shear = 0.0
                for cid, factor in alt.items():
                    values = fields.get(cid, {}).get("N", {}).get(element.id)
                    if values is not None:
                        pr += factor * float(values[_joint_station(element, node.id)])
                    values = fields.get(cid, {}).get("V2", {}).get(element.id)
                    if values is not None:
                        shear += factor * float(values[_joint_station(element, node.id)])
                joint_columns.append(JointColumn(shape.Zx, fy, shape.A, max(0.0, pr), depth))
                column_shears.append(abs(shear))
            joint_beams = []
            sum_mf = 0.0
            dc = max(members[element.id][3] for element in columns)
            for element in beams:
                shape, _, length, _ = members[element.id]
                shear = 0.0
                moment = 0.0
                for cid, factor in alt.items():
                    values = fields.get(cid, {}).get("V2", {}).get(element.id)
                    if values is not None:
                        shear += factor * float(values[_joint_station(element, node.id)])
                    values = fields.get(cid, {}).get("M3", {}).get(element.id)
                    if values is not None:
                        moment += factor * float(values[_joint_station(element, node.id)])
                face_offset = dc / 2.0
                mpr_override: float | None = None
                mv_override: float | None = None
                if element.id in rbs:
                    mpr_override, face_offset = rbs[element.id]
                    vh = max(
                        2.0 * mpr_override / max(length - 2.0 * face_offset, 1e-9),
                        abs(shear),
                    )
                    mv_override = vh * face_offset
                joint_beams.append(
                    JointBeam(
                        shape.Zx,
                        fy,
                        length,
                        abs(shear),
                        mpr_override,
                        mv_override,
                    )
                )
                # A1: the face moment is the end moment less the shear over the
                # face offset (dc/2, or Sh for an RBS).
                sum_mf += max(0.0, abs(moment) - abs(shear) * face_offset)
            pair = joint_scwb(
                joint_columns,
                joint_beams,
                ry=settings.ry,
                fu=fu,
                method=settings.method,
            )
            deepest = max(beams, key=lambda element: members[element.id][0].d)
            db = members[deepest.id][0].d
            tbf = members[deepest.id][0].tf
            demand = panel_zone_demand(sum_mf, db, tbf, max(column_shears, default=0.0))
            capacity = min(
                panel_zone_strength(
                    fy,
                    members[element.id][0].d,
                    members[element.id][0].tw,
                    members[element.id][0].bf,
                    members[element.id][0].tf,
                    db,
                    column.pr,
                    fy * members[element.id][0].A,
                    method=settings.method,
                    inelastic=True,
                )
                for element, column in zip(columns, joint_columns, strict=True)
            )
            if capacity > 0.0:
                panel_ratio = demand / capacity
                if panel_ratio > result.panel_ratio:
                    result.panel_ratio = panel_ratio
                    result.panel_demand = demand
                    result.panel_capacity = capacity
            if pair is None:
                continue
            mpc, mbe = pair
            if mbe <= 0.0:
                continue
            ratio = mpc / mbe
            if result.ratio <= 0.0 or ratio < result.ratio:
                result.ratio = ratio
                result.load_set = label
        if result.ratio <= 0.0:
            continue
        result.status = "OK" if result.ratio > 1.0 else "NG"
        result.panel_status = "OK" if result.panel_ratio <= 1.0 else "NG"
        out.append(result)
    return out


def _connection_results(
    project: Any,
    settings: DesignSettings,
    units: Any,
    *,
    fy: float,
    fu: float,
    fields: dict[int, Field],
    alternatives: list[tuple[str, Alternative]],
) -> list[ConnectionResult]:
    """The AISC 358 RBS connections with their checked geometry."""
    sections = {s.id: s for s in project.sections}
    elements = {e.id: e for e in project.elements}
    out: list[ConnectionResult] = []
    for connection in project.connections:
        result = ConnectionResult(
            connection_id=connection.id,
            beam_element_id=connection.beam_element_id,
            column_element_id=connection.column_element_id,
        )
        beam = elements.get(connection.beam_element_id)
        if beam is None:
            result.status = "invalid"
            result.notes.append("The beam element does not exist.")
            out.append(result)
            continue
        section = sections.get(getattr(beam, "section_id", -1))
        name = getattr(section, "name", "") or ""
        try:
            shape = shape_in_units(name, units, settings.built_up_by_name())
        except (KeyError, ValueError) as exc:
            result.status = "invalid"
            result.notes.append(f"No AISC shape for the beam: {exc}")
            out.append(result)
            continue
        if not isinstance(shape, IShape):
            result.status = "invalid"
            result.notes.append("RBS connections require an I-shaped beam.")
            out.append(result)
            continue
        result.shape = shape.name
        result.a, result.b, result.c = connection.a, connection.b, connection.c
        try:
            geometry = rbs_geometry(connection, shape)
        except ValueError as exc:
            result.status = "invalid"
            result.notes.append(str(exc))
            out.append(result)
            continue
        result.sh = geometry.sh
        result.z_rbs = geometry.z_rbs
        result.mpr = rbs_mpr(geometry, ry=settings.ry, fy=fy, fu=fu or None)
        result.protected_from, result.protected_to = rbs_protected_zone(geometry)
        column = elements.get(connection.column_element_id)
        joint = 0
        beam_length = 0.0
        if column is not None:
            shared = set(beam.nodes) & set(column.nodes)
            if shared:
                joint = min(shared)
                result.joint_node = joint
                coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
                start = coords[joint]
                far = coords[beam.nodes[1] if beam.nodes[0] == joint else beam.nodes[0]]
                direction = far - start
                beam_length = float(np.linalg.norm(direction))
                if beam_length > 0.0:
                    direction = direction / beam_length
                    for node in project.nodes:
                        if node.id in beam.nodes:
                            continue
                        relative = coords[node.id] - start
                        along = float(np.dot(relative, direction))
                        perpendicular = float(np.linalg.norm(relative - along * direction))
                        if 0.0 < along <= result.protected_to and perpendicular <= 1e-6 * max(
                            1.0, beam_length
                        ):
                            result.zone_clear = False
                            support = " (restrained)" if any(node.restraint) else ""
                            result.notes.append(
                                f"Node {node.id} lies inside the protected zone{support}."
                            )
        result.mpe = rbs_mpe(settings.ry, fy, shape.Zx)
        e = float(getattr(section, "E", 0.0) or 0.0) or 29000.0 * stress_scale(SOURCE_UNITS, units)
        g = float(getattr(section, "G", 0.0) or 0.0) or e / 2.6
        steel = Steel(Fy=fy, E=e, G=g, Fu=fu or None)
        if joint and beam_length > 0.0 and alternatives:
            index = _joint_station(beam, joint)
            for _label, alt in alternatives:
                shear = 0.0
                for cid, factor in alt.items():
                    values = fields.get(cid, {}).get("V2", {}).get(beam.id)
                    if values is not None:
                        shear += factor * float(values[index])
                vh = max(
                    2.0 * result.mpr / max(beam_length - 2.0 * result.sh, 1e-9),
                    abs(shear),
                )
                mf = result.mpr + vh * result.sh
                ratio = rbs_flexure_ratio(mf, result.mpe, method=settings.method)
                if ratio > result.flexure_ratio:
                    result.vh = vh
                    result.mf = mf
                    result.flexure_ratio = ratio
            result.flexure_status = "OK" if result.flexure_ratio <= 1.0 else "NG"
            result.shear_demand = result.vh
            result.shear_capacity = shape.shear_major(
                steel, settings.method, length=beam_length
            ).available
            result.shear_ratio = (
                result.shear_demand / result.shear_capacity
                if result.shear_capacity > 0.0
                else math.inf
            )
            result.shear_status = "OK" if result.shear_ratio <= 1.0 else "NG"
            if settings.seismic_system in ("SMF", "IMF"):
                result.span_limit = 7.0 if settings.seismic_system == "SMF" else 5.0
                if column is not None:
                    column_section = sections.get(getattr(column, "section_id", -1))
                    column_name = getattr(column_section, "name", "") or ""
                    try:
                        column_shape = shape_in_units(
                            column_name, units, settings.built_up_by_name()
                        )
                    except (KeyError, ValueError):
                        column_shape = None
                    column_depth = float(getattr(column_shape, "d", 0.0) or 0.0)
                    if column_depth > 0.0 and shape.d > 0.0:
                        clear_span = max(0.0, beam_length - column_depth)
                        result.span_ratio = clear_span / shape.d
                        result.span_status = (
                            "OK" if result.span_ratio >= result.span_limit else "NG"
                        )
            else:
                result.notes.append("AISC 358 RBS is prequalified for SMF and IMF systems only.")
            result.notes.append(
                "AISC 358 2.5: Vu is taken as Vh, which envelopes the mechanism "
                "shear and the analysis shear at the column face; the gravity "
                "shear between the hinge and the face is included in the analysis "
                "term."
            )
            if connection.web_plate_thickness is not None:
                plate_height = connection.web_plate_height
                bolted = connection.web_connection_type == "bolted"
                missing = bolted and (
                    plate_height is None
                    or connection.web_bolt_count is None
                    or connection.web_bolt_diameter is None
                )
                if missing:
                    result.notes.append(
                        "AISC 358 5.5: the web connection is not checked; complete "
                        "the plate height and the bolt data."
                    )
                else:
                    min_thickness = 0.375 * length_scale(SOURCE_UNITS, units)
                    hole_allowance = 0.0625 * length_scale(SOURCE_UNITS, units)
                    bolt_fnv = connection.web_bolt_fnv or 54.0 * stress_scale(SOURCE_UNITS, units)
                    weld_fexx = connection.web_weld_fexx or 70.0 * stress_scale(SOURCE_UNITS, units)
                    checks, web_notes = web_connection_checks(
                        vu=result.shear_demand,
                        plate_thickness=connection.web_plate_thickness,
                        plate_height=plate_height or 1.0,
                        bolt_count=connection.web_bolt_count or 1,
                        bolt_diameter=connection.web_bolt_diameter or 1.0,
                        bolt_fnv=bolt_fnv,
                        hole_allowance=hole_allowance,
                        weld_leg=connection.web_weld_leg,
                        weld_fexx=weld_fexx,
                        fy=fy,
                        fu=fu,
                        min_thickness=min_thickness,
                        method=settings.method,
                        connection_type=connection.web_connection_type,
                    )
                    result.web_checks = checks
                    result.web_ratio = max(check.ratio for check in checks)
                    result.web_status = "OK" if result.web_ratio <= 1.0 else "NG"
                    result.notes.extend(web_notes)
                    result.notes.append(
                        "AISC 358 5.5: the web connection is checked for the "
                        "provided plate, bolts and weld."
                    )
            else:
                result.notes.append(
                    "AISC 358 5.5: the web connection is not checked; set the "
                    "plate thickness/height and the bolt data."
                )
            result.notes.append(
                "AISC 358 5.3(7): supplemental lateral bracing near the RBS is "
                "required; the model does not check it."
            )
            depth_limit = 44.0 * length_scale(SOURCE_UNITS, units)
            if shape.d > depth_limit:
                result.notes.append(
                    f"AISC 358 5.3(2): the beam depth {shape.d:g} exceeds the W44 "
                    f"limit {depth_limit:g}."
                )
            result.notes.append(
                "AISC 358 5.3: the beam weight (408 lb/ft), flange thickness and "
                "built-up-member limits are not in the shape table."
            )
        result.status = "checked"
        out.append(result)
    return out


def _scbf_protected_zones(
    project: Any, settings: DesignSettings, units: Any
) -> list[ProtectedZone]:
    """The F2.5c protected zones of every SCBF brace.

    The centre quarter of the brace and a length equal to its depth at each
    end. A joint or support inside one of them is reported.
    """
    if settings.seismic_system != "SCBF":
        return []
    sections = {s.id: s for s in project.sections}
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    out: list[ProtectedZone] = []
    for element in project.elements:
        if not isinstance(element, FRAME_ELEMENT_CLASSES):
            continue
        if _member_role(project, element, settings) != "brace":
            continue
        section = sections.get(getattr(element, "section_id", -1))
        name = getattr(section, "name", "") or ""
        try:
            shape = shape_in_units(name, units, settings.built_up_by_name())
        except (KeyError, ValueError):
            continue
        depth = float(getattr(shape, "d", getattr(shape, "H", getattr(shape, "D", 0.0))))
        start, end = coords[element.nodes[0]], coords[element.nodes[1]]
        vector = end - start
        length = float(np.linalg.norm(vector))
        if depth <= 0.0 or length <= 0.0:
            continue
        direction = vector / length
        ranges = (
            (0.0, depth / length),
            (0.375, 0.625),
            (max(0.0, 1.0 - depth / length), 1.0),
        )
        zone = ProtectedZone(element_id=element.id, ranges=ranges)
        for node in project.nodes:
            if node.id in element.nodes:
                continue
            along = float(np.dot(coords[node.id] - start, direction)) / length
            if any(low - 1e-9 <= along <= high + 1e-9 for low, high in ranges):
                zone.zone_clear = False
                support = " (restrained)" if any(node.restraint) else ""
                zone.notes.append(f"Node {node.id} lies inside the protected zone{support}.")
        out.append(zone)
    return out


def _plastic_modulus(shape: Any) -> float | None:
    """The plastic section modulus of a shape, major axis first."""
    for attribute in ("Zx", "Z", "Zy"):
        value = getattr(shape, attribute, None)
        if value is not None and float(value) > 0.0:
            return float(value)
    return None


def _scbf_beam_column_joints(
    project: Any,
    settings: DesignSettings,
    units: Any,
    *,
    fy: float,
) -> list[ScbfJointResult]:
    """F2.6b: the required moment of every SCBF beam-to-column joint.

    A joint qualifies when a brace ends there and at least one beam and one
    column frame into it. The required moment is the lesser of the beam and
    column expected plastic moments times 1.1/alpha_s. When an RBS connection
    is modelled at the joint, its available moment ``phi_d Mpe`` gives the
    ratio; otherwise the joint is reported as a simple connection to verify.
    """
    if settings.seismic_system != "SCBF":
        return []
    sections = {s.id: s for s in project.sections}
    frame_elements = [
        element for element in project.elements if isinstance(element, FRAME_ELEMENT_CLASSES)
    ]
    roles = {element.id: _member_role(project, element, settings) for element in frame_elements}
    connected: dict[int, list[Any]] = {}
    for element in frame_elements:
        for node_id in element.nodes:
            connected.setdefault(int(node_id), []).append(element)

    def shape_of(element: Any) -> Any:
        overrides = settings.member(element.id)
        section = sections.get(getattr(element, "section_id", -1))
        name = overrides.shape or (getattr(section, "name", "") or "")
        try:
            return shape_in_units(name, units, settings.built_up_by_name())
        except (KeyError, ValueError):
            return None

    out: list[ScbfJointResult] = []
    for node_id in sorted(connected):
        items = connected[node_id]
        beams = [e for e in items if roles[e.id] == "beam"]
        columns = [e for e in items if roles[e.id] == "column"]
        braces = [e for e in items if roles[e.id] == "brace"]
        if not (beams and columns and braces):
            continue
        beam_data = []
        for beam in beams:
            shape = shape_of(beam)
            z = _plastic_modulus(shape) if shape is not None else None
            if shape is not None and z is not None:
                beam_data.append((beam, shape, z))
        if not beam_data:
            continue
        beam, beam_shape, beam_z = max(beam_data, key=lambda item: item[2])
        column_data = []
        for column in columns:
            shape = shape_of(column)
            z = _plastic_modulus(shape) if shape is not None else None
            if z is not None:
                column_data.append((column, z))
        if not column_data:
            continue
        moment = scbf_beam_column_moment(
            ry=settings.ry,
            beam_fy=fy,
            beam_z=beam_z,
            columns=[(fy, z) for _column, z in column_data],
            method=settings.method,
        )
        result = ScbfJointResult(
            node_id=node_id,
            beam_element_id=beam.id,
            column_element_ids=[column.id for column, _z in column_data],
            brace_element_id=braces[0].id,
            beam_moment=moment.beam_moment,
            column_moment=moment.column_moment,
            required_moment=moment.required,
        )
        connection = next(
            (
                item
                for item in project.connections
                if item.beam_element_id == beam.id
                and item.column_element_id in result.column_element_ids
            ),
            None,
        )
        if connection is None:
            result.status = "simple / not checked"
            result.notes.append(
                "F2.6b: no RBS connection is modelled at this joint. Use a simple "
                "connection with 0.025 rad rotation (B3.4a) or design the connection "
                "for the required moment."
            )
        else:
            try:
                rbs_geometry(connection, beam_shape)
                mpe = rbs_mpe(settings.ry, fy, beam_z)
                available = mpe if settings.method == "LRFD" else mpe / 1.5
                result.available_moment = available
                result.ratio = moment.required / available if available > 0.0 else math.inf
                result.status = "OK" if result.ratio <= 1.0 else "NG"
            except (ValueError, AttributeError) as exc:
                result.status = "invalid"
                result.notes.append(f"The RBS connection is invalid: {exc}")
        out.append(result)
    return out


def _column_splice_results(
    project: Any,
    settings: DesignSettings,
    units: Any,
    *,
    fy: float,
) -> list[ColumnSpliceResult]:
    """The saved column splices checked against F2.6d."""
    sections = {s.id: s for s in project.sections}
    elements = {e.id: e for e in project.elements}
    out: list[ColumnSpliceResult] = []
    for splice in project.column_splices:
        result = ColumnSpliceResult(
            splice_id=splice.id,
            node_id=splice.node_id,
            top_element_id=splice.top_element_id,
            bottom_element_id=splice.bottom_element_id,
            clear_height=splice.clear_height,
        )
        top = elements.get(splice.top_element_id)
        bottom = elements.get(splice.bottom_element_id)
        if top is None or bottom is None:
            result.status = "invalid"
            result.notes.append("The top or bottom column element does not exist.")
            out.append(result)
            continue

        def shape_of(element: Any) -> Any:
            overrides = settings.member(element.id)
            section = sections.get(getattr(element, "section_id", -1))
            name = overrides.shape or (getattr(section, "name", "") or "")
            try:
                return shape_in_units(name, units, settings.built_up_by_name())
            except (KeyError, ValueError):
                return None

        top_shape = shape_of(top)
        bottom_shape = shape_of(bottom)
        if top_shape is None or bottom_shape is None:
            result.status = "invalid"
            result.notes.append("The top or bottom column section is not an AISC shape.")
            out.append(result)
            continue
        top_z = _plastic_modulus(top_shape)
        bottom_z = _plastic_modulus(bottom_shape)
        if top_z is None or bottom_z is None:
            result.status = "invalid"
            result.notes.append("A column shape has no plastic modulus in the table.")
            out.append(result)
            continue
        result.shape_top = top_shape.name
        result.shape_bottom = bottom_shape.name
        demand = column_splice_demand(
            top_fy=fy,
            top_z=top_z,
            bottom_fy=fy,
            bottom_z=bottom_z,
            clear_height=splice.clear_height,
            method=settings.method,
        )
        result.moment = demand.moment
        result.shear = demand.shear
        result.steps = list(demand.steps)
        result.status = "checked"
        out.append(result)
    return out


def _gusset_results(
    project: Any,
    settings: DesignSettings,
    units: Any,
    *,
    fy: float,
) -> list[GussetResult]:
    """The saved gussets checked against the expected brace force."""
    sections = {s.id: s for s in project.sections}
    elements = {e.id: e for e in project.elements}
    out: list[GussetResult] = []
    for gusset in project.gussets:
        result = GussetResult(
            gusset_id=gusset.id,
            brace_element_id=gusset.brace_element_id,
            t=gusset.t,
            b=gusset.b,
            lw=gusset.lw,
            free_length=gusset.free_length,
        )
        brace = elements.get(gusset.brace_element_id)
        if brace is None:
            result.status = "invalid"
            result.notes.append("The brace element does not exist.")
            out.append(result)
            continue
        section = sections.get(getattr(brace, "section_id", -1))
        name = getattr(section, "name", "") or ""
        try:
            shape = shape_in_units(name, units, settings.built_up_by_name())
        except (KeyError, ValueError) as exc:
            result.status = "invalid"
            result.notes.append(f"No AISC shape for the brace: {exc}")
            out.append(result)
            continue
        result.shape = shape.name
        e = float(getattr(section, "E", 0.0) or 0.0) or 29000.0 * stress_scale(SOURCE_UNITS, units)
        g = float(getattr(section, "G", 0.0) or 0.0) or e / 2.6
        overrides = settings.member(brace.id)
        length = _length(project, brace)
        expected = expected_brace_strength(
            shape,
            Steel(Fy=fy, E=e, G=g),
            ry=settings.ry,
            length_x=overrides.length_major or length,
            length_y=overrides.length_minor or length,
            k_x=overrides.k_major,
            k_y=overrides.k_minor,
            method=settings.method,
        )
        result.demand = expected.tension
        result.checks = gusset_checks(
            fy=fy,
            e=e,
            width=gusset.b,
            thickness=gusset.t,
            whitmore_length=gusset.lw,
            free_length=gusset.free_length,
            demand=result.demand,
            brace_thickness=float(getattr(shape, "tf", 0.0) or 0.0),
            method=settings.method,
        )
        demands = brace_connection_demands(
            ry=settings.ry,
            fy=fy,
            ag=shape.A,
            expected_compression=expected.compression,
            plastic_modulus=critical_plastic_modulus(shape),
            method=settings.method,
        )
        result.tension_demand = demands.tension
        result.compression_demand = demands.compression
        result.flexure_demand = demands.flexure
        result.notes.extend(demands.notes)
        if settings.seismic_system == "OCBF":
            result.notes.append(
                "OCBF F1.6a: the connection demands shown are the exception caps "
                "(Ry Fy Ag/alpha_s and expected compression/alpha_s); the "
                "overstrength seismic load may govern. The F2.6c.4 weld check is "
                "an SCBF requirement."
            )
        if gusset.weld_leg is not None:
            fexx = gusset.weld_fexx or 70.0 * stress_scale(SOURCE_UNITS, units)
            weld = gusset_weld_check(
                ry=settings.ry,
                fy=fy,
                thickness=gusset.t,
                fexx=fexx,
                leg=gusset.weld_leg,
                both_sides=gusset.weld_both_sides,
                method=settings.method,
            )
            result.checks.append(weld)
            result.weld_leg = gusset.weld_leg
            result.weld_required_leg = gusset_weld_required_leg(
                ry=settings.ry,
                fy=fy,
                thickness=gusset.t,
                fexx=fexx,
                both_sides=gusset.weld_both_sides,
                method=settings.method,
            )
            result.weld_ratio = weld.ratio
            result.weld_status = "NG" if weld.ratio > 1.0 else "OK"
        else:
            result.notes.append(
                "F2.6c.4: the gusset-to-flange weld is not checked; set the weld leg."
            )
        result.ratio = max(check.ratio for check in result.checks)
        result.status = "NG" if result.ratio > 1.0 else "OK"
        out.append(result)
    return out
