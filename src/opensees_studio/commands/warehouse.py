"""Insert a planned warehouse (``core.warehouse.plan_warehouse``) as one undo step.

The plan is checked against the project *before* anything is pushed: an error
raised inside a command's ``redo`` is lost by ``QUndoStack.push``, and a macro
that fails half way leaves its first commands in the model. So a plan either
goes in whole, as one macro, or raises without touching the project.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opensees_studio.commands.analysis import AddAnalysisCasesCommand
from opensees_studio.commands.buildings import SetDesignSettingsCommand
from opensees_studio.commands.combinations import AddCombinationsCommand
from opensees_studio.commands.elements import AddElementsCommand
from opensees_studio.commands.grid import SetCoordSystemsCommand
from opensees_studio.commands.groups import SetGroupsCommand
from opensees_studio.commands.loads import AddPatternLoadsCommand
from opensees_studio.commands.nodes import AddNodesCommand
from opensees_studio.commands.sections import AddSectionsCommand
from opensees_studio.commands.series_and_patterns import (
    AddLoadPatternCommand,
    AddTimeSeriesCommand,
)
from opensees_studio.core.loads import PlainLoadPattern
from opensees_studio.core.warehouse import WarehousePlan

if TYPE_CHECKING:
    from opensees_studio.core.project import Project
    from opensees_studio.viewmodels import ProjectViewModel


def plan_problems(project: Project, plan: WarehousePlan) -> list[str]:
    """Why ``plan`` cannot be inserted into ``project`` as it is; empty when it can."""
    problems: list[str] = []

    def clash(what: str, new: list[Any], existing: list[Any]) -> None:
        taken = {item.id for item in existing}
        ids = [item.id for item in new]
        repeated = sorted({i for i in ids if i in taken or ids.count(i) > 1})
        if repeated:
            problems.append(f"{what} id(s) already in use: {repeated[:5]}.")

    clash("Section", plan.sections, project.sections)
    clash("Node", plan.warehouse.nodes, project.nodes)
    clash("Element", plan.warehouse.elements, project.elements)
    clash("Group", plan.groups, project.groups)
    clash("Time series", plan.time_series, project.time_series)
    clash("Load pattern", plan.patterns, project.load_patterns)
    clash("Analysis case", plan.cases, project.analyses)
    clash("Combination", plan.combinations, project.combinations)

    sections = {s.id for s in (*project.sections, *plan.sections)}
    unknown = sorted({e.section_id for e in plan.warehouse.elements} - sections)
    if unknown:
        problems.append(f"Missing section(s): {unknown}.")
    plain = {
        p.id for p in (*project.load_patterns, *plan.patterns) if isinstance(p, PlainLoadPattern)
    }
    for pattern_id, list_name, _loads in plan.pattern_loads:
        if pattern_id not in plain:
            problems.append(f"Load pattern {pattern_id} ({list_name}) is not a Plain pattern.")
    if plan.grid is not None and any(c.name == plan.grid.name for c in project.coord_systems):
        problems.append(f"A coordinate system named '{plan.grid.name}' already exists.")
    return problems


def insert_warehouse_plan(
    vm: ProjectViewModel, plan: WarehousePlan, *, text: str = "Create warehouse"
) -> None:
    """Push ``plan`` into the open project as one undoable macro.

    Raises:
        ValueError: when the plan does not fit the project (nothing is pushed).
    """
    project = vm.project
    if project is None:
        raise ValueError("Open or create a project first.")
    problems = plan_problems(project, plan)
    if problems:
        raise ValueError(" ".join(problems))

    stack = vm.undo_stack
    stack.beginMacro(text)
    try:
        if plan.sections:
            vm.apply_command(AddSectionsCommand(vm, plan.sections))
        vm.apply_command(AddNodesCommand(vm, plan.warehouse.nodes))
        vm.apply_command(AddElementsCommand(vm, plan.warehouse.elements))
        if plan.groups:
            vm.apply_command(SetGroupsCommand(vm, [*project.groups, *plan.groups]))
        if plan.grid is not None:
            vm.apply_command(SetCoordSystemsCommand(vm, [*project.coord_systems, plan.grid]))
        for series in plan.time_series:
            vm.apply_command(AddTimeSeriesCommand(vm, series))
        for pattern in plan.patterns:
            vm.apply_command(AddLoadPatternCommand(vm, pattern))
        if plan.cases:
            vm.apply_command(AddAnalysisCasesCommand(vm, plan.cases))
        for pattern_id, list_name, loads in plan.pattern_loads:
            vm.apply_command(AddPatternLoadsCommand(vm, list_name, loads, pattern_id))
        if plan.combinations:
            vm.apply_command(AddCombinationsCommand(vm, plan.combinations))
        if plan.design is not None:
            vm.apply_command(SetDesignSettingsCommand(vm, plan.design))
    finally:
        stack.endMacro()


__all__ = ["insert_warehouse_plan", "plan_problems"]
