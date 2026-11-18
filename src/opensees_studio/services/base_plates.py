"""Column base plates over the analysis results: every base, every load alternative.

A **column base** is a support joint with one column framing up into it. Its
**support type** comes from the restraint: rotations free is a *pinned* base,
checked concentric (axial force and shear); both bending rotations fixed is a
*fixed* base, checked with axial force and moment (DG1 3.3); one of the two is
*partial*, checked as fixed with a note.

The demands are the reactions of the joint under every alternative of the design
load sets, the same ones the steel check reads (the direct analysis cases when
they exist, else the combinations): maximum compression, maximum M / P, uplift
and maximum shear all come out of checking each one. The moment of a fixed base
is the reaction moment about the column's major axis; the plate's length N runs
along the column depth d. A moment about the minor axis is reported, not
combined (Design Guide 1 has no biaxial method).

The column's shape (AISC table) gives d and bf: an I-shape, a rectangular HSS
(H, B) or a round HSS / pipe (D), each with its own DG1 cantilevers.

No Qt. OpenSees is not needed: the results come in.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from opensees_studio.core.aisc import SOURCE_UNITS
from opensees_studio.core.design.aisc360 import IShape
from opensees_studio.core.design.aisc360_shapes import RectHSS, RoundHSS
from opensees_studio.core.design.base_plate import (
    ROD_GRADES,
    BasePlate,
    BasePlateDesign,
    ColumnKind,
    check_base_plate,
)
from opensees_studio.core.design.members import direction_role
from opensees_studio.core.design.settings import DesignSettings
from opensees_studio.core.design.steel_grades import grade_stresses
from opensees_studio.core.geometry.elements import FRAME_ELEMENT_CLASSES
from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.units import (
    UnitSystem,
    force_scale,
    length_scale,
    stress_scale,
)
from opensees_studio.services.results import StaticResults
from opensees_studio.services.steel_design import (
    UnsupportedLoadSetError,
    _axes,
    default_load_sets,
    expand,
    load_set_label,
    shape_in_units,
)

STANDARD_THICKNESSES_IN = (
    0.5, 0.625, 0.75, 0.875, 1.0, 1.125, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0
)  # fmt: skip
"""Plate thicknesses the sizing tries, in inches."""


@dataclass(frozen=True)
class ColumnBase:
    """A support joint with a column on it."""

    node_id: int
    element_id: int
    shape: str
    kind: ColumnKind
    d: float
    bf: float
    support: str
    """``pinned``, ``fixed`` or ``partial``."""
    major_axis: tuple[float, float, float] | None
    """Global direction of the moment vector that bends the column about its major
    axis (3D); None in 2D, where the one moment is in the plane."""
    in_plane_major: bool = True
    """2D: the column bends in the plane about its major axis."""


@dataclass
class BaseResult:
    """The governing outcome of one base plate over every load alternative."""

    node_id: int
    shape: str = ""
    support: str = ""
    status: str = "not checked"
    """``OK``, ``NG`` or ``not checked``."""
    ratio: float = 0.0
    governing: str = ""
    load_set: str = ""
    demands: tuple[float, float, float] = (0.0, 0.0, 0.0)
    """``(Pu, Mu, Vu)`` of the governing alternative (compression positive)."""
    checks: dict[str, float] = field(default_factory=dict)
    """Largest ratio of each check over every alternative."""
    minor_moment: float = 0.0
    """Largest moment about the column's minor axis (reported, not checked)."""
    notes: list[str] = field(default_factory=list)


def _support_type(project: Any, node: Any) -> str:
    slots = (4,) if project.ndm == 2 else (3, 4)
    fixed = [bool(node.restraint[s]) for s in slots]
    if all(fixed):
        return "fixed"
    return "partial" if any(fixed) else "pinned"


def column_bases(project: Any, settings: DesignSettings | None = None) -> list[ColumnBase]:
    """Every supported joint with exactly one column framing up into it, and an AISC shape."""
    settings = settings or DesignSettings()
    units = project.meta.units
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    sections = {s.id: s for s in project.sections}
    at_node: dict[int, list[Any]] = {}
    for element in project.elements:
        if isinstance(element, FRAME_ELEMENT_CLASSES):
            for nid in element.nodes:
                at_node.setdefault(int(nid), []).append(element)
    out: list[ColumnBase] = []
    for node in project.nodes:
        if not any(node.restraint[:3]):
            continue
        columns = []
        for element in at_node.get(node.id, ()):
            other = int(element.nodes[1] if element.nodes[0] == node.id else element.nodes[0])
            role = settings.member(element.id).role or direction_role(
                project, coords[node.id], coords[other]
            )
            if role == "column" and coords[other][2] > coords[node.id][2]:
                columns.append(element)
        if len(columns) != 1:
            continue
        element = columns[0]
        section = sections.get(getattr(element, "section_id", -1))
        name = settings.member(element.id).shape or (getattr(section, "name", "") or "")
        try:
            shape = shape_in_units(name, units, settings.built_up_by_name())
        except (KeyError, ValueError):
            continue
        if isinstance(shape, IShape):
            kind, d, bf = "W", shape.d, shape.bf
        elif isinstance(shape, RectHSS):
            kind, d, bf = "HSS", shape.H, shape.B
        elif isinstance(shape, RoundHSS):
            kind, d, bf = "round", shape.D, shape.D
        else:
            continue
        m_major, _vx, _m_minor, _vy, about_major = _axes(project, section, shape)
        major_axis: tuple[float, float, float] | None = None
        if project.ndm == 3:
            axes = frame_local_axes(
                3,
                coords[element.nodes[0]].tolist(),
                coords[element.nodes[1]].tolist(),
                float(getattr(element, "local_axis_angle", 0.0) or 0.0),
            )
            if axes is None:
                continue
            vector = axes[2] if m_major == "M3" else axes[1]
            major_axis = (float(vector[0]), float(vector[1]), float(vector[2]))
        out.append(
            ColumnBase(
                node_id=node.id,
                element_id=element.id,
                shape=shape.name,
                kind=kind,  # type: ignore[arg-type]
                d=float(d),
                bf=float(bf),
                support=_support_type(project, node),
                major_axis=major_axis,
                in_plane_major=about_major,
            )
        )
    return out


def _inches(units: UnitSystem) -> float:
    return length_scale(UnitSystem.US_IN_KIP, units)


def default_design(base: ColumnBase, units: UnitSystem) -> BasePlateDesign:
    """A starting plate: 3 in all round the column, 1 in thick, A36, f'c 4 ksi, four 3/4 in rods."""
    inch = _inches(units)
    ksi = stress_scale(UnitSystem.US_IN_KIP, units)
    n_length = base.d + 6.0 * inch
    b_width = base.bf + 6.0 * inch
    return BasePlateDesign(
        node_id=base.node_id,
        n_length=n_length,
        b_width=b_width,
        tp=1.0 * inch,
        fc=4.0 * ksi,
        rod_diameter=0.75 * inch,
        rod_offset=n_length / 2.0 - 1.5 * inch,
        rod_spacing=b_width - 3.0 * inch,
        edge_distance=6.0 * inch,
        embedment=12.0 * inch,
    )


def plate_for(base: ColumnBase, design: BasePlateDesign, units: UnitSystem) -> BasePlate:
    """The DG1 plate of ``design`` on ``base``'s column, in the project's units."""
    fy, _fu = grade_stresses(design.plate_grade, "W", units)
    futa = ROD_GRADES[design.rod_grade][1] * stress_scale(SOURCE_UNITS, units)
    return BasePlate(
        d=base.d,
        bf=base.bf,
        n_length=design.n_length,
        b_width=design.b_width,
        tp=design.tp,
        fy=fy,
        fc=design.fc,
        a2=design.a2_ratio * design.n_length * design.b_width,
        rods_tension=design.rods_tension,
        rods_total=design.rods_total,
        rod_diameter=design.rod_diameter,
        rod_futa=futa,
        rod_offset=design.rod_offset,
        rod_spacing=design.rod_spacing,
        edge_distance=design.edge_distance,
        embedment=design.embedment,
        mpa=stress_scale(UnitSystem.SI_MM_N, units),
        mm=length_scale(UnitSystem.SI_MM_N, units),
        newton=force_scale(UnitSystem.SI_MM_N, units),
        kind=base.kind,
    )


def _reaction(results: StaticResults, node_id: int) -> np.ndarray | None:
    values = results.node_reaction.get(node_id)
    return None if values is None else np.atleast_2d(values)[-1]


def _demands(project: Any, base: ColumnBase, row: np.ndarray) -> tuple[float, float, float, float]:
    """``(Pu, M major, M minor, Vu)`` of a reaction row (OpenSees DOF order, global signs)."""
    if project.ndm == 2:
        in_plane = float(row[2])
        major, minor = (in_plane, 0.0) if base.in_plane_major else (0.0, in_plane)
        return float(row[1]), major, minor, abs(float(row[0]))
    moment = np.asarray(row[3:6], dtype=float)
    axis = np.asarray(base.major_axis, dtype=float)
    major = float(moment @ axis)
    vertical = np.array([0.0, 0.0, 1.0])
    minor_vec = moment - major * axis - float(moment @ vertical) * vertical
    return float(row[2]), major, float(np.linalg.norm(minor_vec)), math.hypot(row[0], row[1])


def _designs(project: Any, settings: DesignSettings, bases: list[ColumnBase]) -> dict[int, Any]:
    saved = {d.node_id: d for d in settings.base_plates}
    units = project.meta.units
    return {b.node_id: saved.get(b.node_id) or default_design(b, units) for b in bases}


def check_bases(
    project: Any,
    results: Mapping[int, Any],
    settings: DesignSettings | None = None,
    *,
    designs: Mapping[int, BasePlateDesign] | None = None,
) -> list[BaseResult]:
    """Every column base checked over every alternative of the design load sets.

    ``designs`` replaces the saved plates (the dialog's edits before OK); a base
    without one gets :func:`default_design`.
    """
    settings = settings or DesignSettings()
    units = project.meta.units
    bases = column_bases(project, settings)
    plates = {**_designs(project, settings, bases), **(designs or {})}
    alternatives: list[tuple[str, dict[int, float]]] = []
    skipped: list[str] = []
    for load_set in settings.load_sets or default_load_sets(project):
        label = load_set_label(project, load_set)
        try:
            options = expand(project, load_set.source, load_set.ref_id)
        except UnsupportedLoadSetError:
            skipped.append(label)
            continue
        if any(not isinstance(results.get(cid), StaticResults) for alt in options for cid in alt):
            skipped.append(label)
            continue
        alternatives += [(label, alt) for alt in options]

    out: list[BaseResult] = []
    for base in bases:
        result = BaseResult(node_id=base.node_id, shape=base.shape, support=base.support)
        out.append(result)
        if skipped:
            result.notes.append(
                f"Not checked (no static results or no signed demands): {', '.join(skipped)}."
            )
        if base.support == "partial":
            result.notes.append("One bending rotation is free: checked as a fixed base.")
        if not alternatives:
            result.notes.append("No load set with static results: run the cases first.")
            continue
        plate = plate_for(base, plates[base.node_id], units)
        worst: tuple[float, str, str, tuple[float, float, float]] | None = None
        for label, alt in alternatives:
            row = np.zeros(6)
            for cid, factor in alt.items():
                reaction = _reaction(results[cid], base.node_id)
                if reaction is not None:
                    row[: len(reaction)] += factor * reaction
            pu, m_major, m_minor, vu = _demands(project, base, row)
            mu = 0.0 if base.support == "pinned" else abs(m_major)
            result.minor_moment = max(result.minor_moment, abs(m_minor))
            check = check_base_plate(plate, pu=pu, mu=mu, vu=vu)
            for item in check.checks:
                result.checks[item.name] = max(result.checks.get(item.name, 0.0), item.ratio)
            governing = check.governing
            if governing is not None and (worst is None or governing.ratio > worst[0]):
                worst = (governing.ratio, governing.name, label, (pu, mu, vu))
            for note in check.notes:
                if note not in result.notes:
                    result.notes.append(note)
        if worst is not None:
            result.ratio, result.governing, result.load_set, result.demands = worst
            result.status = "OK" if result.ratio <= settings.ratio_limit else "NG"
        if base.support != "pinned" and result.minor_moment > 0.0:
            result.notes.append(
                f"Moment about the column's minor axis up to {result.minor_moment:.4g} is not "
                "combined with the major one (DG1 has no biaxial method): check it apart."
            )
    return out


def size_thickness(
    project: Any,
    results: Mapping[int, Any],
    settings: DesignSettings,
    design: BasePlateDesign,
) -> float | None:
    """The thinnest standard plate whose thickness checks pass, None when none does."""
    inch = _inches(project.meta.units)
    for t in STANDARD_THICKNESSES_IN:
        trial = design.model_copy(update={"tp": t * inch})
        (found,) = [
            r
            for r in check_bases(project, results, settings, designs={design.node_id: trial})
            if r.node_id == design.node_id
        ]
        thickness = [v for k, v in found.checks.items() if k.startswith("Plate thickness")]
        if found.checks and all(v <= settings.ratio_limit for v in thickness):
            return t * inch
    return None
