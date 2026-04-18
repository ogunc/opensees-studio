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

from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

from opensees_studio.core.analysis import AnalysisCase
from opensees_studio.core.geometry import (
    CoordinateGridSystem,
    Element,
    GridSystem,
    Node,
    default_global_system,
)
from opensees_studio.core.loads import LoadPattern, ResponseSpectrum, TimeSeries
from opensees_studio.core.materials import Material
from opensees_studio.core.sections import Section
from opensees_studio.core.units import UnitSystem


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

    schema_version: int = Field(default=1, frozen=True)
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
            data["coord_systems"] = [{
                "name": "Global",
                "coord": {},
                "grid": legacy,
            }]
        return data

    @model_validator(mode="after")
    def _ensure_global_system(self) -> "Project":
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
    elements: list[Element] = Field(default_factory=list)
    time_series: list[TimeSeries] = Field(default_factory=list)
    load_patterns: list[LoadPattern] = Field(default_factory=list)
    spectra: list[ResponseSpectrum] = Field(default_factory=list)
    analyses: list[AnalysisCase] = Field(default_factory=list)

    # ─────────────────── invariants ───────────────────
    @model_validator(mode="after")
    def _check_ndm_ndf(self) -> "Project":
        valid = {(2, 2), (2, 3), (3, 3), (3, 6)}
        if (self.ndm, self.ndf) not in valid:
            raise ValueError(
                f"Invalid (ndm, ndf) pair: ({self.ndm}, {self.ndf}). "
                f"Must be one of {sorted(valid)}."
            )
        return self

    @model_validator(mode="after")
    def _check_unique_ids(self) -> "Project":
        for label, items in (
            ("node", self.nodes),
            ("material", self.materials),
            ("section", self.sections),
            ("element", self.elements),
            ("time series", self.time_series),
            ("load pattern", self.load_patterns),
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

    def next_element_id(self) -> int:
        return self._next_id(self.elements)

    def next_time_series_id(self) -> int:
        return self._next_id(self.time_series)

    def next_pattern_id(self) -> int:
        return self._next_id(self.load_patterns)

    def next_analysis_id(self) -> int:
        return self._next_id(self.analyses)

    # ─────────────────── lookups ───────────────────
    def node(self, node_id: PositiveInt) -> Node:
        return self._get(self.nodes, node_id, "node")

    def material(self, material_id: PositiveInt) -> Material:  # type: ignore[valid-type]
        return self._get(self.materials, material_id, "material")

    def section(self, section_id: PositiveInt) -> Section:  # type: ignore[valid-type]
        return self._get(self.sections, section_id, "section")

    def element(self, element_id: PositiveInt) -> Element:  # type: ignore[valid-type]
        return self._get(self.elements, element_id, "element")

    @staticmethod
    def _get(items: list[Any], target_id: int, label: str) -> Any:
        for item in items:
            if item.id == target_id:
                return item
        raise KeyError(f"{label.capitalize()} with id={target_id} not found.")

    # ─────────────────── reference validation ───────────────────
    def validate_references(self) -> None:
        """Check every element/load reference points to an existing entity.

        Raises:
            ValueError: with a single combined message listing all problems.
        """
        node_ids = {n.id for n in self.nodes}
        material_ids = {m.id for m in self.materials}
        section_ids = {s.id for s in self.sections}
        ts_ids = {ts.id for ts in self.time_series}
        problems: list[str] = []

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

        for sec in self.sections:
            fibres = getattr(sec, "fibres", None)
            if fibres is not None:
                for fb in fibres:
                    if fb.material_id not in material_ids:
                        problems.append(
                            f"Section {sec.id} has a fibre with missing material {fb.material_id}."
                        )

        for pat in self.load_patterns:
            ts_id = getattr(pat, "time_series_id", None) or getattr(pat, "accel_series_id", None)
            if ts_id is not None and ts_id not in ts_ids:
                problems.append(f"Pattern {pat.id} refers to missing time series {ts_id}.")
            for nl in getattr(pat, "nodal_loads", []):
                if nl.node_id not in node_ids:
                    problems.append(f"Pattern {pat.id} loads missing node {nl.node_id}.")

        if problems:
            raise ValueError("Reference validation failed:\n  - " + "\n  - ".join(problems))
