"""Isolated footings over the analysis results: every support, every load alternative.

A **footing support** is a node restrained vertically (``Uz``). When a steel
column with an AISC shape stands on it (:func:`services.base_plates.column_bases`)
the footing starts under that column's base plate, and the moment is taken
halfway between the column face and the plate edge (ACI 318-19 13.2.7.1);
otherwise it starts under a 400 mm square column. Every number is editable in
Design → Footings.

Two families of loads, both lists of :class:`~...settings.DesignLoadSet`:

* **service** (the soil: bearing, contact, overturning, sliding, uplift) —
  ``DesignSettings.footing_service_sets``, else every combination whose name
  says ASD, service or SLS. With none of those the strength loads are used and a
  note says so (conservative).
* **strength** (the concrete) — ``DesignSettings.footing_strength_sets``, else
  the steel check's load sets without the service ones.

The reactions of each alternative are summed exactly as the base plate check
does, converted to N and mm, and checked by
:func:`~opensees_studio.core.design.footing.check_footing`. A 2D model's
reaction ``(Fx, Fz, My)`` lies in the X-Z plane.

No Qt. OpenSees is not needed: the results come in.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from opensees_studio.core.design.combined_footing import (
    CombinedColumn,
    CombinedFooting,
    CombinedFootingDesign,
    CombinedLoad,
    FootingColumn,
    check_combined_footing,
    size_combined_footing,
)
from opensees_studio.core.design.footing import (
    REQUIRES_VERIFICATION,
    Footing,
    FootingCheck,
    FootingDesign,
    FootingLoad,
    FootingResult,
    Pressure,
    check_footing,
    size_footing,
)
from opensees_studio.core.design.settings import DesignLoadSet, DesignSettings
from opensees_studio.core.units import UnitSystem, force_scale, length_scale, stress_scale
from opensees_studio.services.base_plates import ColumnBase, column_bases, default_design
from opensees_studio.services.results import StaticResults
from opensees_studio.services.steel_design import (
    UnsupportedLoadSetError,
    default_load_sets,
    expand,
    load_set_label,
)

SERVICE_NAME = re.compile(r"\b(asd|serv\w*|sls|ser)\b|^asd|^sls", re.IGNORECASE)
"""A combination whose name matches is a service load set by default."""

STATUS_REQUIRES_VERIFICATION = REQUIRES_VERIFICATION.lower()


@dataclass(frozen=True)
class FootingSupport:
    """A vertically restrained node, and the steel column on it when there is one."""

    node_id: int
    column: str = ""
    base: ColumnBase | None = None


@dataclass
class FootingReport:
    """The governing outcome of one footing over every load alternative."""

    node_id: int
    column: str = ""
    status: str = "not checked"
    """``OK``, ``NG``, ``requires verification`` or ``not checked``."""
    ratio: float = 0.0
    governing: str = ""
    load_set: str = ""
    checks: list[FootingCheck] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    q_max: float = 0.0
    """Largest service pressure, in the project's stress unit."""
    name: str = ""
    """A combined footing's name; empty for an isolated one."""
    node_ids: tuple[int, ...] = ()
    """Every support on the footing."""
    plan: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    """``(centre X, centre Y, L, B)`` in the project's length unit."""
    pressure: Pressure | None = None
    """Service pressure with the largest q,max, in N and mm from the footing centre."""
    pressure_load: str = ""
    footprints: list[tuple[float, float, float, float]] = field(default_factory=list)
    """``(X, Y, cx, cy)`` of each pedestal, column or plate on the footing (project units)."""

    @property
    def label(self) -> str:
        return self.name or f"Node {self.node_id}"


@dataclass(frozen=True)
class _Scales:
    """Project units → N and mm."""

    length: float
    force: float
    stress: float

    @property
    def weight(self) -> float:
        return self.force / self.length**3


def _scales(units: UnitSystem) -> _Scales:
    target = UnitSystem.SI_MM_N
    return _Scales(
        length=length_scale(units, target),
        force=force_scale(units, target),
        stress=stress_scale(units, target),
    )


# ───────────────────────────── supports ─────────────────────────────
def footing_supports(project: Any, settings: DesignSettings | None = None) -> list[FootingSupport]:
    """Every node restrained in Uz, with the steel column base found on it."""
    settings = settings or DesignSettings()
    bases = {b.node_id: b for b in column_bases(project, settings)}
    return [
        FootingSupport(
            node_id=node.id,
            column=bases[node.id].shape if node.id in bases else "",
            base=bases.get(node.id),
        )
        for node in project.nodes
        if bool(node.restraint[2])
    ]


def _plate_plan(base: ColumnBase, n_length: float, b_width: float) -> tuple[float, float, bool]:
    """``(along X, along Y, depth along X)`` of a plate N × B under ``base``'s column."""
    if base.major_axis is None:
        along_x = True
    else:
        ax, ay, _az = base.major_axis
        along_x = abs(ay) >= abs(ax)
    return (n_length, b_width, True) if along_x else (b_width, n_length, False)


def default_footing(
    support: FootingSupport, units: UnitSystem, settings: DesignSettings | None = None
) -> FootingDesign:
    """A starting footing: 1.5 m square, 500 mm thick, f'c 21 MPa, fy 420 MPa, 16 mm at 200 mm.

    Under a steel column the footprint is its base plate (the saved one, else
    :func:`services.base_plates.default_design`); otherwise a 400 mm column.
    """
    s = _scales(units)
    mm, mpa = 1.0 / s.length, 1.0 / s.stress
    column_x = column_y = 400.0 * mm
    steel_x: float | None = None
    steel_y: float | None = None
    if support.base is not None:
        base = support.base
        saved = {d.node_id: d for d in (settings or DesignSettings()).base_plates}
        plate = saved.get(base.node_id) or default_design(base, units)
        column_x, column_y, depth_x = _plate_plan(base, plate.n_length, plate.b_width)
        steel_x, steel_y = (base.d, base.bf) if depth_x else (base.bf, base.d)
    side = max(1500.0 * mm, max(column_x, column_y) + 600.0 * mm)
    return FootingDesign(
        node_id=support.node_id,
        length_x=side,
        width_y=side,
        thickness=500.0 * mm,
        column_x=column_x,
        column_y=column_y,
        steel_x=steel_x,
        steel_y=steel_y,
        fc=21.0 * mpa,
        fy=420.0 * mpa,
        cover=75.0 * mm,
        bar_x_diameter=16.0 * mm,
        bar_x_spacing=200.0 * mm,
        bar_y_diameter=16.0 * mm,
        bar_y_spacing=200.0 * mm,
        concrete_weight=23.6e-6 / s.weight,
        soil_weight=18.0e-6 / s.weight,
        bearing_allowable=0.15 * mpa,
    )


def footing_in_si(design: FootingDesign, units: UnitSystem) -> Footing:
    """The core :class:`Footing` (N, mm, MPa) of a saved design."""
    s = _scales(units)
    ln, st = s.length, s.stress
    flex_x = flex_y = None
    if design.pedestal_height <= 0.0 and design.steel_x and design.steel_y:
        flex_x = (design.column_x + design.steel_x) / 2.0 * ln
        flex_y = (design.column_y + design.steel_y) / 2.0 * ln
    return Footing(
        length_x=design.length_x * ln,
        width_y=design.width_y * ln,
        thickness=design.thickness * ln,
        cx=design.column_x * ln,
        cy=design.column_y * ln,
        offset_x=design.offset_x * ln,
        offset_y=design.offset_y * ln,
        flex_cx=flex_x,
        flex_cy=flex_y,
        pedestal_height=design.pedestal_height * ln,
        soil_cover=design.soil_cover * ln,
        fc=design.fc * st,
        fy=design.fy * st,
        lam=design.lam,
        cover=design.cover * ln,
        bar_x_diameter=design.bar_x_diameter * ln,
        bar_x_spacing=design.bar_x_spacing * ln,
        bar_y_diameter=design.bar_y_diameter * ln,
        bar_y_spacing=design.bar_y_spacing * ln,
        concrete_weight=design.concrete_weight * s.weight,
        soil_weight=design.soil_weight * s.weight,
        bearing_allowable=design.bearing_allowable * st,
        friction=design.friction,
        fs_overturning=design.fs_overturning,
        fs_sliding=design.fs_sliding,
    )


def design_from_si(design: FootingDesign, footing: Footing, units: UnitSystem) -> FootingDesign:
    """``design`` with the plan, thickness and bars of a sized core footing."""
    ln = _scales(units).length
    return design.model_copy(
        update={
            "length_x": footing.length_x / ln,
            "width_y": footing.width_y / ln,
            "thickness": footing.thickness / ln,
            "bar_x_diameter": footing.bar_x_diameter / ln,
            "bar_x_spacing": footing.bar_x_spacing / ln,
            "bar_y_diameter": footing.bar_y_diameter / ln,
            "bar_y_spacing": footing.bar_y_spacing / ln,
        }
    )


# ───────────────────────────── loads ─────────────────────────────
def is_service_name(name: str) -> bool:
    return bool(SERVICE_NAME.search(name or ""))


def footing_load_sets(
    project: Any, settings: DesignSettings
) -> tuple[list[DesignLoadSet], list[DesignLoadSet], list[str]]:
    """``(service, strength, notes)`` the footings are checked with."""
    notes: list[str] = []
    service = list(settings.footing_service_sets) or [
        DesignLoadSet(source="combination", ref_id=c.id)
        for c in project.combinations
        if is_service_name(c.name)
    ]
    strength = list(settings.footing_strength_sets)
    if not strength:
        keys = {(s.source, s.ref_id) for s in service}
        strength = [
            s
            for s in (settings.load_sets or default_load_sets(project))
            if (s.source, s.ref_id) not in keys
        ]
    if not service:
        service = list(strength)
        if service:
            notes.append(
                "No service (ASD) combination: the soil is checked with the strength loads, "
                "which is conservative. Name service combinations ASD or SLS, or pick them."
            )
    return service, strength, notes


def _alternatives(
    project: Any, results: Mapping[int, Any], sets: list[DesignLoadSet]
) -> tuple[list[tuple[str, dict[int, float]]], list[str]]:
    out: list[tuple[str, dict[int, float]]] = []
    skipped: list[str] = []
    for load_set in sets:
        label = load_set_label(project, load_set)
        try:
            options = expand(project, load_set.source, load_set.ref_id)
        except UnsupportedLoadSetError:
            skipped.append(label)
            continue
        if any(not isinstance(results.get(cid), StaticResults) for alt in options for cid in alt):
            skipped.append(label)
            continue
        out += [(label, alt) for alt in options]
    return out, skipped


def _load(
    project: Any,
    results: Mapping[int, Any],
    node_id: int,
    label: str,
    alt: dict[int, float],
    s: _Scales,
) -> FootingLoad | None:
    row: np.ndarray | None = None
    for cid, factor in alt.items():
        values = results[cid].node_reaction.get(node_id)
        if values is None:
            continue
        vector = np.atleast_2d(np.asarray(values, dtype=float))[-1]
        row = factor * vector if row is None else row + factor * vector
    if row is None:
        return None
    if project.ndm == 2 or row.size == 3:
        force = (row[0], 0.0, row[1])
        moment = (0.0, row[2] if row.size > 2 else 0.0, 0.0)
    else:
        force = (row[0], row[1], row[2])
        moment = (row[3], row[4], row[5]) if row.size >= 6 else (0.0, 0.0, 0.0)
    moment_scale = s.force * s.length
    return FootingLoad(
        force=tuple(float(v) * s.force for v in force),  # type: ignore[arg-type]
        moment=tuple(float(v) * moment_scale for v in moment),  # type: ignore[arg-type]
        label=label,
    )


def footing_loads(
    project: Any,
    results: Mapping[int, Any],
    settings: DesignSettings,
    node_id: int,
) -> tuple[list[FootingLoad], list[FootingLoad], list[str]]:
    """``(service, strength, notes)`` loads of one support, in N and mm."""
    s = _scales(project.meta.units)
    service_sets, strength_sets, notes = footing_load_sets(project, settings)
    loads: list[list[FootingLoad]] = []
    for sets in (service_sets, strength_sets):
        alternatives, skipped = _alternatives(project, results, sets)
        if skipped:
            notes.append(
                f"Not checked (no static results or no signed demands): {', '.join(skipped)}."
            )
        found = [_load(project, results, node_id, label, alt, s) for label, alt in alternatives]
        loads.append([x for x in found if x is not None])
    return loads[0], loads[1], notes


# ───────────────────────────── the check ─────────────────────────────
def _designs(
    project: Any, settings: DesignSettings, supports: list[FootingSupport]
) -> dict[int, FootingDesign]:
    saved = {d.node_id: d for d in settings.footings}
    units = project.meta.units
    return {
        s.node_id: saved.get(s.node_id) or default_footing(s, units, settings) for s in supports
    }


def check_footings(
    project: Any,
    results: Mapping[int, Any],
    settings: DesignSettings | None = None,
    *,
    designs: Mapping[int, FootingDesign] | None = None,
    nodes: set[int] | None = None,
) -> list[FootingReport]:
    """Every footing (or those under ``nodes``) over its service and strength loads.

    ``designs`` replaces the saved footings (the dialog's edits before OK).
    Only supports with a saved or given design are checked unless ``nodes`` names
    them: a project never asked for footings reports none.
    """
    settings = settings or DesignSettings()
    supports = footing_supports(project, settings)
    footings = {**_designs(project, settings, supports), **(designs or {})}
    wanted = (
        nodes
        if nodes is not None
        else {d.node_id for d in settings.footings} | set((designs or {}).keys())
    )
    wanted = wanted - combined_nodes(settings)
    units = project.meta.units
    coords = {n.id: n.coords for n in project.nodes}
    out: list[FootingReport] = []
    for support in supports:
        if support.node_id not in wanted:
            continue
        design = footings[support.node_id]
        x, y = coords[support.node_id][0], coords[support.node_id][1]
        report = FootingReport(
            node_id=support.node_id,
            column=support.column,
            node_ids=(support.node_id,),
            plan=(x - design.offset_x, y - design.offset_y, design.length_x, design.width_y),
            footprints=[(x, y, design.column_x, design.column_y)],
        )
        out.append(report)
        service, strength, notes = footing_loads(project, results, settings, support.node_id)
        report.notes.extend(notes)
        if not service and not strength:
            report.notes.append("No load set with static results: run the cases first.")
            continue
        result = check_footing(footing_in_si(design, units), service, strength)
        _finish(report, result, settings, units)
    return out


def _finish(
    report: FootingReport, result: FootingResult, settings: DesignSettings, units: UnitSystem
) -> None:
    report.checks = result.checks
    report.notes.extend(n for n in result.notes if n not in report.notes)
    report.q_max = result.q_max / _scales(units).stress
    report.pressure, report.pressure_load = result.pressure, result.pressure_load
    governing = result.governing
    if governing is not None:
        report.ratio = governing.ratio
        report.governing = governing.name
        report.load_set = governing.load
        report.status = "OK" if governing.ratio <= settings.ratio_limit else "NG"
    if result.requires_verification and report.status != "NG":
        report.status = STATUS_REQUIRES_VERIFICATION


def size_design(
    project: Any,
    results: Mapping[int, Any],
    settings: DesignSettings,
    design: FootingDesign,
) -> FootingDesign | None:
    """The smallest footing that passes, keeping the footprint and the materials."""
    units = project.meta.units
    service, strength, _notes = footing_loads(project, results, settings, design.node_id)
    if not service and not strength:
        return None
    footing = footing_in_si(design, units)
    sized = size_footing(footing, service, strength, limit=settings.ratio_limit)
    if sized is None:
        return None
    return design_from_si(design, sized, units)


# ───────────────────────────── combined footings ─────────────────────────────
def combined_nodes(settings: DesignSettings) -> set[int]:
    """Supports that stand on a combined footing (they get no isolated one)."""
    return {nid for c in settings.combined_footings for nid in c.node_ids}


def _coords(project: Any) -> dict[int, tuple[float, float]]:
    return {n.id: (float(n.coords[0]), float(n.coords[1])) for n in project.nodes}


def default_combined(
    project: Any,
    node_ids: list[int],
    settings: DesignSettings | None = None,
    *,
    name: str = "",
) -> CombinedFootingDesign:
    """A starting combined footing under ``node_ids`` (two or more supports).

    Centred on the supports, its long side along the line through the two that
    are farthest apart (rounded to global X or Y), 600 mm past the outer
    footprints and 1.5 m wide; each column starts as its isolated default
    (its base plate under a steel column).
    """
    settings = settings or DesignSettings()
    units = project.meta.units
    s = _scales(units)
    mm, mpa = 1.0 / s.length, 1.0 / s.stress
    supports = {sp.node_id: sp for sp in footing_supports(project, settings)}
    coords = _coords(project)
    columns = []
    for nid in node_ids:
        single = default_footing(supports.get(nid) or FootingSupport(nid), units, settings)
        columns.append(
            CombinedColumn(
                node_id=nid,
                column_x=single.column_x,
                column_y=single.column_y,
                steel_x=single.steel_x,
                steel_y=single.steel_y,
            )
        )
    xs = [coords[n][0] for n in node_ids]
    ys = [coords[n][1] for n in node_ids]
    along_x = (max(xs) - min(xs)) >= (max(ys) - min(ys))
    margin = 600.0 * mm
    if along_x:
        lo = min(x - c.column_x / 2.0 for x, c in zip(xs, columns, strict=True)) - margin
        hi = max(x + c.column_x / 2.0 for x, c in zip(xs, columns, strict=True)) + margin
        length, width = hi - lo, 1500.0 * mm
        centre = ((lo + hi) / 2.0, sum(ys) / len(ys))
    else:
        lo = min(y - c.column_y / 2.0 for y, c in zip(ys, columns, strict=True)) - margin
        hi = max(y + c.column_y / 2.0 for y, c in zip(ys, columns, strict=True)) + margin
        width, length = hi - lo, 1500.0 * mm
        centre = (sum(xs) / len(xs), (lo + hi) / 2.0)
    return CombinedFootingDesign(
        name=name or f"CF-{'-'.join(map(str, node_ids))}",
        columns=columns,
        center_x=centre[0],
        center_y=centre[1],
        length_x=length,
        width_y=width,
        thickness=600.0 * mm,
        fc=21.0 * mpa,
        fy=420.0 * mpa,
        cover=75.0 * mm,
        bar_x_diameter=16.0 * mm,
        bar_x_spacing=200.0 * mm,
        bar_y_diameter=16.0 * mm,
        bar_y_spacing=200.0 * mm,
        top_bar_diameter=16.0 * mm,
        top_bar_spacing=200.0 * mm,
        concrete_weight=23.6e-6 / s.weight,
        soil_weight=18.0e-6 / s.weight,
        bearing_allowable=0.15 * mpa,
    )


def combined_in_si(project: Any, design: CombinedFootingDesign) -> CombinedFooting:
    """The core :class:`CombinedFooting` (N, mm, MPa) of a saved design."""
    s = _scales(project.meta.units)
    ln, st = s.length, s.stress
    coords = _coords(project)
    columns = []
    for c in design.columns:
        x, y = coords[c.node_id]
        flex_x = flex_y = None
        if c.pedestal_height <= 0.0 and c.steel_x and c.steel_y:
            flex_x = (c.column_x + c.steel_x) / 2.0 * ln
            flex_y = (c.column_y + c.steel_y) / 2.0 * ln
        columns.append(
            FootingColumn(
                x=(x - design.center_x) * ln,
                y=(y - design.center_y) * ln,
                cx=c.column_x * ln,
                cy=c.column_y * ln,
                flex_cx=flex_x,
                flex_cy=flex_y,
                pedestal_height=c.pedestal_height * ln,
                label=f"node {c.node_id}",
            )
        )
    return CombinedFooting(
        length_x=design.length_x * ln,
        width_y=design.width_y * ln,
        thickness=design.thickness * ln,
        columns=tuple(columns),
        soil_cover=design.soil_cover * ln,
        fc=design.fc * st,
        fy=design.fy * st,
        lam=design.lam,
        cover=design.cover * ln,
        bar_x_diameter=design.bar_x_diameter * ln,
        bar_x_spacing=design.bar_x_spacing * ln,
        bar_y_diameter=design.bar_y_diameter * ln,
        bar_y_spacing=design.bar_y_spacing * ln,
        top_bar_diameter=design.top_bar_diameter * ln,
        top_bar_spacing=design.top_bar_spacing * ln,
        concrete_weight=design.concrete_weight * s.weight,
        soil_weight=design.soil_weight * s.weight,
        bearing_allowable=design.bearing_allowable * st,
        friction=design.friction,
        fs_overturning=design.fs_overturning,
        fs_sliding=design.fs_sliding,
    )


def combined_loads(
    project: Any,
    results: Mapping[int, Any],
    settings: DesignSettings,
    node_ids: list[int],
) -> tuple[list[CombinedLoad], list[CombinedLoad], list[str]]:
    """``(service, strength, notes)``: every alternative with a reaction at every node."""
    s = _scales(project.meta.units)
    service_sets, strength_sets, notes = footing_load_sets(project, settings)
    out: list[list[CombinedLoad]] = []
    for sets in (service_sets, strength_sets):
        alternatives, skipped = _alternatives(project, results, sets)
        if skipped:
            notes.append(
                f"Not checked (no static results or no signed demands): {', '.join(skipped)}."
            )
        loads = []
        for label, alt in alternatives:
            reactions = [_load(project, results, n, label, alt, s) for n in node_ids]
            if all(r is not None for r in reactions):
                loads.append(CombinedLoad(tuple(reactions), label))  # type: ignore[arg-type]
        out.append(loads)
    return out[0], out[1], notes


def check_combined_footings(
    project: Any,
    results: Mapping[int, Any],
    settings: DesignSettings | None = None,
    *,
    designs: list[CombinedFootingDesign] | None = None,
) -> list[FootingReport]:
    """Every combined footing (``designs``, else the saved ones) over its load sets."""
    settings = settings or DesignSettings()
    units = project.meta.units
    out: list[FootingReport] = []
    supports = {sp.node_id: sp for sp in footing_supports(project, settings)}
    for design in settings.combined_footings if designs is None else designs:
        nodes = design.node_ids
        report = FootingReport(
            node_id=nodes[0],
            name=design.name,
            column=", ".join(
                supports[n].column for n in nodes if n in supports and supports[n].column
            ),
            node_ids=tuple(nodes),
            plan=(design.center_x, design.center_y, design.length_x, design.width_y),
        )
        coords = _coords(project)
        report.footprints = [
            (*coords[c.node_id], c.column_x, c.column_y)
            for c in design.columns
            if c.node_id in coords
        ]
        out.append(report)
        missing = [n for n in nodes if n not in supports]
        if missing:
            report.notes.append(
                f"Node(s) {', '.join(map(str, missing))} are not supports restrained in Uz."
            )
            continue
        service, strength, notes = combined_loads(project, results, settings, nodes)
        report.notes.extend(notes)
        if not service and not strength:
            report.notes.append("No load set with static results: run the cases first.")
            continue
        result = check_combined_footing(combined_in_si(project, design), service, strength)
        _finish(report, result, settings, units)
    return out


def size_combined_design(
    project: Any,
    results: Mapping[int, Any],
    settings: DesignSettings,
    design: CombinedFootingDesign,
) -> CombinedFootingDesign | None:
    """The narrowest, thinnest combined footing that passes (the length is kept)."""
    service, strength, _notes = combined_loads(project, results, settings, design.node_ids)
    if not service and not strength:
        return None
    sized = size_combined_footing(
        combined_in_si(project, design), service, strength, limit=settings.ratio_limit
    )
    if sized is None:
        return None
    ln = _scales(project.meta.units).length
    return design.model_copy(
        update={
            "length_x": sized.length_x / ln,
            "width_y": sized.width_y / ln,
            "thickness": sized.thickness / ln,
            "bar_x_diameter": sized.bar_x_diameter / ln,
            "bar_x_spacing": sized.bar_x_spacing / ln,
            "bar_y_diameter": sized.bar_y_diameter / ln,
            "bar_y_spacing": sized.bar_y_spacing / ln,
            "top_bar_diameter": sized.top_bar_diameter / ln,
            "top_bar_spacing": sized.top_bar_spacing / ln,
        }
    )


def all_footing_reports(
    project: Any, results: Mapping[int, Any], settings: DesignSettings | None = None
) -> list[FootingReport]:
    """The saved isolated and combined footings, checked."""
    settings = settings or DesignSettings()
    return check_footings(project, results, settings) + check_combined_footings(
        project, results, settings
    )


# ───────────────────────────── drawing ─────────────────────────────
def pressure_grid(
    report: FootingReport, units: UnitSystem, n: int = 60
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """``(X, Y, q)`` cell centres (project lengths) and service pressure (project stress).

    The pressure is the governing service alternative's (largest q,max); None
    when the footing has none.
    """
    if report.pressure is None:
        return None
    s = _scales(units)
    cx, cy, length, width = report.plan
    u = (np.arange(n) + 0.5) / n - 0.5
    xs, ys = cx + u * length, cy + u * width
    q = (
        report.pressure.at(((xs - cx) * s.length)[:, None], ((ys - cy) * s.length)[None, :])
        / s.stress
    )
    return xs, ys, q


__all__ = [
    "FootingReport",
    "FootingSupport",
    "all_footing_reports",
    "check_combined_footings",
    "check_footings",
    "combined_in_si",
    "combined_loads",
    "combined_nodes",
    "default_combined",
    "default_footing",
    "design_from_si",
    "footing_in_si",
    "footing_load_sets",
    "footing_loads",
    "footing_supports",
    "is_service_name",
    "pressure_grid",
    "size_combined_design",
    "size_design",
]
