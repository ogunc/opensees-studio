"""Global-to-local conversion for frame loads, and the command that uses it."""

from __future__ import annotations

import pytest

from opensees_studio.commands import (
    AddElementLoadsCommand,
    AddElementsCommand,
    AddNodesCommand,
    AddPointElementLoadsCommand,
    AddSectionsCommand,
)
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    Node,
    PlainLoadPattern,
    PointElementLoad,
    Project,
    UniformElementLoad,
    load_axes,
)
from opensees_studio.viewmodels import ProjectViewModel


def _project(ndm: int = 3) -> Project:
    return Project(
        ndm=ndm,
        ndf=6 if ndm == 3 else 3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(1.0, 0.0, 0.0)),
            Node(id=3, coords=(0.0, 0.0, 0.0)),
            Node(id=4, coords=(0.0, 1.0, 0.0)),
            Node(id=5, coords=(0.0, 0.0, 0.0)),
            Node(id=6, coords=(0.0, 0.0, 1.0)),
        ],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=2e-5)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(3, 4), section_id=1),
            ElasticBeamColumn(id=3, nodes=(5, 6), section_id=1),
        ],
    )


def test_global_axes_project_onto_each_member_orientation() -> None:
    project = _project()
    assert load_axes.global_to_local(project, 1, (0.0, 0.0, -10.0)) == pytest.approx(
        (0.0, 0.0, -10.0)
    )
    # A member along +Y: local y is -X.
    assert load_axes.global_to_local(project, 2, (10.0, 0.0, 0.0)) == pytest.approx(
        (0.0, -10.0, 0.0)
    )
    # A member along +Z: local x is +Z.
    assert load_axes.global_to_local(project, 3, (0.0, 0.0, -10.0)) == pytest.approx(
        (-10.0, 0.0, 0.0)
    )


def test_a_global_y_load_is_refused_in_a_2d_model() -> None:
    project = _project(ndm=2)
    with pytest.raises(ValueError, match="out of plane"):
        load_axes.global_to_local(project, 1, (0.0, 1.0, 0.0))


def _vm() -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project(ndm=3, ndf=6)
    vm.apply_command(
        AddNodesCommand(
            vm,
            [
                Node(id=1, coords=(0.0, 0.0, 0.0)),
                Node(id=2, coords=(1.0, 0.0, 0.0)),
                Node(id=3, coords=(0.0, 0.0, 0.0)),
                Node(id=4, coords=(0.0, 0.0, 1.0)),
            ],
        )
    )
    vm.apply_command(
        AddSectionsCommand(
            vm,
            [ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=2e-5)],
        )
    )
    vm.apply_command(
        AddElementsCommand(
            vm,
            [
                ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
                ElasticBeamColumn(id=2, nodes=(3, 4), section_id=1),
            ],
        )
    )
    return vm


def test_the_distributed_load_command_converts_a_global_vector_per_member() -> None:
    vm = _vm()
    vm.apply_command(AddElementLoadsCommand(vm, {1, 2}, global_vector=(0.0, 0.0, -10.0)))
    loads = {
        load.element_id: load
        for pattern in vm.project.load_patterns
        if isinstance(pattern, PlainLoadPattern)
        for load in pattern.element_loads
    }
    # The X member takes the load as local z; the Z column as local x.
    assert loads[1] == UniformElementLoad(element_id=1, wz=-10.0)
    assert loads[2] == UniformElementLoad(element_id=2, wx=-10.0)


def test_the_point_load_command_converts_a_global_vector_per_member() -> None:
    vm = _vm()
    vm.apply_command(
        AddPointElementLoadsCommand(vm, {1: 0.5, 2: 0.5}, global_vector=(0.0, 0.0, -10.0))
    )
    loads = {
        load.element_id: load
        for pattern in vm.project.load_patterns
        if isinstance(pattern, PlainLoadPattern)
        for load in pattern.point_loads
    }
    assert loads[1] == PointElementLoad(element_id=1, pz=-10.0, x=0.5)
    assert loads[2] == PointElementLoad(element_id=2, px=-10.0, x=0.5)
