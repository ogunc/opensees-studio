"""Repair the duplicates the checker found: merge nodes, drop repeated members.

One undo step, because the two halves are not independent: merging two
coincident nodes can turn two members into the same member, so the element
duplicates are recomputed *after* the merge rather than taken from a report
computed before it. That is the case a report alone cannot see.

The merge policies, all of them chosen so the quiet direction of the mistake is
the safe one:

* **restraints are combined** (a DOF fixed on any of the nodes stays fixed) —
  silently releasing a support would produce an unstable model, and for the
  common case (a copied node) every value is identical anyway;
* **masses that agree are kept once** — a copied node must not weigh twice —
  and **masses that differ are added**, so nothing disappears without a trace;
* **references follow the keeper**: element nodes, ``equalDOF`` constraints,
  nodal loads and imposed-support node lists;
* **loads that were copies are dropped, not doubled**: two identical loads on
  the keeper are one load, but a load that only existed on the duplicate is
  repointed and kept;
* an element whose two ends merge into one node has no length left, so it is
  removed and the removal is counted in the report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from opensees_studio.commands.base import ProjectCommand, restore_project, snapshot_project
from opensees_studio.core.duplicates import NodeCluster, check_duplicates, find_element_clusters
from opensees_studio.core.loads import ImposedSupportMotionPattern, PlainLoadPattern
from opensees_studio.core.project import Project

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


@dataclass
class RepairReport:
    """What the repair did, for the log line and the dialog."""

    merged_node_groups: int = 0
    removed_nodes: int = 0
    removed_elements: int = 0
    degenerate_elements: int = 0
    repointed_loads: int = 0
    dropped_copy_loads: int = 0
    merged_constraints: int = 0
    mass_conflicts: int = 0

    def summary(self) -> str:
        if not any(vars(self).values()):
            return "Nothing to fix: no duplicate nodes or elements."
        parts = []
        if self.merged_node_groups:
            parts.append(
                f"merged {self.merged_node_groups} coincident node group(s), "
                f"removing {self.removed_nodes} node(s)"
            )
        if self.removed_elements:
            parts.append(f"removed {self.removed_elements} duplicate element(s)")
        if self.degenerate_elements:
            parts.append(f"removed {self.degenerate_elements} element(s) left with no length")
        if self.repointed_loads:
            parts.append(f"repointed {self.repointed_loads} load(s)")
        if self.dropped_copy_loads:
            parts.append(f"dropped {self.dropped_copy_loads} copied load(s)")
        if self.merged_constraints:
            parts.append(f"merged {self.merged_constraints} constraint(s)")
        if self.mass_conflicts:
            parts.append(f"added the mass of {self.mass_conflicts} node(s) with a different mass")
        return "; ".join(parts) + "."

    @property
    def changed_anything(self) -> bool:
        return any(vars(self).values())


class FixDuplicatesCommand(ProjectCommand):
    """Merge coincident nodes and remove the elements that repeat a member."""

    def __init__(self, vm: ProjectViewModel, *, tolerance: float | None = None) -> None:
        super().__init__(vm, "Fix duplicate nodes and elements")
        self._tolerance = tolerance
        self._before: dict[str, Any] | None = None
        self.report = RepairReport()

    # ── lifecycle ───────────────────────────────────────────────────
    def redo(self) -> None:
        project = self.project
        self._before = snapshot_project(project)
        self.report = RepairReport()

        found = check_duplicates(project, tolerance=self._tolerance)
        mapping = self._merge_nodes(project, found.node_clusters)
        if mapping:
            self._follow_the_keeper(project, mapping)
        self._remove_repeated_elements(project)
        self._notify()

    def undo(self) -> None:
        if self._before is not None:
            restore_project(self.project, self._before)
        self._notify()

    # ── nodes ───────────────────────────────────────────────────────
    def _merge_nodes(self, project: Project, clusters: list[NodeCluster]) -> dict[int, int]:
        if not clusters:
            return {}
        by_id = {node.id: node for node in project.nodes}
        mapping: dict[int, int] = {}
        removed: set[int] = set()
        for cluster in clusters:
            keeper = by_id[cluster.keeper_id]
            members = [by_id[node_id] for node_id in cluster.ids]
            masses = [node.mass for node in members]
            restraints = [node.restraint for node in members]
            # Equal values are kept once (a copied node must not weigh twice);
            # different ones are added, so a real mass is never lost.
            combined_mass = [
                sum(values) if len(set(values)) > 1 else values[0]
                for values in zip(*masses, strict=True)
            ]
            keeper.mass = (
                combined_mass[0],
                combined_mass[1],
                combined_mass[2],
                combined_mass[3],
                combined_mass[4],
                combined_mass[5],
            )
            if len(set(masses)) > 1:
                self.report.mass_conflicts += len(members) - 1
            # A DOF fixed on any of the nodes stays fixed: releasing a support
            # silently is the failure that produces an unstable model.
            combined = [any(values) for values in zip(*restraints, strict=True)]
            keeper.restraint = (
                combined[0],
                combined[1],
                combined[2],
                combined[3],
                combined[4],
                combined[5],
            )
            for node_id in cluster.duplicate_ids:
                mapping[node_id] = cluster.keeper_id
                removed.add(node_id)
            self.report.merged_node_groups += 1
            self.report.removed_nodes += len(cluster.duplicate_ids)
        project.nodes[:] = [node for node in project.nodes if node.id not in removed]
        return mapping

    # ── everything that pointed at the merged nodes ─────────────────
    def _follow_the_keeper(self, project: Project, mapping: dict[int, int]) -> None:
        self._repoint_elements(project, mapping)
        self._repoint_constraints(project, mapping)
        for pattern in project.load_patterns:
            if isinstance(pattern, PlainLoadPattern):
                self._repoint_nodal_loads(pattern, mapping)
            elif isinstance(pattern, ImposedSupportMotionPattern):
                pattern.node_ids = sorted({mapping.get(nid, nid) for nid in pattern.node_ids})

    def _repoint_elements(self, project: Project, mapping: dict[int, int]) -> None:
        kept: list[Any] = []
        for element in project.elements:
            mapped = tuple(mapping.get(node_id, node_id) for node_id in element.nodes)
            if len(set(mapped)) != len(mapped):
                # Both ends on the same node: the member has no length left, and
                # OpenSees would refuse it. Whatever it carried goes with it.
                self._drop_element_loads(project, element.id)
                self.report.degenerate_elements += 1
                continue
            if mapped != tuple(element.nodes):
                element = element.model_copy(update={"nodes": mapped})
            kept.append(element)
        project.elements[:] = kept

    def _repoint_constraints(self, project: Project, mapping: dict[int, int]) -> None:
        seen: set[tuple[int, int, tuple[int, ...]]] = set()
        kept = []
        for constraint in project.mp_constraints:
            retained = mapping.get(constraint.retained_node, constraint.retained_node)
            constrained = mapping.get(constraint.constrained_node, constraint.constrained_node)
            if retained == constrained:
                # A node tied to itself constrains nothing.
                self.report.merged_constraints += 1
                continue
            key = (retained, constrained, tuple(constraint.dofs))
            if key in seen:
                self.report.merged_constraints += 1
                continue
            seen.add(key)
            if (retained, constrained) != (constraint.retained_node, constraint.constrained_node):
                constraint = constraint.model_copy(
                    update={"retained_node": retained, "constrained_node": constrained}
                )
            kept.append(constraint)
        project.mp_constraints[:] = kept

    def _repoint_nodal_loads(self, pattern: PlainLoadPattern, mapping: dict[int, int]) -> None:
        seen: set[tuple[int, tuple[float, ...]]] = set()
        kept = []
        for load in pattern.nodal_loads:
            node_id = mapping.get(load.node_id, load.node_id)
            key = (node_id, tuple(load.forces))
            if key in seen:
                # The duplicate carried a copy of a load that is already here.
                self.report.dropped_copy_loads += 1
                continue
            seen.add(key)
            if node_id != load.node_id:
                self.report.repointed_loads += 1
                load = load.model_copy(update={"node_id": node_id})
            kept.append(load)
        pattern.nodal_loads[:] = kept

    # ── repeated elements, recomputed after the merge ───────────────
    def _remove_repeated_elements(self, project: Project) -> None:
        duplicates, _ = find_element_clusters(project)
        removed: set[int] = set()
        for cluster in duplicates:
            for duplicate_id in cluster.duplicate_ids:
                removed.add(duplicate_id)
                self._move_element_loads(project, duplicate_id, cluster.keeper_id)
        if removed:
            project.elements[:] = [
                element for element in project.elements if element.id not in removed
            ]
            self.report.removed_elements += len(removed)

    def _move_element_loads(self, project: Project, from_id: int, to_id: int) -> None:
        for pattern in project.load_patterns:
            if not isinstance(pattern, PlainLoadPattern):
                continue
            seen = {(load.element_id, load.wy, load.wz, load.wx) for load in pattern.element_loads}
            kept = []
            for load in pattern.element_loads:
                if load.element_id != from_id:
                    kept.append(load)
                    continue
                key = (to_id, load.wy, load.wz, load.wx)
                if key in seen:
                    self.report.dropped_copy_loads += 1
                    continue
                seen.add(key)
                self.report.repointed_loads += 1
                kept.append(load.model_copy(update={"element_id": to_id}))
            pattern.element_loads[:] = kept

    def _drop_element_loads(self, project: Project, element_id: int) -> None:
        for pattern in project.load_patterns:
            if not isinstance(pattern, PlainLoadPattern):
                continue
            kept = [load for load in pattern.element_loads if load.element_id != element_id]
            self.report.dropped_copy_loads += len(pattern.element_loads) - len(kept)
            pattern.element_loads[:] = kept
