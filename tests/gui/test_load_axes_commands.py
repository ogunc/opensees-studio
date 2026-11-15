"""The frame-load commands convert a global vector per member (core.load_axes)."""

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
    UniformElementLoad,
)
from opensees_studio.viewmodels import ProjectViewModel

pytestmark = pytest.mark.gui


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
