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

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

from opensees_studio.core._base import omit_when_default
from opensees_studio.core.analysis import AnalysisCase
from opensees_studio.core.combinations import LoadCombination
from opensees_studio.core.constraints import EqualDOFConstraint, RigidDiaphragm, RigidLink
from opensees_studio.core.custom_commands import CustomCommandBlock
from opensees_studio.core.design.settings import DesignSettings
from opensees_studio.core.diaphragms import constraint_chain_problems, diaphragm_problems
from opensees_studio.core.friction import FrictionModel
from opensees_studio.core.geometry import (
    BEARING_CLASSES,
    FRAME_ELEMENT_CLASSES,
    SLIDING_BEARING_CLASSES,
    CoordinateGridSystem,
    Element,
    GridSystem,
    MVLEMElement,
    Node,
    TripleFrictionPendulumElement,
    default_global_system,
)
from opensees_studio.core.ground_motion import GroundMotionRecord
from opensees_studio.core.groups import Group, group_problems
from opensees_studio.core.loads import LoadPattern, PathTimeSeries, ResponseSpectrum, TimeSeries
from opensees_studio.core.mass_source import MassSource
from opensees_studio.core.materials import Material
from opensees_studio.core.materials.library import material_reference_problems
from opensees_studio.core.section_cuts import SectionCut, cut_problems
from opensees_studio.core.sections import ElasticSection, NonprismaticSection, Section
from opensees_studio.core.storeys import Storey
from opensees_studio.core.target_spectrum import TargetSpectrum
from opensees_studio.core.units import UnitSystem
from opensees_studio.core.view_settings import ViewSettings


class ProjectMeta(BaseModel):
    """Project-level metadata."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    # A project that never changed its display system dumps exactly as before.
    serialize_without_defaults = omit_when_default("display_units")

    name: str = "Untitled"
    description: str = ""
    author: str = ""
    units: UnitSystem = UnitSystem.SI_M_N
    """The unit system the model is built in — the units of every value the
    engineer typed. Never rewritten by a display change."""

    display_units: UnitSystem | None = None
    """The system results are *shown* in (SAP2000 "Set Display Units").

    ``None`` — the default, and what every file written before this field
    existed means — shows results in :attr:`units`. Setting it converts the
    numbers the analysis produced (diagrams, displacements, tables, curves)
    for display only; the model and its inputs are untouched.
    """


class Project(BaseModel):
    """The root aggregate. Serializable to/from JSON via ``model_dump_json``."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    # The building fields and the load combinations are additive: a project
    # without storeys, diaphragms, rigid links, a mass source or combinations
    # saves byte-identical to before they existed.
    serialize_without_defaults = omit_when_default(
        "storeys",
        "diaphragms",
        "rigid_links",
        "mass_source",
        "combinations",
        "groups",
        "section_cuts",
        "custom_commands",
        "view",
        "design",
    )

    # 1 = pre ground-motion catalog (records embedded in PathTimeSeries),
    # 2 = ground_motions catalog with record-backed time series,
    # 3 = 2D models in the X-Z plane, Z up (core.plane).
    # ``services.persistence`` migrates v1 payloads on load and stamps the
    # current version on save.
    schema_version: int = Field(default=3, frozen=True)
    meta: ProjectMeta = Field(default_factory=ProjectMeta)

    ndm: int = Field(default=3, description="Spatial dimensions (2 or 3).")
    ndf: int = Field(default=6, description="DOFs per node (1, 2, 3, or 6).")

    coord_systems: list[CoordinateGridSystem] = Field(
        default_factory=lambda: [default_global_system()],
    )
    storeys: list[Storey] = Field(
        default_factory=list,
        description="Floor levels (elevation along Z); additive.",
    )
    nodes: list[Node] = Field(default_factory=list)
    materials: list[Material] = Field(default_factory=list)

    view: ViewSettings | None = None
    """Display settings of the primary viewport (View → Visibility / Colors).

    ``None`` — the default, and what every file written before this field
    existed means — renders with :class:`ViewSettings` defaults, so an
    untouched project still saves byte-identical.
    """

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
    mp_constraints: list[EqualDOFConstraint] = Field(default_factory=list)
    diaphragms: list[RigidDiaphragm] = Field(
        default_factory=list, description="rigidDiaphragm constraints (additive)."
    )
    rigid_links: list[RigidLink] = Field(
        default_factory=list, description="rigidLink beam/bar constraints (additive)."
    )
    mass_source: MassSource | None = Field(
        default=None,
        description="Mass derived from self weight and load patterns; None = typed masses only.",
    )
    time_series: list[TimeSeries] = Field(default_factory=list)
    load_patterns: list[LoadPattern] = Field(default_factory=list)
    spectra: list[ResponseSpectrum] = Field(default_factory=list)
    ground_motions: list[GroundMotionRecord] = Field(default_factory=list)
    target_spectra: list[TargetSpectrum] = Field(
        default_factory=list,
        description="Design/target spectra in g for record scaling (additive, schema 2).",
    )
    analyses: list[AnalysisCase] = Field(default_factory=list)
    combinations: list[LoadCombination] = Field(
        default_factory=list,
        description="Load combinations of analysis-case results (additive, schema 2).",
    )
    groups: list[Group] = Field(
        default_factory=list,
        description="Named sets of joints and elements (Define → Groups; additive).",
    )
    custom_commands: list[CustomCommandBlock] = Field(
        default_factory=list,
        description="Python blocks of OpenSeesPy calls run during the build (additive).",
    )
    section_cuts: list[SectionCut] = Field(
        default_factory=list,
        description="Resultant forces through a group (Define → Section Cuts; additive).",
    )
    design: DesignSettings | None = Field(
        default=None,
        description="Steel frame and storey drift check settings (Design menu); None = unused.",
    )

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
            ("storey", self.storeys),
            ("diaphragm", self.diaphragms),
            ("load combination", self.combinations),
            ("group", self.groups),
            ("section cut", self.section_cuts),
            ("custom command block", self.custom_commands),
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

    def next_spectrum_id(self) -> int:
        """Lowest unused id for a case response spectrum (``project.spectra``)."""
        return max((s.id for s in self.spectra), default=0) + 1

    def next_target_spectrum_id(self) -> int:
        return self._next_id(self.target_spectra)

    def next_analysis_id(self) -> int:
        return self._next_id(self.analyses)

    def next_combination_id(self) -> int:
        return self._next_id(self.combinations)

    def next_storey_id(self) -> int:
        return self._next_id(self.storeys)

    def next_diaphragm_id(self) -> int:
        return self._next_id(self.diaphragms)

    def next_group_id(self) -> int:
        return self._next_id(self.groups)

    def next_section_cut_id(self) -> int:
        return self._next_id(self.section_cuts)

    # ─────────────────── lookups ───────────────────
    def node(self, node_id: PositiveInt) -> Node:
        return self._get(self.nodes, node_id, "node")

    def material(self, material_id: PositiveInt) -> Material:
        return self._get(self.materials, material_id, "material")

    def section(self, section_id: PositiveInt) -> Section:
        return self._get(self.sections, section_id, "section")

    def friction_model(self, friction_model_id: PositiveInt) -> FrictionModel:
        return self._get(self.friction_models, friction_model_id, "friction model")

    def element(self, element_id: PositiveInt) -> Element:
        return self._get(self.elements, element_id, "element")

    def ground_motion(self, record_id: PositiveInt) -> GroundMotionRecord:
        return self._get(self.ground_motions, record_id, "ground motion")

    def target_spectrum(self, spectrum_id: PositiveInt) -> TargetSpectrum:
        return self._get(self.target_spectra, spectrum_id, "target spectrum")

    def combination(self, combination_id: PositiveInt) -> LoadCombination:
        for combo in self.combinations:
            if combo.id == combination_id:
                return combo
        raise KeyError(f"Load combination with id={combination_id} not found.")

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
        element_ids = {e.id for e in self.elements}
        elements_by_id = {e.id: e for e in self.elements}
        material_ids = {m.id for m in self.materials}
        section_ids = {s.id for s in self.sections}
        ts_ids = {ts.id for ts in self.time_series}
        gm_ids = {gm.id for gm in self.ground_motions}
        friction_ids = {fm.id for fm in self.friction_models}
        problems: list[str] = []

        if self.ndm == 2:
            # A 2D model lives in the X-Z plane (core.plane): OpenSees never sees y.
            off_plane = [n.id for n in self.nodes if abs(float(n.coords[1])) > 1e-9]
            if off_plane:
                shown = ", ".join(str(i) for i in off_plane[:10])
                more = f" and {len(off_plane) - 10} more" if len(off_plane) > 10 else ""
                problems.append(
                    f"2D model: node(s) {shown}{more} are off the X-Z plane (y != 0). A 2D "
                    "model is drawn in X-Z with Z up; move them to y = 0."
                )

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
            if isinstance(el, MVLEMElement):
                if self.ndm != 2 or self.ndf != 3:
                    problems.append(
                        f"Element {el.id} (MVLEM) needs a 2D model with 3 DOF per joint."
                    )
                for m in el.material_reference_ids:
                    if m not in material_ids:
                        problems.append(f"Element {el.id} refers to missing material {m}.")
            if isinstance(el, TripleFrictionPendulumElement):
                if self.ndm != 3 or self.ndf != 6:
                    problems.append(
                        f"Element {el.id} (TripleFrictionPendulum) needs a 3D model with 6 DOF."
                    )
                for m in el.material_reference_ids:
                    if m not in material_ids:
                        problems.append(f"Element {el.id} refers to missing material {m}.")
                for fm in el.friction_model_ids:
                    if fm not in friction_ids:
                        problems.append(f"Element {el.id} refers to missing friction model {fm}.")
            if isinstance(el, SLIDING_BEARING_CLASSES) and el.friction_model_id not in friction_ids:
                problems.append(
                    f"Element {el.id} ({el.type}) refers to missing friction model "
                    f"{el.friction_model_id}."
                )

        sections_by_id = {s.id: s for s in self.sections}
        for sec in self.sections:
            if isinstance(sec, NonprismaticSection):
                for segment in sec.segments:
                    for sid in (segment.start_section_id, segment.end_section_id):
                        if sid == sec.id:
                            problems.append(f"Nonprismatic section {sec.id} refers to itself.")
                            continue
                        ref = sections_by_id.get(sid)
                        if ref is None:
                            problems.append(
                                f"Nonprismatic section {sec.id} refers to missing section {sid}."
                            )
                        elif not isinstance(ref, ElasticSection):
                            problems.append(
                                f"Nonprismatic section {sec.id} refers to section {sid} "
                                f"({ref.type}); segments must use ElasticSection."
                            )
                try:
                    sec.fractions()
                except ValueError as exc:
                    problems.append(f"Nonprismatic section {sec.id}: {exc}")
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
            for pl in getattr(pat, "point_loads", []):
                if pl.element_id not in element_ids:
                    problems.append(
                        f"Pattern {pat.id} has a point load on missing element {pl.element_id}."
                    )
            for tl in getattr(pat, "temperature_loads", []):
                if tl.element_id not in element_ids:
                    problems.append(
                        f"Pattern {pat.id} has a temperature load on missing element "
                        f"{tl.element_id}."
                    )
            for dl in getattr(pat, "distributed_loads", []):
                if dl.element_id not in element_ids:
                    problems.append(
                        f"Pattern {pat.id} has a distributed load on missing element "
                        f"{dl.element_id}."
                    )
                elif not isinstance(elements_by_id[dl.element_id], FRAME_ELEMENT_CLASSES):
                    problems.append(
                        f"Pattern {pat.id} has a distributed load on element {dl.element_id}, "
                        "which is not a frame (beam-column) element."
                    )
            for nid in getattr(pat, "node_ids", []):
                if nid not in node_ids:
                    problems.append(f"Pattern {pat.id} drives missing node {nid}.")
            for sl in getattr(pat, "surface_loads", []):
                element = elements_by_id.get(sl.element_id)
                if element is None or len(element.nodes) != 4:
                    problems.append(
                        f"Pattern {pat.id} has a surface load on element {sl.element_id}, "
                        "which is not a shell."
                    )
            for fl in getattr(pat, "floor_loads", []):
                missing = [n for n in fl.nodes if n not in node_ids]
                if missing:
                    problems.append(
                        f"Pattern {pat.id} has a floor load on missing node(s) {missing}."
                    )
            for imposed in getattr(pat, "imposed_displacements", []):
                if imposed.node_id not in node_ids:
                    problems.append(
                        f"Pattern {pat.id} imposes a displacement on missing node {imposed.node_id}."
                    )
                elif imposed.dof > self.ndf:
                    problems.append(
                        f"Pattern {pat.id} imposes DOF {imposed.dof} on node {imposed.node_id}, "
                        f"but the model has {self.ndf} DOF per node."
                    )

        for mp in self.mp_constraints:
            if mp.retained_node not in node_ids:
                problems.append(
                    f"MP constraint refers to missing retained node {mp.retained_node}."
                )
            if mp.constrained_node not in node_ids:
                problems.append(
                    f"MP constraint refers to missing constrained node {mp.constrained_node}."
                )
            for dof in mp.dofs:
                if dof < 1 or dof > self.ndf:
                    problems.append(
                        f"MP constraint {mp.retained_node}->{mp.constrained_node} "
                        f"uses invalid DOF {dof} for ndf={self.ndf}."
                    )

        for link in self.rigid_links:
            for nid in (link.retained_node, link.constrained_node):
                if nid not in node_ids:
                    problems.append(f"Rigid link refers to missing node {nid}.")
        if any(link.kind == "beam" for link in self.rigid_links) and (self.ndm, self.ndf) not in (
            (2, 3),
            (3, 6),
        ):
            problems.append(
                "A rigid beam link needs rotations: ndf=3 in 2D or ndf=6 in 3D "
                f"(this model has ndm={self.ndm}, ndf={self.ndf})."
            )
        problems.extend(diaphragm_problems(self))
        problems.extend(constraint_chain_problems(self))
        problems.extend(group_problems(self))
        problems.extend(cut_problems(self))
        problems.extend(material_reference_problems(self.materials))

        if self.mass_source is not None:
            pattern_ids = {p.id for p in self.load_patterns}
            for entry in self.mass_source.patterns:
                if entry.pattern_id not in pattern_ids:
                    problems.append(f"Mass source refers to missing pattern {entry.pattern_id}.")

        if problems:
            raise ValueError("Reference validation failed:\n  - " + "\n  - ".join(problems))

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
                elif isinstance(ts, PathTimeSeries) and not ts.values:
                    problems.append(
                        f"Pattern {pat.id}: ground-motion record {label} has no samples loaded."
                    )

        if problems:
            raise ValueError("Cannot run this case:\n  - " + "\n  - ".join(problems))
