"""Connections by joint over the analysis results: topology, suggestion, and the shear tabs checked.

:func:`core.design.joints.joint_connections` classifies every member end. Here
each simple beam end gets its shear tab (:mod:`core.design.shear_tab`) checked
under the largest end shear over every alternative of the design load sets (the
direct analysis cases when they exist, else the combinations). The other
connection types point to the dialog that designs them, or say that they are
not checked here.

A beam end starts from a conventional shear tab sized to the beam: 3/4 in A325-N
bolts at 3 in, Lev 1 1/4 in, Leh 1 1/2 in, a = 3 in, a 3/8 in A36 plate with
1/4 in E70 welds both sides, as many bolts as fit in the beam's clear depth
(2 to 12).

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
from opensees_studio.core.design.joints import SHEAR_TAB, Connection, joint_connections
from opensees_studio.core.design.settings import DesignSettings
from opensees_studio.core.design.shear_tab import BOLT_GRADES, ShearTabDesign, check_shear_tab
from opensees_studio.core.design.steel_grades import grade_stresses
from opensees_studio.core.units import UnitSystem, length_scale, stress_scale
from opensees_studio.services.results import StaticResults
from opensees_studio.services.steel_design import (
    UnsupportedLoadSetError,
    default_load_sets,
    expand,
    load_set_label,
    member_steel,
    shape_family,
    shape_in_units,
    static_field,
)


@dataclass
class ConnectionResult:
    """One connection, its suggestion and, for a shear tab, its governing check."""

    connection: Connection
    beam_shape: str = ""
    status: str = "not checked"
    """``OK`` / ``NG`` for a checked shear tab; otherwise where it is designed."""
    ratio: float = 0.0
    governing: str = ""
    load_set: str = ""
    vu: float = 0.0
    """Largest end shear over every alternative."""
    checks: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _inch(units: UnitSystem) -> float:
    return length_scale(UnitSystem.US_IN_KIP, units)


def default_tab(connection: Connection, beam: IShape, units: UnitSystem) -> ShearTabDesign:
    """A conventional shear tab that fits the beam's clear depth."""
    inch = _inch(units)
    ksi = stress_scale(UnitSystem.US_IN_KIP, units)
    clear = beam.d - 2.0 * beam.tf - 2.0 * inch
    bolts = int(max(2, min(12, math.floor((clear - 2.5 * inch) / (3.0 * inch)) + 1)))
    return ShearTabDesign(
        element_id=connection.element_id,
        end=connection.end,
        bolts=bolts,
        bolt_diameter=0.75 * inch,
        spacing=3.0 * inch,
        edge_vertical=1.25 * inch,
        edge_horizontal=1.5 * inch,
        weld_to_bolts=3.0 * inch,
        tp=0.375 * inch,
        weld_leg=0.25 * inch,
        fexx=70.0 * ksi,
    )


def _alternatives(
    project: Any, results: Mapping[int, Any], settings: DesignSettings
) -> tuple[list[tuple[str, dict[int, float]]], list[str]]:
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
    return alternatives, skipped


def connection_report(
    project: Any,
    results: Mapping[int, Any],
    settings: DesignSettings | None = None,
    *,
    tabs: Mapping[tuple[int, str], ShearTabDesign] | None = None,
) -> list[ConnectionResult]:
    """Every connection of the frame, the shear tabs checked over the design load sets.

    ``tabs`` replaces the saved shear tabs (the dialog's edits before OK); a
    simple beam end without one gets :func:`default_tab`.
    """
    settings = settings or DesignSettings()
    units = project.meta.units
    saved = {(t.element_id, t.end): t for t in settings.shear_tabs}
    chosen = {**saved, **(tabs or {})}
    alternatives, skipped = _alternatives(project, results, settings)
    fields: dict[int, Any] = {}
    for _label, alt in alternatives:
        for cid in alt:
            if cid not in fields:
                fields[cid] = static_field(project, results[cid])
    elements = {e.id: e for e in project.elements}
    sections = {s.id: s for s in project.sections}
    inch = _inch(units)

    out: list[ConnectionResult] = []
    for connection in joint_connections(project, settings):
        result = ConnectionResult(connection=connection)
        out.append(result)
        if connection.suggested != SHEAR_TAB:
            result.status = "see dialog" if "Design →" in connection.suggested else "not checked"
            continue
        element = elements[connection.element_id]
        overrides = settings.member(element.id)
        section = sections.get(getattr(element, "section_id", -1))
        name = overrides.shape or (getattr(section, "name", "") or "")
        try:
            beam = shape_in_units(name, units, settings.built_up_by_name())
        except (KeyError, ValueError):
            result.notes.append("No AISC shape for the beam: the shear tab is not checked.")
            continue
        if not isinstance(beam, IShape):
            result.notes.append(f"{beam.name} is not an I-shape: the shear tab is not checked.")
            continue
        result.beam_shape = beam.name
        if not alternatives:
            result.notes.append("No load set with static results: run the cases first.")
            continue
        tab = chosen.get(connection.key) or default_tab(connection, beam, units)
        # End shear: the major-axis shear at the element's station at this end.
        component = (
            "V2"
            if project.ndm == 2
            or (
                float(getattr(section, "Iz", 0.0) or 0.0)
                >= float(getattr(section, "Iy", 0.0) or 0.0)
            )
            else "V3"
        )
        station = 0 if connection.end == "i" else -1
        worst_v, worst_label = 0.0, ""
        for label, alt in alternatives:
            v = sum(
                factor
                * float(np.asarray(fields[cid].get(component, {}).get(element.id, [0.0]))[station])
                for cid, factor in alt.items()
            )
            if abs(v) > worst_v:
                worst_v, worst_label = abs(v), label
        result.vu, result.load_set = worst_v, worst_label
        _fy, web_fu, _grade = member_steel(settings, shape_family(beam), overrides, units)
        plate_fy, plate_fu = grade_stresses(tab.plate_grade, "W", units)
        fnv = BOLT_GRADES[tab.bolt_grade][1] * stress_scale(SOURCE_UNITS, units)
        check = check_shear_tab(
            tab,
            vu=worst_v,
            fnv=fnv,
            plate_fy=plate_fy,
            plate_fu=plate_fu,
            web_thickness=beam.tw,
            web_fu=web_fu,
            hole_extra=inch / 16.0,
            inch=inch,
            method=settings.method,
        )
        result.checks = {c.name: c.ratio for c in check.checks}
        result.notes += check.notes
        governing = check.governing
        if governing is not None:
            result.ratio, result.governing = governing.ratio, governing.name
            result.status = "OK" if governing.ratio <= settings.ratio_limit else "NG"
        if tab.length > beam.d - 2.0 * beam.tf:
            result.notes.append("The plate is longer than the beam's clear web depth.")
    if skipped:
        for result in out:
            if result.status in ("OK", "NG"):
                result.notes.append(
                    f"Not in the envelope (no static results or signed demands): {', '.join(skipped)}."
                )
    return out
