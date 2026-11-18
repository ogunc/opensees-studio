"""Staged construction: which elements and joints exist at each stage.

A :class:`~opensees_studio.core.analysis.StagedCase` lists stages that add and
remove groups of elements. This module turns that list into a plan the runner
follows and the case check reads:

* an element in a group some stage adds is **pending** until that stage; every
  other element exists from the start;
* an element in a group a stage removes leaves at that stage (it must exist by
  then, and it cannot come back);
* a joint is **active** while an active element touches it; a joint only pending
  elements touch is held still until they arrive.

No Qt, no OpenSees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StagePlan:
    """The elements that appear and leave at each stage, and what is wrong."""

    initial: set[int]
    """Elements that exist before the first stage."""
    added: list[list[int]]
    """Per stage, the element ids it activates."""
    removed: list[list[int]]
    """Per stage, the element ids it takes away."""
    errors: list[str] = field(default_factory=list)

    @property
    def staged(self) -> set[int]:
        """Every element some stage adds or removes."""
        return {e for ids in self.added for e in ids} | {e for ids in self.removed for e in ids}

    def active_after(self, stage: int) -> set[int]:
        """Elements that exist at the end of ``stage`` (0-based); -1 = before the first."""
        active = set(self.initial)
        for k in range(stage + 1):
            active |= set(self.added[k])
            active -= set(self.removed[k])
        return active


def _element_nodes(element: Any) -> tuple[int, ...]:
    return tuple(getattr(element, "nodes", ()))


def stage_plan(project: Any, case: Any) -> StagePlan:
    """The activation plan of ``case`` on ``project``, with every inconsistency in ``errors``."""
    groups = {g.id: g for g in project.groups}
    elements = {e.id: e for e in project.elements}
    errors: list[str] = []
    prefix = f"Staged case {case.id}"

    added: list[list[int]] = []
    removed: list[list[int]] = []
    for k, stage in enumerate(case.stages, start=1):
        label = f"{prefix}, stage {k}" + (f" ({stage.name})" if stage.name else "")
        ids_in: list[int] = []
        ids_out: list[int] = []
        for gid, bucket in [(g, ids_in) for g in stage.add_group_ids] + [
            (g, ids_out) for g in stage.remove_group_ids
        ]:
            group = groups.get(gid)
            if group is None:
                errors.append(f"{label}: group {gid} does not exist.")
                continue
            for eid in group.element_ids:
                if eid in elements and eid not in bucket:
                    bucket.append(eid)
            if not group.element_ids:
                errors.append(f"{label}: group {gid} ({group.name}) has no elements.")
        added.append(sorted(ids_in))
        removed.append(sorted(ids_out))

    pending = {e for ids in added for e in ids}
    initial = set(elements) - pending
    first_add: dict[int, int] = {}
    for k, ids in enumerate(added):
        for eid in ids:
            if eid in first_add:
                errors.append(
                    f"{prefix}: element {eid} is added twice (stages {first_add[eid] + 1} "
                    f"and {k + 1})."
                )
            else:
                first_add[eid] = k

    plan = StagePlan(initial=initial, added=added, removed=removed, errors=errors)
    gone: dict[int, int] = {}
    for k, ids in enumerate(removed):
        active_before = plan.active_after(k - 1) | set(added[k])
        for eid in ids:
            if eid in gone:
                errors.append(f"{prefix}: element {eid} is removed twice.")
            elif eid not in active_before:
                errors.append(
                    f"{prefix}, stage {k + 1}: element {eid} is removed before it is built."
                )
            gone.setdefault(eid, k)
    for eid, k in first_add.items():
        if eid in gone and gone[eid] < k:
            errors.append(f"{prefix}: element {eid} is added after it was removed.")

    # Loads may only act on elements that exist while they are applied.
    patterns = {p.id: p for p in project.load_patterns}
    for k, stage in enumerate(case.stages):
        active = plan.active_after(k)
        for pid in stage.pattern_ids:
            pattern = patterns.get(pid)
            if pattern is None:
                continue
            loaded: set[int] = set()
            for attr in (
                "element_loads",
                "point_loads",
                "distributed_loads",
                "surface_loads",
                "temperature_loads",
                "tendon_loads",
            ):
                for load in getattr(pattern, attr, []) or []:
                    eid = getattr(load, "element_id", None)
                    if eid is not None:
                        loaded.add(int(eid))
            missing = sorted(loaded - active)
            if missing:
                errors.append(
                    f"{prefix}, stage {k + 1}: pattern {pid} loads element(s) "
                    f"{', '.join(map(str, missing[:8]))} that do not exist in that stage."
                )

    return plan


def late_joints(project: Any, plan: StagePlan) -> set[int]:
    """Joints only staged elements reach: held still until their elements are built."""
    elements = {e.id: e for e in project.elements}
    staged_nodes = {n for eid in plan.staged for n in _element_nodes(elements[eid])}
    always = {n for eid in plan.initial for n in _element_nodes(elements[eid])}
    return staged_nodes - always


def staged_errors(project: Any, case: Any) -> list[str]:
    """Only the errors of :func:`stage_plan`."""
    return stage_plan(project, case).errors
