"""Project — the root aggregate.

A ``Project`` owns every entity in the model. It provides:

* Auto-allocated, kind-scoped integer IDs (Node IDs are independent of
  Element IDs, etc., matching OpenSees tag semantics).
* Convenience adders that allocate the next ID and append in one call.
* O(1) lookup by id.
* Cross-reference validation (``validate_references``): every Element's
  node_id and material_id/section_id must point to a real entity.

The model itself is mutable (lists), but each *entity* is replaced
wholesale on edits — the Project boundary is where mutation happens
and the only place where ``QUndoCommand`` will hook in (Phase 4).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

from opensees_studio.core.analysis import AnalysisCase
from opensees_studio.core.constraints import (
    MPConstraint,
    RigidLinkConstraint,
)
from opensees_studio.core.friction import FrictionModel
from opensees_studio.core.geometry import (
    BEARING_CLASSES,
    SLIDING_BEARING_CLASSES,
    CoordinateGridSystem,
    Element,
    GridSystem,
    Node,
    TwoNodeLinkElement,
    default_global_system,
)
from opensees_studio.core.ground_motion import GroundMotionRecord
from opensees_studio.core.loads import LoadPattern, ResponseSpectrum, TimeSeries
from opensees_studio.core.materials import Material
from opensees_studio.core.sections import Section
from opensees_studio.core.target_spectrum import TargetSpectrum
from opensees_studio.core.units import UnitSystem

TWO_NODE_LINK_PARALLEL_TOL = 1e-9
"""Relative tolerance of the twoNodeLink orient checks (|a x b| <= tol |a| |b|)."""


def _cross_norm(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.sqrt(
        (a[1] * b[2] - a[2] * b[1]) ** 2
        + (a[2] * b[0] - a[0] * b[2]) ** 2
        + (a[0] * b[1] - a[1] * b[0]) ** 2
    )


class ProjectMeta(BaseModel):
    """Project-level metadata."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    name: str = "Untitled"
    description: str = ""
    author: str = ""
    units: UnitSystem = UnitSystem.SI_M_N


class Project(BaseModel):
    """The root aggregate. Serializable to/from JSON via ``model_dump_json``."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # 1 = pre ground-motion catalog (records embedded in PathTimeSeries),
    # 2 = ground_motions catalog with record-backed time series.
    # ``services.persistence`` migrates v1 payloads on load and stamps the
    # current version on save.
    schema_version: int = Field(default=2, frozen=True)
    meta: ProjectMeta = Field(default_factory=ProjectMeta)

    ndm: int = Field(default=3, description="Spatial dimensions (2 or 3).")
    ndf: int = Field(default=6, description="DOFs per node (1, 2, 3, or 6).")

    coord_systems: list[CoordinateGridSystem] = Field(
        default_factory=lambda: [default_global_system()],
    )
    nodes: list[Node] = Field(default_factory=list)
    materials: list[Material] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_grid_system(cls, data: Any) -> Any:
        """Back-compat: old schema had a single ``grid_system`` field.

        If we see it in the incoming data and no ``coord_systems`` list
        is provided, wrap the grid into the Global system.
        """
        if isinstance(data, dict) and "grid_system" in data and "coord_systems" not in data:
            legacy = data.pop("grid_system")
            data["coord_systems"] = [
                {
                    "name": "Global",
                    "coord": {},
                    "grid": legacy,
                }
            ]
        return data

    @model_validator(mode="after")
    def _ensure_global_system(self) -> Project:
        """Guarantee that a 'Global' entry exists as the first coord system."""
        has_global = any(cs.name == "Global" for cs in self.coord_systems)
        if not has_global:
            self.coord_systems.insert(0, default_global_system())
        return self

    # ────────────── backward-compat proxy ──────────────
    @property
    def grid_system(self) -> GridSystem:
        """Compat alias: the Global system's grid."""
        for cs in self.coord_systems:
            if cs.name == "Global":
                return cs.grid
        return self.coord_systems[0].grid

    @grid_system.setter
    def grid_system(self, new_grid: GridSystem) -> None:
        """Compat alias: rewrite the Global system's grid in place."""
        for i, cs in enumerate(self.coord_systems):
            if cs.name == "Global":
                self.coord_systems[i] = cs.model_copy(update={"grid": new_grid})
                return
        # No Global system yet — create one with this grid.
        from opensees_studio.core.geometry import CoordinateGridSystem

        self.coord_systems.insert(
            0,
            CoordinateGridSystem(name="Global", grid=new_grid),
        )

    sections: list[Section] = Field(default_factory=list)
    friction_models: list[FrictionModel] = Field(
        default_factory=list,
        description="Friction models for sliding bearings (additive, schema 2).",
    )
    elements: list[Element] = Field(default_factory=list)
    mp_constraints: list[MPConstraint] = Field(default_factory=list)
    time_series: list[TimeSeries] = Field(default_factory=list)
    load_patterns: list[LoadPattern] = Field(default_factory=list)
    spectra: list[ResponseSpectrum] = Field(default_factory=list)
    ground_motions: list[GroundMotionRecord] = Field(default_factory=list)
    target_spectra: list[TargetSpectrum] = Field(
        default_factory=list,
        description="Design/target spectra in g for record scaling (additive, schema 2).",
    )
    analyses: list[AnalysisCase] = Field(default_factory=list)

    # ─────────────────── invariants ───────────────────
    @model_validator(mode="after")
    def _check_ndm_ndf(self) -> Project:
        valid = {(2, 2), (2, 3), (3, 3), (3, 6)}
        if (self.ndm, self.ndf) not in valid:
            raise ValueError(
                f"Invalid (ndm, ndf) pair: ({self.ndm}, {self.ndf}). "
                f"Must be one of {sorted(valid)}."
            )
        return self

    @model_validator(mode="after")
    def _check_unique_ids(self) -> Project:
        for label, items in (
            ("node", self.nodes),
            ("material", self.materials),
            ("section", self.sections),
            ("friction model", self.friction_models),
            ("element", self.elements),
            ("time series", self.time_series),
            ("load pattern", self.load_patterns),
            ("ground motion", self.ground_motions),
            ("target spectrum", self.target_spectra),
            ("analysis", self.analyses),
        ):
            ids = [it.id for it in items]
            if len(ids) != len(set(ids)):
                dup = {i for i in ids if ids.count(i) > 1}
                raise ValueError(f"Duplicate {label} ids: {sorted(dup)}.")
        return self

    # ─────────────────── ID allocation ───────────────────
    @staticmethod
    def _next_id(items: Iterable[Any]) -> int:
        used = {it.id for it in items}
        return (max(used) + 1) if used else 1

    def next_node_id(self) -> int:
        return self._next_id(self.nodes)

    def next_material_id(self) -> int:
        return self._next_id(self.materials)

    def next_section_id(self) -> int:
        return self._next_id(self.sections)

    def next_friction_model_id(self) -> int:
        return self._next_id(self.friction_models)

    def next_element_id(self) -> int:
        return self._next_id(self.elements)

    def next_time_series_id(self) -> int:
        return self._next_id(self.time_series)

    def next_pattern_id(self) -> int:
        return self._next_id(self.load_patterns)

    def next_ground_motion_id(self) -> int:
        return self._next_id(self.ground_motions)

    def next_target_spectrum_id(self) -> int:
        return self._next_id(self.target_spectra)

    def next_analysis_id(self) -> int:
        return self._next_id(self.analyses)

    # ─────────────────── lookups ───────────────────
    def node(self, node_id: PositiveInt) -> Node:
        return self._get(self.nodes, node_id, "node")

    def material(self, material_id: PositiveInt) -> Material:  # type: ignore[valid-type]
        return self._get(self.materials, material_id, "material")

    def section(self, section_id: PositiveInt) -> Section:  # type: ignore[valid-type]
        return self._get(self.sections, section_id, "section")

    def friction_model(self, friction_model_id: PositiveInt) -> FrictionModel:  # type: ignore[valid-type]
        return self._get(self.friction_models, friction_model_id, "friction model")

    def element(self, element_id: PositiveInt) -> Element:  # type: ignore[valid-type]
        return self._get(self.elements, element_id, "element")

    def ground_motion(self, record_id: PositiveInt) -> GroundMotionRecord:
        return self._get(self.ground_motions, record_id, "ground motion")

    def target_spectrum(self, spectrum_id: PositiveInt) -> TargetSpectrum:
        return self._get(self.target_spectra, spectrum_id, "target spectrum")

    @staticmethod
    def _get(items: list[Any], target_id: int, label: str) -> Any:
        for item in items:
            if item.id == target_id:
                return item
        raise KeyError(f"{label.capitalize()} with id={target_id} not found.")

    # ─────────────────── reference validation ───────────────────
    def case_reference_errors(self, case: Any) -> list[str]:
        """Return actionable reference errors without preventing a damaged file loading."""
        errors: list[str] = []
        patterns = {p.id: p for p in self.load_patterns}
        series = {s.id for s in self.time_series}
        nodes = {n.id for n in self.nodes}
        cases = {c.id: c for c in self.analyses}
        cases[case.id] = case

        def visit(current: Any, chain: tuple[int, ...]) -> None:
            prefix = f"Case {current.id}"
            for pid in getattr(current, "pattern_ids", []):
                pattern = patterns.get(pid)
                if pattern is None:
                    errors.append(f"{prefix}: missing pattern {pid}.")
                    continue
                for attr in (
                    "time_series_id",
                    "accel_series_id",
                    "vel_series_id",
                    "disp_series_id",
                ):
                    sid = getattr(pattern, attr, None)
                    if sid is not None and sid not in series:
                        errors.append(f"{prefix}: pattern {pid} has missing time series {sid}.")
            node = getattr(current, "control_node", None)
            if node is not None and node not in nodes:
                errors.append(f"{prefix}: missing control node {node}.")
            for cid in getattr(current, "preload_case_ids", []):
                preload = cases.get(cid)
                if cid in (*chain, current.id):
                    errors.append(f"{prefix}: preload case {cid} creates a cycle.")
                elif preload is None:
                    errors.append(f"{prefix}: missing preload case {cid}.")
                elif preload.type != "Static":
                    errors.append(f"{prefix}: preload case {cid} must be Static.")
                else:
                    visit(preload, (*chain, current.id))

        visit(case, ())
        return list(dict.fromkeys(errors))

    def validate_case_references(self, case: Any) -> None:
        errors = self.case_reference_errors(case)
        if errors:
            raise ValueError("\n".join(errors))

    def validate_references(self) -> None:
        """Check every element/load reference points to an existing entity.

        Raises:
            ValueError: with a single combined message listing all problems.
        """
        node_ids = {n.id for n in self.nodes}
        material_ids = {m.id for m in self.materials}
        section_ids = {s.id for s in self.sections}
        ts_ids = {ts.id for ts in self.time_series}
        gm_ids = {gm.id for gm in self.ground_motions}
        friction_ids = {fm.id for fm in self.friction_models}
        problems: list[str] = []

        for ts in self.time_series:
            rec_id = getattr(ts, "record_id", None)
            if rec_id is not None and rec_id not in gm_ids:
                problems.append(
                    f"Time series {ts.id} refers to missing ground-motion record {rec_id}."
                )

        for el in self.elements:
            for nid in el.nodes:
                if nid not in node_ids:
                    problems.append(f"Element {el.id} ({el.type}) refers to missing node {nid}.")
            mid = getattr(el, "material_id", None)
            if mid is not None and mid not in material_ids:
                problems.append(f"Element {el.id} refers to missing material {mid}.")
            sid = getattr(el, "section_id", None)
            if sid is not None and sid not in section_ids:
                problems.append(f"Element {el.id} refers to missing section {sid}.")
            mids = getattr(el, "material_ids", None)
            if mids is not None:
                for m in mids:
                    if m not in material_ids:
                        problems.append(f"Element {el.id} refers to missing material {m}.")
            if isinstance(el, BEARING_CLASSES):
                for m in el.material_reference_ids:
                    if m not in material_ids:
                        problems.append(f"Element {el.id} refers to missing material {m}.")
                if self.ndm == 3 and (el.t_material_id is None or el.my_material_id is None):
                    problems.append(
                        f"Element {el.id} ({el.type}) needs t_material_id and my_material_id "
                        "in a 3D model."
                    )
            if isinstance(el, SLIDING_BEARING_CLASSES) and el.friction_model_id not in friction_ids:
                problems.append(
                    f"Element {el.id} ({el.type}) refers to missing friction model "
                    f"{el.friction_model_id}."
                )

        for sec in self.sections:
            # Every material referenced inside a section — explicit fibres,
            # fibre-section patches/layers, and aggregator pairings — must exist,
            # as must an aggregator's base section.
            for kind, items in (
                ("fibre", getattr(sec, "fibres", None)),
                ("patch", getattr(sec, "patches", None)),
                ("layer", getattr(sec, "layers", None)),
            ):
                for child in items or []:
                    if child.material_id not in material_ids:
                        problems.append(
                            f"Section {sec.id} has a {kind} with missing material "
                            f"{child.material_id}."
                        )
            for pairing in getattr(sec, "pairings", None) or []:
                if pairing.material_id not in material_ids:
                    problems.append(
                        f"Section {sec.id} has an aggregator pairing with missing "
                        f"material {pairing.material_id}."
                    )
            base_section_id = getattr(sec, "section_id", None)
            if base_section_id is not None and base_section_id not in section_ids:
                problems.append(
                    f"Section {sec.id} refers to missing base section {base_section_id}."
                )

        for pat in self.load_patterns:
            ts_id = (
                getattr(pat, "time_series_id", None)
                or getattr(pat, "accel_series_id", None)
                or getattr(pat, "disp_series_id", None)
            )
            if ts_id is not None and ts_id not in ts_ids:
                problems.append(f"Pattern {pat.id} refers to missing time series {ts_id}.")
            for nl in getattr(pat, "nodal_loads", []):
                if nl.node_id not in node_ids:
                    problems.append(f"Pattern {pat.id} loads missing node {nl.node_id}.")
            for nid in getattr(pat, "node_ids", []):
                if nid not in node_ids:
                    problems.append(f"Pattern {pat.id} drives missing node {nid}.")

        for mp in self.mp_constraints:
            if mp.retained_node not in node_ids:
                problems.append(
                    f"MP constraint refers to missing retained node {mp.retained_node}."
                )
            if mp.constrained_node not in node_ids:
                problems.append(
                    f"MP constraint refers to missing constrained node {mp.constrained_node}."
                )
            for dof in getattr(mp, "dofs", ()):
                if dof < 1 or dof > self.ndf:
                    problems.append(
                        f"MP constraint {mp.retained_node}->{mp.constrained_node} "
                        f"uses invalid DOF {dof} for ndf={self.ndf}."
                    )

        problems.extend(self._two_node_link_problems())
        problems.extend(self._rigid_link_problems())

        if problems:
            raise ValueError("Reference validation failed:\n  - " + "\n  - ".join(problems))

    @property
    def has_rigid_links(self) -> bool:
        """True when at least one ``rigidLink beam`` tie is in the model."""
        return any(isinstance(mp, RigidLinkConstraint) for mp in self.mp_constraints)

    def _two_node_link_problems(self) -> list[str]:
        """Geometry checks of every twoNodeLink: distinct node coordinates, an
        explicit x along node i to node j, and yp not along the local x."""
        coords = {n.id: n.coords for n in self.nodes}
        problems: list[str] = []
        for el in self.elements:
            if not isinstance(el, TwoNodeLinkElement):
                continue
            if any(nid not in coords for nid in el.nodes):
                continue  # reported as a missing node above
            if any(d > self.ndf for d in el.dofs):
                problems.append(
                    f"Element {el.id} (TwoNodeLink) uses a direction above ndf={self.ndf}: "
                    f"{el.dofs}."
                )
            pi, pj = coords[el.nodes[0]], coords[el.nodes[1]]
            axis = tuple(b - a for a, b in zip(pi, pj, strict=True))
            length = math.sqrt(sum(c * c for c in axis))
            if length == 0.0:
                problems.append(
                    f"Element {el.id} (TwoNodeLink): nodes {el.nodes[0]} and {el.nodes[1]} "
                    "are at the same coordinates; use a ZeroLength element for coincident "
                    "nodes."
                )
                continue
            x = el.orient_x if el.orient_x is not None else axis
            if el.orient_x is not None:
                nx = math.sqrt(sum(c * c for c in x))
                if (
                    _cross_norm(x, axis) > TWO_NODE_LINK_PARALLEL_TOL * nx * length
                    or sum(a * b for a, b in zip(x, axis, strict=True)) <= 0.0
                ):
                    problems.append(
                        f"Element {el.id} (TwoNodeLink): orient_x {el.orient_x} is not "
                        f"parallel to node {el.nodes[0]} -> node {el.nodes[1]} {axis} "
                        f"within {TWO_NODE_LINK_PARALLEL_TOL} (it must point from i to j)."
                    )
            if el.orient_y is not None:
                nx = math.sqrt(sum(c * c for c in x))
                ny = math.sqrt(sum(c * c for c in el.orient_y))
                if _cross_norm(x, el.orient_y) <= TWO_NODE_LINK_PARALLEL_TOL * nx * ny:
                    problems.append(
                        f"Element {el.id} (TwoNodeLink): orient_y {el.orient_y} is parallel "
                        "to the local x axis."
                    )
        return problems

    def _rigid_link_problems(self) -> list[str]:
        """Rigid-tie checks: no self tie, rotational DOF present, a constrained node
        tied only once, and no fixity on a tied DOF of the constrained node."""
        links = [mp for mp in self.mp_constraints if isinstance(mp, RigidLinkConstraint)]
        if not links:
            return []
        problems: list[str] = []
        if (self.ndm, self.ndf) not in {(2, 3), (3, 6)}:
            problems.append(
                f"Rigid link needs rotational DOF (ndm=2/ndf=3 or ndm=3/ndf=6); this "
                f"model has ndm={self.ndm}, ndf={self.ndf}."
            )
        nodes = {n.id: n for n in self.nodes}
        constrained_by: dict[int, int] = {}
        for mp in self.mp_constraints:
            constrained_by[mp.constrained_node] = constrained_by.get(mp.constrained_node, 0) + 1
        dof_slots = (0, 1, 5) if self.ndf == 3 else tuple(range(6))
        for mp in links:
            tag = f"Rigid link {mp.retained_node}->{mp.constrained_node}"
            if mp.retained_node == mp.constrained_node:
                problems.append(f"{tag}: a node may not be tied to itself.")
                continue
            if constrained_by.get(mp.constrained_node, 0) > 1:
                problems.append(
                    f"{tag}: node {mp.constrained_node} is the constrained node of more "
                    "than one tie; a constrained node may be tied only once."
                )
            node = nodes.get(mp.constrained_node)
            if node is not None and any(node.restraint[i] for i in dof_slots):
                problems.append(
                    f"{tag}: constrained node {mp.constrained_node} has a fixity on a tied "
                    "DOF; restrain the retained node instead."
                )
        return list(dict.fromkeys(problems))

    def check_ground_motion_records(self, pattern_ids: Iterable[PositiveInt]) -> None:
        """Refuse to run patterns whose record-backed series are unhealthy.

        Called by the analysis runner before building the model. A
        record-backed :class:`PathTimeSeries` is runnable only when its
        catalog entry loaded cleanly ('ok', or 'pending_sidecar' with the
        legacy values still in memory).

        Raises:
            ValueError: naming each unusable record and its path.
        """
        wanted = set(pattern_ids)
        gm_by_id = {gm.id: gm for gm in self.ground_motions}
        ts_by_id = {ts.id: ts for ts in self.time_series}
        problems: list[str] = []

        for pat in self.load_patterns:
            if pat.id not in wanted:
                continue
            for attr in ("time_series_id", "accel_series_id", "vel_series_id", "disp_series_id"):
                sid = getattr(pat, attr, None)
                if sid is None:
                    continue
                ts = ts_by_id.get(sid)
                rec_id = getattr(ts, "record_id", None)
                if ts is None or rec_id is None:
                    continue
                rec = gm_by_id.get(rec_id)
                label = f"'{rec.name}' ({rec.source_path})" if rec is not None else f"{rec_id}"
                if rec is None:
                    problems.append(
                        f"Pattern {pat.id}: time series {sid} references "
                        f"ground-motion record {rec_id}, which is not in the catalog."
                    )
                elif rec.status == "missing":
                    problems.append(
                        f"Pattern {pat.id}: ground-motion record {label} - file not found. "
                        "Relink it in Define > Ground Motions."
                    )
                elif rec.status == "hash_mismatch":
                    problems.append(
                        f"Pattern {pat.id}: ground-motion record {label} - the file changed "
                        "on disk since it was catalogued (content hash mismatch). "
                        "Relink it in Define > Ground Motions to accept the new content."
                    )
                elif not ts.values:
                    problems.append(
                        f"Pattern {pat.id}: ground-motion record {label} has no samples loaded."
                    )

        if problems:
            raise ValueError("Cannot run this case:\n  - " + "\n  - ".join(problems))
