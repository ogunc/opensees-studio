"""AISC 360-16 Chapter C, the Direct Analysis Method, as analysis cases.

A combination of separate results is a sum, and a second-order analysis cannot be
summed: ``1.2D + 1.6L`` with P-Delta has to be solved as one analysis under the
factored loads. So each load combination becomes one
:class:`~opensees_studio.core.analysis.StaticCase` carrying its patterns with their
factors, and the case itself says what the method requires when it runs:

* **Second order** (C2.1): ``p_delta`` runs every frame as PDelta. P-delta (the
  member's own curvature) is left to ``B1`` in the member check (C2.1b).
* **Reduced stiffness** (C2.3): ``stiffness_factor = 0.8`` on the elastic frames
  and trusses. ``tau_b`` is taken as 1.0 with the additional notional load of
  C2.3(c), ``0.001 alpha Yi`` in every combination, so no iteration on the axial
  forces is needed.
* **Notional loads** (C2.2b): ``0.002 alpha Yi`` at every storey, ``Yi`` being that
  storey's factored gravity load *in this combination*. They act in
  gravity-only combinations, in each lateral direction and sign, while the
  second- to first-order drift ratio stays at or below 1.7 (C2.2b(d)); above
  that they act in every combination, along its lateral load.

A lateral combination also gets a first-order twin (no P-Delta, same reduced
stiffness and loads), from which :func:`drift_ratios` computes Δ2/Δ1 per storey.
The model itself is never changed: :func:`analysis_model` makes the copy a case
runs on.

LRFD only: in ASD, C2.1(e) requires the analysis at 1.6 times the ASD
combinations and the results divided by 1.6.

No Qt, no OpenSees.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from opensees_studio.core.analysis import (
    DirectAnalysisTag,
    ResponseSpectrumCase,
    StaticCase,
)
from opensees_studio.core.combinations import asce7_16_lrfd
from opensees_studio.core.design.stability import (
    ALPHA_LRFD,
    NOTIONAL_FRACTION,
    storey_node_levels,
)
from opensees_studio.core.geometry.elements import (
    FRAME_ELEMENT_CLASSES,
    BeamWithHingesElement,
    CorotTrussElement,
    TrussElement,
)
from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.loads import NodalLoad, PlainLoadPattern
from opensees_studio.core.materials import ElasticUniaxial
from opensees_studio.core.sections import ElasticSection
from opensees_studio.core.storeys import base_elevation

if TYPE_CHECKING:
    from opensees_studio.core.design.settings import DesignSettings
    from opensees_studio.core.project import Project

STIFFNESS_REDUCTION = 0.8
"""C2.3(a): factor on every stiffness that contributes to the structure's stability."""

TAU_B_NOTIONAL = 0.001
"""C2.3(c): additional notional fraction that lets ``tau_b = 1.0`` in every member."""

DRIFT_RATIO_LIMIT = 1.7
"""C2.2b(d): above this Δ2/Δ1 the notional loads act in every combination."""

DAM_STEPS = 10
"""Load steps of a second-order case (LoadControl 0.1)."""

LATERAL_ROLES = ("W", "E")


# ─────────────────────────── the model a case runs on ───────────────────────────
def analysis_model(
    project: Project, *, p_delta: bool, stiffness_factor: float
) -> tuple[Project, list[str]]:
    """A copy of ``project`` with P-Delta frames and scaled stiffness, and notes on what changed.

    ``p_delta`` turns every frame with a Linear transformation into PDelta
    (Corotational stays). ``stiffness_factor`` scales E and G of the elastic
    sections frames use, the elastic interior of beams with hinges, and the elastic
    materials of trusses (each truss material gets a scaled copy, so a spring
    sharing the material keeps its stiffness). Fibre sections and nonlinear
    materials are not scaled, and the notes say so.
    """
    model = project.model_copy(deep=True)
    notes: list[str] = []
    frames = [el for el in model.elements if isinstance(el, FRAME_ELEMENT_CLASSES)]
    if p_delta:
        switched = 0
        for el in frames:
            if el.geom_transf == "Linear":
                el.geom_transf = "PDelta"
                switched += 1
        kept = sum(1 for el in frames if el.geom_transf == "Corotational")
        note = f"Second order: {switched} frame member(s) run with the PDelta transformation"
        notes.append(note + (f", {kept} kept Corotational." if kept else "."))
    if stiffness_factor == 1.0:
        return model, notes

    f = float(stiffness_factor)
    sections = {s.id: s for s in model.sections}
    scaled_sections: set[int] = set()
    unscaled: list[int] = []
    for el in frames:
        if isinstance(el, BeamWithHingesElement):
            el.E = el.E * f
            if el.G is not None:
                el.G = el.G * f
            continue
        section = sections.get(getattr(el, "section_id", -1))
        if isinstance(section, ElasticSection):
            if section.id not in scaled_sections:
                section.E = section.E * f
                if section.G is not None:
                    section.G = section.G * f
                scaled_sections.add(section.id)
        else:
            unscaled.append(el.id)

    materials = {m.id: m for m in model.materials}
    copies: dict[int, int] = {}
    next_id = max((m.id for m in model.materials), default=0) + 1
    scaled_trusses = 0
    for bar in model.elements:
        if not isinstance(bar, TrussElement | CorotTrussElement):
            continue
        material = materials.get(bar.material_id)
        if not isinstance(material, ElasticUniaxial):
            unscaled.append(bar.id)
            continue
        if material.id not in copies:
            copy = material.model_copy(
                update={
                    "id": next_id,
                    "name": f"{material.name or material.id} x{f:g}",
                    "E": material.E * f,
                    "Eneg": None if material.Eneg is None else material.Eneg * f,
                }
            )
            model.materials.append(copy)
            copies[material.id] = next_id
            next_id += 1
        bar.material_id = copies[material.id]
        scaled_trusses += 1

    notes.append(
        f"Stiffness x{f:g} (AISC 360 C2.3): {len(scaled_sections)} elastic section(s), "
        f"{scaled_trusses} truss(es)."
    )
    if unscaled:
        shown = ", ".join(str(i) for i in unscaled[:10]) + (" …" if len(unscaled) > 10 else "")
        notes.append(
            f"Not reduced: member(s) {shown} use a fibre section or a nonlinear material, "
            "whose stiffness this reduction does not reach."
        )
    return model, notes


# ─────────────────────────── loads of a case ───────────────────────────
def _frame_axes(
    project: Project, coords: dict[int, np.ndarray], element: Any
) -> tuple[np.ndarray, tuple[int, int], float] | None:
    nodes = tuple(getattr(element, "nodes", ()))
    if len(nodes) != 2:
        return None
    axes = frame_local_axes(
        project.ndm,
        coords[nodes[0]].tolist(),
        coords[nodes[1]].tolist(),
        float(getattr(element, "local_axis_angle", 0.0) or 0.0),
    )
    if axes is None:
        return None
    length = float(np.linalg.norm(coords[nodes[1]] - coords[nodes[0]]))
    return np.vstack(axes), (int(nodes[0]), int(nodes[1])), length


def pattern_forces(project: Project, pattern: PlainLoadPattern) -> dict[int, np.ndarray]:
    """Node id -> global force (Fx, Fy, Fz) of ``pattern``, its member loads lumped on joints.

    Every load that pushes the structure counts: nodal loads, uniform, point and
    trapezoidal member loads (floor panels included), shell pressures and the
    pattern's self weight. A member load goes to its two joints by the lever rule.
    Imposed displacements, temperature and tendons are left out: they are not
    weight.
    """
    from opensees_studio.core.area_loads import pattern_distributed_loads, surface_nodal_loads
    from opensees_studio.core.mass_source import self_weight_per_node
    from opensees_studio.core.self_weight import gravity_direction

    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    elements = {e.id: e for e in project.elements}
    out: dict[int, np.ndarray] = {}

    def add(nid: int, force: np.ndarray) -> None:
        out[nid] = out.get(nid, np.zeros(3)) + force

    for nodal in pattern.nodal_loads:
        add(nodal.node_id, np.asarray(nodal.forces[:3], dtype=float))
    for uniform in pattern.element_loads:
        frame = _frame_axes(project, coords, elements.get(uniform.element_id))
        if frame is None:
            continue
        axes, (i, j), length = frame
        total = (np.array([uniform.wx, uniform.wy, uniform.wz]) @ axes) * length
        add(i, 0.5 * total)
        add(j, 0.5 * total)
    for point in pattern.point_loads:
        frame = _frame_axes(project, coords, elements.get(point.element_id))
        if frame is None:
            continue
        axes, (i, j), _length = frame
        force = np.array([point.px, point.py, point.pz]) @ axes
        add(i, (1.0 - point.x) * force)
        add(j, point.x * force)
    for load in pattern_distributed_loads(project, pattern):
        frame = _frame_axes(project, coords, elements.get(load.element_id))
        if frame is None:
            continue
        axes, (i, j), length = frame
        span = (load.x_end - load.x_start) * length
        local_i = np.zeros(3)
        local_j = np.zeros(3)
        for k, (start, end) in enumerate(
            (
                (load.wx_start, load.wx_end),
                (load.wy_start, load.wy_end),
                (load.wz_start, load.wz_end),
            )
        ):
            resultant = 0.5 * (start + end) * span
            if resultant == 0.0:
                continue
            # Centroid of the trapezoid, as a fraction of the member length.
            share = (start + 2.0 * end) / (3.0 * (start + end)) if start + end else 0.5
            x = load.x_start + share * (load.x_end - load.x_start)
            local_i[k] = (1.0 - x) * resultant
            local_j[k] = x * resultant
        add(i, local_i @ axes)
        add(j, local_j @ axes)
    if pattern.surface_loads:
        for nid, force in surface_nodal_loads(project, list(pattern.surface_loads)).items():
            add(nid, np.asarray(force, dtype=float))
    if pattern.self_weight:
        down = gravity_direction(project.ndm)
        for nid, weight in self_weight_per_node(project, pattern.self_weight).items():
            add(nid, weight * np.asarray(down, dtype=float))
    return out


def case_forces(project: Project, case: StaticCase) -> dict[int, np.ndarray]:
    """Node id -> global force of the factored patterns of ``case`` (Plain patterns only)."""
    patterns = {p.id: p for p in project.load_patterns}
    out: dict[int, np.ndarray] = {}
    for index, pid in enumerate(case.pattern_ids):
        pattern = patterns.get(pid)
        if not isinstance(pattern, PlainLoadPattern):
            continue
        factor = case.factor_of(index)
        for nid, force in pattern_forces(project, pattern).items():
            out[nid] = out.get(nid, np.zeros(3)) + factor * force
    return out


def case_gravity(project: Project, case: StaticCase) -> dict[int, float]:
    """Node id -> downward factored load of ``case`` (only the joints it pushes down)."""
    from opensees_studio.core.self_weight import gravity_direction

    down = np.asarray(gravity_direction(project.ndm), dtype=float)
    weights = {nid: float(force @ down) for nid, force in case_forces(project, case).items()}
    return {nid: w for nid, w in weights.items() if w > 0.0}


@dataclass(frozen=True)
class StoreyNotionalLoad:
    name: str
    elevation: float
    gravity: float
    """Yi: the storey's factored gravity load in the case."""
    force: float
    """Ni = ratio x Yi."""


def case_notional_loads(
    project: Project, case: StaticCase
) -> tuple[list[NodalLoad], list[StoreyNotionalLoad]]:
    """The notional nodal loads of ``case``, and each storey's Yi and Ni.

    ``Ni = notional_ratio x Yi`` at every level, shared between the level's joints in
    proportion to the factored gravity load each carries, along
    ``notional_direction``.
    """
    if case.notional_ratio <= 0.0:
        return [], []
    axis = 0 if case.notional_direction.endswith("X") else 1
    if project.ndm == 2 and axis == 1:
        raise ValueError(f"Case '{case.name}': a 2D model has notional loads along X only.")
    sign = -1.0 if case.notional_direction.startswith("-") else 1.0
    weights = case_gravity(project, case)
    loads: list[NodalLoad] = []
    storeys: list[StoreyNotionalLoad] = []
    for name, elevation, node_ids in storey_node_levels(project):
        shares = [weights.get(nid, 0.0) for nid in node_ids]
        total = float(sum(shares))
        if total <= 0.0:
            continue
        force = case.notional_ratio * total
        storeys.append(StoreyNotionalLoad(name, elevation, total, force))
        for nid, share in zip(node_ids, shares, strict=True):
            if share <= 0.0:
                continue
            forces = [0.0] * 6
            forces[axis] = sign * force * share / total
            loads.append(NodalLoad(node_id=nid, forces=tuple(forces)))  # type: ignore[arg-type]
    return loads, storeys


# ─────────────────────────── the cases of the method ───────────────────────────
@dataclass
class GeneratedCases:
    """What :func:`direct_analysis_cases` made, and what the engineer should know."""

    cases: list[StaticCase] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def strength_cases(self) -> list[StaticCase]:
        return [c for c in self.cases if c.direct_analysis and c.direct_analysis.order == "second"]


def is_direct_analysis_case(case: Any) -> bool:
    return isinstance(case, StaticCase) and case.direct_analysis is not None


def _lateral_direction(forces: Mapping[int, np.ndarray], ndm: int) -> str | None:
    """``+X``, ``-Y``, ... : the axis and sign of the largest net horizontal force."""
    total = np.zeros(3)
    for force in forces.values():
        total += force
    candidates = [(abs(total[0]), "X", total[0])]
    if ndm == 3:
        candidates.append((abs(total[1]), "Y", total[1]))
    size, axis, value = max(candidates)
    if size <= 1e-12 * max(1.0, float(np.abs(total).max())):
        return None
    return f"{'+' if value > 0 else '-'}{axis}"


def direct_analysis_cases(
    project: Project,
    settings: DesignSettings,
    roles: Mapping[str, Iterable[int]],
    *,
    first_id: int,
    notional_everywhere: bool = False,
) -> GeneratedCases:
    """The analysis cases of the direct analysis method for the ASCE 7-16 LRFD combinations.

    ``roles`` maps a load role (``D``, ``L``, ``W``, ``E``, ...) to the static cases
    carrying it; their patterns (with the case's own factors) make up each
    combination. ``notional_everywhere`` puts the 0.002 alpha Yi notional loads in
    the lateral combinations too, as C2.2b(d) requires when Δ2/Δ1 > 1.7.

    Raises:
        ValueError: ASD, or no dead load case.
    """
    if settings.method != "LRFD":
        raise ValueError(
            "The direct analysis cases are generated for LRFD. In ASD, AISC 360 C2.1(e) "
            "requires the second-order analysis at 1.6 times the ASD combinations with "
            "the results divided by 1.6; switch the design basis to LRFD."
        )
    alpha = ALPHA_LRFD
    cases_by_id = {c.id: c for c in project.analyses}
    role_of: dict[int, str] = {}
    for role, ids in roles.items():
        for cid in ids:
            role_of[int(cid)] = role
    if not any(role == "D" for role in role_of.values()):
        raise ValueError("Assign at least one static case to the dead load (D).")
    peaks = [cid for cid in role_of if isinstance(cases_by_id.get(cid), ResponseSpectrumCase)]
    combos = asce7_16_lrfd(
        roles, peak_cases=peaks, omega0=settings.omega0(), sds=settings.sds or 1.0
    )

    out = GeneratedCases()
    out.notes.append(
        "AISC 360-16 Chapter C, LRFD: P-Delta in every frame, stiffness x0.8 (C2.3), "
        "tau_b = 1.0 with the additional notional load 0.001 alpha Yi (C2.3(c)) in every "
        "combination, K = 1 in the member check."
    )
    skipped_spectrum = False
    used_nonlinear: set[str] = set()
    next_id = first_id

    def add(case: StaticCase) -> None:
        nonlocal next_id
        out.cases.append(case)
        next_id += 1

    for name, terms in combos:
        factors: dict[int, float] = {}
        lateral_part: dict[int, float] = {}
        skip = False
        for term in terms:
            case = cases_by_id.get(term.ref_id)
            if isinstance(case, ResponseSpectrumCase):
                skip = skipped_spectrum = True
                break
            if not isinstance(case, StaticCase):
                skip = True
                break
            if case.algorithm != "Linear" or case.preload_case_ids:
                used_nonlinear.add(case.name or str(case.id))
            for index, pid in enumerate(case.pattern_ids):
                value = term.factor * case.factor_of(index)
                factors[pid] = factors.get(pid, 0.0) + value
                if role_of.get(case.id) in LATERAL_ROLES:
                    lateral_part[pid] = lateral_part.get(pid, 0.0) + value
        if skip:
            continue
        pattern_ids = [pid for pid, f in factors.items() if f != 0.0]
        if not pattern_ids:
            continue
        pattern_factors = [round(factors[pid], 12) for pid in pattern_ids]
        overstrength = name.startswith("Ω0")
        lateral = bool(lateral_part)
        base = dict(
            pattern_ids=pattern_ids,
            pattern_factors=pattern_factors,
            n_steps=DAM_STEPS,
            load_factor_increment=1.0 / DAM_STEPS,
            algorithm="Newton",
            max_iter=50,
            p_delta=True,
            stiffness_factor=STIFFNESS_REDUCTION,
        )
        if not lateral:
            ratio = (NOTIONAL_FRACTION + TAU_B_NOTIONAL) * alpha
            directions = ["+X", "-X"] + (["+Y", "-Y"] if project.ndm == 3 else [])
            for direction in directions:
                add(
                    StaticCase(
                        id=next_id,
                        name=f"DAM {name} N{direction}",
                        notional_ratio=ratio,
                        notional_direction=direction,  # type: ignore[arg-type]
                        direct_analysis=DirectAnalysisTag(
                            combination=name, overstrength=overstrength
                        ),
                        **base,  # type: ignore[arg-type]
                    )
                )
            continue
        probe = StaticCase(
            id=1,
            pattern_ids=list(lateral_part),
            pattern_factors=list(lateral_part.values()),
        )
        found = _lateral_direction(case_forces(project, probe), project.ndm)
        direction = found or "+X"
        if found is None:
            out.notes.append(
                f"{name}: the lateral load has no net horizontal force; its notional "
                "loads act along +X."
            )
        ratio = (TAU_B_NOTIONAL + (NOTIONAL_FRACTION if notional_everywhere else 0.0)) * alpha
        tag = DirectAnalysisTag(combination=name, lateral=True, overstrength=overstrength)
        add(
            StaticCase(
                id=next_id,
                name=f"DAM {name}",
                notional_ratio=ratio,
                notional_direction=direction,  # type: ignore[arg-type]
                direct_analysis=tag,
                **base,  # type: ignore[arg-type]
            )
        )
        add(
            StaticCase(
                id=next_id,
                name=f"DAM 1st-order {name}",
                pattern_ids=pattern_ids,
                pattern_factors=pattern_factors,
                stiffness_factor=STIFFNESS_REDUCTION,
                notional_ratio=ratio,
                notional_direction=direction,  # type: ignore[arg-type]
                direct_analysis=tag.model_copy(update={"order": "first"}),
            )
        )

    if skipped_spectrum:
        out.notes.append(
            "Combinations with a response spectrum case are left out: a spectrum is a "
            "peak of linear modes and cannot enter a second-order analysis. Use an "
            "equivalent lateral force case for the direct analysis method."
        )
    if used_nonlinear:
        out.notes.append(
            f"Case(s) {', '.join(sorted(used_nonlinear))} enter only through their load "
            "patterns; their own algorithm and preload are not used."
        )
    if notional_everywhere:
        out.notes.append(
            "Δ2/Δ1 > 1.7: the notional loads 0.002 alpha Yi act in every combination (C2.2b(d))."
        )
    else:
        out.notes.append(
            "Notional loads 0.002 alpha Yi in the gravity-only combinations only, valid "
            "while Δ2/Δ1 <= 1.7 (C2.2b(d)); check it after running the cases."
        )
    return out


# ─────────────────────────── Δ2/Δ1 ───────────────────────────
@dataclass(frozen=True)
class DriftRatio:
    """Second- over first-order drift of one storey in one lateral combination."""

    combination: str
    storey: str
    elevation: float
    first: float
    second: float

    @property
    def ratio(self) -> float | None:
        if self.first <= 0.0:
            return None
        return self.second / self.first


def drift_ratios(
    project: Project,
    case: StaticCase,
    first: Mapping[int, np.ndarray],
    second: Mapping[int, np.ndarray],
) -> list[DriftRatio]:
    """Δ2/Δ1 of every storey, along the case's lateral direction.

    ``first`` and ``second`` map node id to the final displacement of the
    first-order twin and of the second-order case. A storey's drift is the
    difference between the mean displacement of its joints and of the level below
    (the base does not move).
    """
    axis = 0 if case.notional_direction.endswith("X") else 1
    name = case.direct_analysis.combination if case.direct_analysis else case.name

    def level_disp(disp: Mapping[int, np.ndarray], nodes: tuple[int, ...]) -> float:
        values = [float(np.asarray(disp[n])[axis]) for n in nodes if n in disp]
        return float(np.mean(values)) if values else math.nan

    rows: list[DriftRatio] = []
    below_first = below_second = 0.0
    for storey, elevation, nodes in storey_node_levels(project):
        if elevation <= base_elevation(project):
            continue
        u1, u2 = level_disp(first, nodes), level_disp(second, nodes)
        if math.isnan(u1) or math.isnan(u2):
            continue
        rows.append(
            DriftRatio(name, storey, elevation, abs(u1 - below_first), abs(u2 - below_second))
        )
        below_first, below_second = u1, u2
    return rows


def notional_everywhere_required(ratios: Iterable[DriftRatio]) -> bool:
    """True when a storey's Δ2/Δ1 exceeds 1.7 (C2.2b(d))."""
    return any((r.ratio or 0.0) > DRIFT_RATIO_LIMIT for r in ratios)
