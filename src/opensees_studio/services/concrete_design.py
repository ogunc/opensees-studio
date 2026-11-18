"""Design → Concrete Frame Check (ACI 318-19): every RC member over the load sets.

A member is reinforced concrete when its section is a fibre section of concrete
and bars (the Concrete Section Wizard's, or any other), or an elastic section the
wizard made next to one (``<name> (elastic, …)``): its capacity comes from those
fibres (:mod:`core.design.aci318`). The demands are the steel check's: the
diagrams of every case a load set needs at the stations, combined linearly.

M3 (about local z) uses the reinforcement where it is: the diagram's sign
convention puts sagging (compression on +y) negative. M2 takes the smaller
capacity of the two senses.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from opensees_studio.core.design.aci318 import (
    RcSection,
    ShearReinforcement,
    beam_checks,
    check_station,
    interaction_curve,
)
from opensees_studio.core.design.settings import ConcreteDesign, DesignSettings
from opensees_studio.core.geometry.elements import FRAME_ELEMENT_CLASSES
from opensees_studio.core.sections import ElasticSection, FiberSection
from opensees_studio.core.units import UnitSystem, stress_scale
from opensees_studio.services.results import ResponseSpectrumResults
from opensees_studio.services.section_properties import expand_fibres_with_materials
from opensees_studio.services.steel_design import (
    _GRID,
    STATIONS,
    Alternative,
    Field,
    UnsupportedLoadSetError,
    default_load_sets,
    expand,
    load_set_label,
    spectrum_field,
    static_field,
)

#: Concrete materials and the field holding their compressive strength.
_CONCRETE_FIELDS = ("fpc", "fc", "fpcc", "fcc")
#: Steel materials: (yield field, modulus field).
_STEEL_FIELDS = (("Fy", "E0"), ("fy", "Es"), ("Fy", "E"))


@dataclass
class RcMemberResult:
    """The governing outcome of one RC member (the ratio overlay reads the first three)."""

    element_id: int
    status: str = "not designed"
    ratio: float = 0.0
    section: str = ""
    check: str = ""
    clause: str = ""
    detail: str = ""
    load_set: str = ""
    station: float = 0.0
    ratios: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class ConcreteReport:
    members: list[RcMemberResult] = field(default_factory=list)
    load_sets: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def failing(self) -> list[RcMemberResult]:
        return [m for m in self.members if m.status == "NG"]

    def summary(self) -> str:
        designed = [m for m in self.members if m.status != "not designed"]
        if not designed:
            return "No reinforced concrete member was checked."
        worst = max(designed, key=lambda m: m.ratio)
        return (
            f"{len(designed)} RC member(s) checked, {len(self.failing)} over the limit; "
            f"largest ratio {worst.ratio:.3f} ({worst.check}, member {worst.element_id})."
        )


def _concrete_fc(material: Any) -> float | None:
    for name in _CONCRETE_FIELDS:
        value = getattr(material, name, None)
        if isinstance(value, int | float) and value != 0.0:
            return abs(float(value))
    return None


def _steel(material: Any) -> tuple[float, float] | None:
    for fy_name, e_name in _STEEL_FIELDS:
        fy, es = getattr(material, fy_name, None), getattr(material, e_name, None)
        if isinstance(fy, int | float) and isinstance(es, int | float) and fy > 0 and es > 0:
            return float(fy), float(es)
    return None


def design_fibre_section(project: Any, section: Any) -> FiberSection | None:
    """The fibre section that carries a member's reinforcement, if there is one."""
    if isinstance(section, FiberSection):
        return section
    if isinstance(section, ElasticSection) and " (elastic" in (section.name or ""):
        stem = section.name.split(" (elastic")[0]
        return next(
            (s for s in project.sections if isinstance(s, FiberSection) and s.name == stem),
            None,
        )
    return None


def rc_section(project: Any, fibre: FiberSection, settings: ConcreteDesign) -> RcSection | None:
    """The fibres of ``fibre`` split into concrete and bars, or None if it is not RC."""
    materials = {m.id: m for m in project.materials}
    rows = expand_fibres_with_materials(fibre)
    concrete, bars = [], []
    fc_values, steel_values = [], []
    for y, z, area, mid in rows:
        material = materials.get(int(mid))
        if material is None:
            continue
        steel = _steel(material)
        if steel is not None:
            bars.append((y, z, area))
            steel_values.append(steel)
            continue
        fc = _concrete_fc(material)
        if fc is not None:
            concrete.append((y, z, area))
            fc_values.append(fc)
    if not concrete or not bars:
        return None
    mpa = stress_scale(UnitSystem.SI_MM_N, project.meta.units)
    return RcSection(
        concrete=np.asarray(concrete, dtype=float),
        bars=np.asarray(bars, dtype=float),
        fc=float(min(fc_values)),
        fy=float(min(f for f, _ in steel_values)),
        es=float(steel_values[0][1]),
        mpa=mpa,
        transverse=settings.transverse,
    )


def _shear(project: Any, settings: ConcreteDesign) -> ShearReinforcement:
    mpa = stress_scale(UnitSystem.SI_MM_N, project.meta.units)
    from opensees_studio.core.units import length_scale

    mm = length_scale(UnitSystem.SI_MM_N, project.meta.units)
    return ShearReinforcement(
        av=settings.stirrup_area if settings.stirrup_area is not None else 157.0 * mm * mm,
        spacing=settings.stirrup_spacing if settings.stirrup_spacing is not None else 150.0 * mm,
        fyt=settings.fyt if settings.fyt is not None else 420.0 * mpa,
    )


def concrete_frame_check(
    project: Any, results: Mapping[int, Any], settings: DesignSettings | None = None
) -> ConcreteReport:
    """Check every RC frame member against ACI 318-19 over the chosen load sets."""
    settings = settings or DesignSettings()
    concrete = settings.concrete or ConcreteDesign()
    report = ConcreteReport()
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
        if any(cid not in results for cid in needed):
            report.notes.append(f"{label} not checked: run its cases first.")
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
    shear = _shear(project, concrete)
    curves_cache: dict[int, tuple[RcSection, dict[str, Any]]] = {}
    for element in project.elements:
        if not isinstance(element, FRAME_ELEMENT_CLASSES):
            continue
        result = RcMemberResult(element_id=element.id)
        section = sections.get(getattr(element, "section_id", -1))
        fibre = design_fibre_section(project, section)
        if fibre is None:
            continue
        if fibre.id not in curves_cache:
            rc = rc_section(project, fibre, concrete)
            if rc is None:
                continue
            curves_cache[fibre.id] = (
                rc,
                {"y": interaction_curve(rc, "y"), "z": interaction_curve(rc, "z")},
            )
        rc, curves = curves_cache[fibre.id]
        report.members.append(result)
        result.section = fibre.name or f"#{fibre.id}"
        if not alternatives:
            result.notes.append("No load set with results.")
            continue
        worst: tuple[float, Any, str, float] | None = None
        for label, alt in alternatives:
            values: dict[str, np.ndarray] = {}
            for component in ("N", "V2", "V3", "T", "M2", "M3"):
                total = np.zeros(STATIONS)
                for cid, factor in alt.items():
                    per_case = fields[cid].get(component, {}).get(element.id)
                    if per_case is not None:
                        total = total + factor * per_case
                values[component] = total
            for k, station in enumerate(_GRID):
                m2 = float(values["M2"][k])
                outcome = check_station(
                    rc,
                    curves,
                    pu=float(values["N"][k]),
                    m3=-float(values["M3"][k]),
                    m2=0.0,
                    v2=float(values["V2"][k]),
                    v3=float(values["V3"][k]),
                    t=float(values["T"][k]),
                    shear=shear,
                    lam=concrete.lam,
                )
                if m2 != 0.0:
                    both = [
                        check_station(
                            rc,
                            curves,
                            pu=float(values["N"][k]),
                            m3=-float(values["M3"][k]),
                            m2=sign * abs(m2),
                            v2=0.0,
                            v3=0.0,
                            t=0.0,
                            shear=None,
                            lam=concrete.lam,
                        )
                        for sign in (1.0, -1.0)
                    ]
                    worse = max(both, key=lambda o: o.governing.ratio if o.governing else 0.0)
                    outcome.checks = [
                        c for c in outcome.checks if not c.name.startswith(("Flexure", "Biaxial"))
                    ] + [c for c in worse.checks if c.name.startswith(("Flexure", "Biaxial"))]
                for check in outcome.checks:
                    result.ratios[check.name] = max(result.ratios.get(check.name, 0.0), check.ratio)
                governing = outcome.governing
                if governing is not None and (worst is None or governing.ratio > worst[0]):
                    worst = (governing.ratio, governing, label, float(station))
                for note in outcome.notes:
                    if note not in result.notes:
                        result.notes.append(note)
        for check in beam_checks(rc, "y", curves["y"]):
            result.ratios[check.name] = max(result.ratios.get(check.name, 0.0), check.ratio)
            if worst is None or check.ratio > worst[0]:
                worst = (check.ratio, check, "detailing", 0.0)
        if worst is None:
            continue
        result.ratio, governing, result.load_set, result.station = worst
        result.check, result.clause, result.detail = (
            governing.name,
            governing.clause,
            governing.detail,
        )
        result.status = "NG" if result.ratio > settings.ratio_limit else "OK"
    report.notes.append(
        f"Shear reinforcement: Av = {shear.av:g}, s = {shear.spacing:g}, fyt = {shear.fyt:g} "
        "(project units) for every member; slenderness (6.6.4) is not checked."
    )
    return report
