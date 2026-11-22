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

from opensees_studio.core.design.footing import (
    REQUIRES_VERIFICATION,
    Footing,
    FootingCheck,
    FootingDesign,
    FootingLoad,
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
    units = project.meta.units
    stress = _scales(units).stress
    out: list[FootingReport] = []
    for support in supports:
        if support.node_id not in wanted:
            continue
        report = FootingReport(node_id=support.node_id, column=support.column)
        out.append(report)
        service, strength, notes = footing_loads(project, results, settings, support.node_id)
        report.notes.extend(notes)
        if not service and not strength:
            report.notes.append("No load set with static results: run the cases first.")
            continue
        result = check_footing(footing_in_si(footings[support.node_id], units), service, strength)
        report.checks = result.checks
        report.notes.extend(n for n in result.notes if n not in report.notes)
        report.q_max = result.q_max / stress
        governing = result.governing
        if governing is not None:
            report.ratio = governing.ratio
            report.governing = governing.name
            report.load_set = governing.load
            report.status = "OK" if governing.ratio <= settings.ratio_limit else "NG"
        if result.requires_verification and report.status != "NG":
            report.status = STATUS_REQUIRES_VERIFICATION
    return out


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


__all__ = [
    "FootingReport",
    "FootingSupport",
    "check_footings",
    "default_footing",
    "design_from_si",
    "footing_in_si",
    "footing_load_sets",
    "footing_loads",
    "footing_supports",
    "is_service_name",
    "size_design",
]
