"""Joint patterns in the interface: the commands that keep them in step, and the dialogs.

The arithmetic is pinned in ``tests/unit/test_joint_patterns.py``; here, what an
edit does to the values: meshing a hydrostatic wall keeps its resultant, Edit →
Replicate copies the values, deleting a joint deletes them, every step undoes,
and the two dialogs and the surface-load dialog build what they show.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.commands import (
    DeleteNodesCommand,
    MeshCommand,
    ReplicateCommand,
    SetJointPatternsCommand,
)
from opensees_studio.core import SurfaceLoad
from opensees_studio.core.area_loads import surface_nodal_loads
from opensees_studio.core.mesh import mesh_shells
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs.area_loads import SurfaceLoadDialog
from opensees_studio.views.dialogs.joint_patterns import (
    NEW_PATTERN,
    AssignJointPatternDialog,
    JointPatternsDialog,
)
from tests.unit.test_joint_patterns import HEIGHT, WATER, WIDTH, _wall


def _vm() -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.adopt(_wall())
    return vm


def _resultant(vm: ProjectViewModel) -> np.ndarray:
    project = vm.project
    assert project is not None
    return np.sum(
        list(surface_nodal_loads(project, project.load_patterns[0].surface_loads).values()), axis=0
    )


# ──────────────────────────── commands ────────────────────────────
@pytest.mark.gui
def test_meshing_a_hydrostatic_wall_interpolates_the_values_and_keeps_the_resultant() -> None:
    vm = _vm()
    before = _resultant(vm)
    plan = mesh_shells(vm.project, {1}, target_size=0.5)
    vm.apply_command(MeshCommand(vm, plan))

    project = vm.project
    values = project.joint_patterns[0].values
    for node in plan.new_nodes:  # every new node below the free surface has its depth
        assert values.get(node.id, 0.0) == pytest.approx(WATER * (HEIGHT - node.coords[2]))
    assert _resultant(vm) == pytest.approx(before)
    assert before[1] == pytest.approx(-0.5 * WATER * HEIGHT**2 * WIDTH)

    vm.undo_stack.undo()
    assert set(vm.project.joint_patterns[0].values) == {1, 2}


@pytest.mark.gui
def test_replicating_a_wall_copies_its_values_and_undo_takes_them_back() -> None:
    vm = _vm()
    vm.apply_command(ReplicateCommand(vm, {1, 2, 3, 4}, {1}, (0.0, 5.0, 0.0), 1))
    values = vm.project.joint_patterns[0].values
    assert len(values) == 4  # nodes 1, 2 and their two copies
    assert _resultant(vm)[1] == pytest.approx(-WATER * HEIGHT**2 * WIDTH)

    vm.undo_stack.undo()
    assert set(vm.project.joint_patterns[0].values) == {1, 2}


@pytest.mark.gui
def test_deleting_a_joint_deletes_its_values_and_undo_restores_them() -> None:
    vm = _vm()
    vm.apply_command(DeleteNodesCommand(vm, {1}))
    assert 1 not in vm.project.joint_patterns[0].values
    vm.undo_stack.undo()
    assert vm.project.joint_patterns[0].value(1) == pytest.approx(3 * WATER)


@pytest.mark.gui
def test_a_pattern_a_load_uses_cannot_be_removed() -> None:
    vm = _vm()
    with pytest.raises(ValueError, match="carry a surface load"):
        vm.apply_command(SetJointPatternsCommand(vm, []))
    assert len(vm.project.joint_patterns) == 1


# ──────────────────────────── dialogs ────────────────────────────
@pytest.mark.gui
def test_the_assign_dialog_builds_a_new_hydrostatic_pattern(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _wall()
    dialog = AssignJointPatternDialog(project, [1, 2, 3, 4])
    qtbot.addWidget(dialog)

    assert dialog.z_zero.value() == HEIGHT  # the top of the selection, by default
    dialog.pattern.setCurrentIndex(dialog.pattern.findData(NEW_PATTERN))
    dialog.new_name.setText("EARTH")
    dialog.weight.setValue(18000.0)
    dialog.z_zero.setValue(2.0)  # above it the values would be negative: zeroed
    patterns = dialog.patterns()

    earth = next(p for p in patterns if p.name == "EARTH")
    assert earth.values == {1: pytest.approx(36000.0), 2: pytest.approx(36000.0)}
    assert "0 to 36000" in dialog.preview.text()
    assert len(patterns) == 2  # WATER kept


@pytest.mark.gui
def test_the_assign_dialog_adds_a_plane_to_existing_values(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _wall()
    dialog = AssignJointPatternDialog(project, [1, 3])
    qtbot.addWidget(dialog)
    dialog.by_plane.setChecked(True)
    assert not dialog.by_depth.isChecked()  # one method at a time
    dialog.d.setValue(1.0)
    dialog.restriction.setCurrentIndex(0)
    dialog.action.setCurrentIndex(dialog.action.findData("add"))

    (water,) = dialog.patterns()
    assert water.value(1) == pytest.approx(3 * WATER + 1.0)
    assert water.value(3) == pytest.approx(1.0)
    assert water.value(2) == pytest.approx(3 * WATER)  # not selected: unchanged


@pytest.mark.gui
def test_the_define_dialog_edits_a_value_and_refuses_to_delete_a_used_pattern(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = JointPatternsDialog(_wall())
    qtbot.addWidget(dialog)

    assert dialog._table.rowCount() == 2
    dialog._table.item(0, 1).setText("100")
    dialog._delete_pattern()
    assert "carries a surface load" in dialog._message.text()
    (water,) = dialog.patterns()
    assert water.value(1) == 100.0

    dialog._add_pattern()
    assert [p.name for p in dialog.patterns()] == ["WATER", "PATTERN2"]


@pytest.mark.gui
def test_the_surface_load_dialog_offers_the_patterns_as_a_distribution(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = SurfaceLoadDialog(1, _wall())
    qtbot.addWidget(dialog)
    assert "joint_pattern_id" not in dialog.values()

    dialog.distribution.setCurrentIndex(1)
    values = dialog.values()
    assert values == {"value": 1.0, "direction": "normal", "joint_pattern_id": 1}
    assert dialog._value_label.text().startswith("Multiplier")
    SurfaceLoad(element_id=1, **values)  # what the host builds from it


@pytest.mark.gui
def test_the_canvas_draws_the_pressure_as_arrows_as_long_as_it_is(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.adopt(_wall())
    renderer = mw._canvas._renderer
    project = mw._vm.project
    nodes = {n.id: n for n in project.nodes}
    elements = {e.id: e for e in project.elements}
    arrows = renderer._surface_load_arrows(project, nodes, elements, 1.0)

    # 3 x 3 stations at z = 0.5, 1.5 and 2.5 m, all below the water line.
    assert len(arrows) == 9
    by_depth = sorted({round(length, 9) for _, _, length in arrows}, reverse=True)
    # Relative to the largest pressure, the deep corners' (3 m): 2 x depth / 3.
    assert by_depth == pytest.approx([2.0 * 2.5 / 3, 2.0 * 1.5 / 3, 2.0 * 0.5 / 3])
    assert all(np.allclose(d, (0.0, -1.0, 0.0)) for _, d, _ in arrows)  # along the normal
