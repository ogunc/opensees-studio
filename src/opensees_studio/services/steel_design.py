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
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import numpy as np

from opensees_studio.core.aisc import SOURCE_UNITS, get_shape, load_shapes
from opensees_studio.core.analysis import ResponseSpectrumCase, StaticCase
from opensees_studio.core.design.aisc341 import (
    JointBeam,
    JointColumn,
    Role,
    ca,
    continuity_plate_thickness,
    continuity_tlim,
    joint_scwb,
    member_limits,
    panel_zone_demand,
    panel_zone_strength,
)
from opensees_studio.core.design.aisc360 import (
    I_SHAPE_FAMILIES,
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
from opensees_studio.core.design.calc import CalcStep, LimitStateCheck
from opensees_studio.core.design.settings import DesignLoadSet, DesignSettings
from opensees_studio.core.geometry.elements import FRAME_ELEMENT_CLASSES
from opensees_studio.core.sections import ElasticSection
from opensees_studio.core.units import length_scale, stress_scale
from opensees_studio.services.element_forces import ForceComponent, extract_diagram_data
from opensees_studio.services.results import ResponseSpectrumResults, StaticResults

#: Points along each member where the demands are read (ends included).
STATIONS = 25

_GRID = np.linspace(0.0, 1.0, STATIONS)
_COMPONENTS = (
    ForceComponent.N,
    ForceComponent.V2,
    ForceComponent.V3,
    ForceComponent.M2,
    ForceComponent.M3,
)
_FY_KSI = 50.0
_FU_KSI = 65.0

#: localForce index of (component, end) for the response spectrum peaks.
_PEAK_INDEX_3D = {"N": (0, 6), "V2": (1, 7), "V3": (2, 8), "M2": (4, 10), "M3": (5, 11)}
_PEAK_INDEX_2D = {"N": (0, 3), "V2": (1, 4), "M3": (2, 5)}


class UnsupportedLoadSetError(ValueError):
    """A combination the steel check cannot expand into linear sums."""


# ──────────────────────────── load sets ────────────────────────────
Alternative = dict[int, float]
"""Case id → factor; a response spectrum case's factor carries the ± of its peak."""


def default_load_sets(project: Any) -> list[DesignLoadSet]:
    """Every combination, or every static case when the project has none."""
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


def shape_in_units(name: str, units: Any) -> SteelShape:
    """The AISC shape ``name`` as the class of its family, in the project's ``units``.

    Raises:
        KeyError: not an AISC v16 shape.
        ValueError: a shape these provisions do not cover, or a table row
            missing a property the family needs.
    """
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
class DesignReport:
    members: list[MemberResult] = field(default_factory=list)
    joints: list[JointResult] = field(default_factory=list)
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


def _member_role(project: Any, element: Any) -> Role:
    """``column``, ``beam`` or ``brace`` from the member's direction.

    A member within 20% of vertical is a column; within 20% of horizontal is a
    beam (a plan diagonal in 3D is a brace); anything else is a brace.
    """
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    delta = coords[element.nodes[1]] - coords[element.nodes[0]]
    length = float(np.linalg.norm(delta))
    if length <= 0.0:
        return "beam"
    vertical = abs(float(delta[2])) / length
    if vertical >= 0.8:
        return "column"
    if vertical <= 0.2:
        horizontal = math.hypot(float(delta[0]), float(delta[1]))
        if project.ndm == 2 or min(abs(float(delta[0])), abs(float(delta[1]))) <= 0.2 * horizontal:
            return "beam"
    return "brace"


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
    fy = settings.fy if settings.fy is not None else default_fy(units)
    fu = settings.fu if settings.fu is not None else default_fu(units)

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
            shape = shape_in_units(name, units)
        except (KeyError, ValueError) as exc:
            reason = exc.args[0] if exc.args else str(exc)
            result.notes.append(f"No AISC shape to check with: {reason}")
            continue
        result.shape = shape.name
        if isinstance(section, ElasticSection) and abs(section.A - shape.A) > 0.02 * shape.A:
            result.notes.append(
                f"The analysis section's area differs from {shape.name}'s by "
                f"{abs(section.A - shape.A) / shape.A:.0%}."
            )
        e = float(getattr(section, "E", 0.0) or 0.0) or 29000.0 * stress_scale(SOURCE_UNITS, units)
        g = float(getattr(section, "G", 0.0) or 0.0) or e / 2.6
        steel = Steel(Fy=fy, E=e, G=g, Fu=fu)
        length = _length(project, element)
        role = _member_role(project, element)
        m_major, v_major, m_minor, v_minor, about_major = _axes(project, section, shape)
        if not about_major:
            result.notes.append("Bent about the shape's minor axis in this 2D model.")
        if not alternatives:
            result.notes.append("No load set with results.")
            continue
        worst: tuple[float, MemberCheck, str, float] | None = None
        max_ratios: dict[str, float] = {}
        for label, alt in alternatives:
            values: dict[str, np.ndarray] = {}
            for component in ("N", "V2", "V3", "M2", "M3"):
                total = np.zeros(STATIONS)
                for cid, factor in alt.items():
                    per_case = fields[cid].get(component, {}).get(element.id)
                    if per_case is not None:
                        total = total + factor * per_case
                values[component] = total
            major_moment = values[m_major] if m_major else np.zeros(STATIONS)
            quarter = [float(np.interp(s, _GRID, major_moment)) for s in (0.25, 0.5, 0.75)]
            peak = float(np.max(np.abs(major_moment)))
            cb = overrides.cb or cb_from_moments(peak, *quarter)
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
                    length_x=overrides.length_major or length,
                    length_y=overrides.length_minor or length,
                    length_ltb=overrides.length_ltb or length,
                    k_x=overrides.k_major,
                    k_y=overrides.k_minor,
                    net_area=overrides.net_area,
                    shear_lag=overrides.shear_lag,
                    p_delta=settings.p_delta,
                )
                if settings.seismic_system != "none":
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
                        system=settings.seismic_system,
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
                ratio = check.governing[1]
                for name, value in check.ratios.items():
                    max_ratios[name] = max(max_ratios.get(name, 0.0), value)
                if worst is None or ratio > worst[0]:
                    worst = (ratio, check, label, float(station_value))
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
            shape = shape_in_units(name, units)
        except (KeyError, ValueError):
            continue
        if not isinstance(shape, IShape):
            continue
        length = float(np.linalg.norm(coords[element.nodes[1]] - coords[element.nodes[0]]))
        out[element.id] = (shape, _member_role(project, element), length, shape.d)
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
                joint_beams.append(JointBeam(shape.Zx, fy, length, abs(shear)))
                # A1: the face moment is the end moment less the shear over dc/2.
                sum_mf += max(0.0, abs(moment) - abs(shear) * dc / 2.0)
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
