"""Properties panel with several things selected: edit what they share, in one step."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import Qt

from opensees_studio.commands import (
    AddElementsCommand,
    AddMaterialsCommand,
    AddNodesCommand,
    AddSectionsCommand,
)
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    ElasticUniaxial,
    FrameEndOffsets,
    Node,
    TrussElement,
)
from opensees_studio.views.docks.property_editor import VARIES

FIXED_2D = (True, False, True, False, True, False)


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    vm = mw._vm
    vm.new_project(ndm=2, ndf=3)
    vm.apply_command(
        AddNodesCommand(
            vm,
            [
                Node(id=1, coords=(0.0, 0.0, 0.0), restraint=FIXED_2D),
                Node(id=2, coords=(0.0, 0.0, 3.0), mass=(2.0, 0.0, 2.0, 0.0, 0.0, 0.0)),
                Node(id=3, coords=(5.0, 0.0, 3.0), mass=(4.0, 0.0, 4.0, 0.0, 0.0, 0.0)),
                Node(id=4, coords=(5.0, 0.0, 0.0), restraint=FIXED_2D),
            ],
        )
    )
    vm.apply_command(
        AddSectionsCommand(
            vm,
            [
                ElasticSection(id=1, name="C", E=2e8, A=0.02, Iz=2e-4),
                ElasticSection(id=2, name="B", E=2e8, A=0.01, Iz=1e-4),
            ],
        )
    )
    vm.apply_command(AddMaterialsCommand(vm, [ElasticUniaxial(id=1, E=2e8)]))
    vm.apply_command(
        AddElementsCommand(
            vm,
            [
                ElasticBeamColumn(
                    id=1,
                    nodes=(1, 2),
                    section_id=1,
                    end_offsets=FrameEndOffsets(length_i=0.2),
                ),
                ElasticBeamColumn(id=2, nodes=(2, 3), section_id=2),
                ElasticBeamColumn(
                    id=3,
                    nodes=(4, 3),
                    section_id=1,
                    end_offsets=FrameEndOffsets(length_i=0.4),
                ),
                TrussElement(id=4, nodes=(1, 3), area=0.005, material_id=1),
            ],
        )
    )
    return mw


def _select(mw, nodes=(), elements=()):  # type: ignore[no-untyped-def]
    mw._canvas.selection.set_selection(set(nodes), set(elements))
    mw._props.update_for_selection(frozenset(nodes), frozenset(elements))
    return mw._props


@pytest.mark.gui
def test_shared_masses_show_and_differing_ones_say_varies(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    props = _select(mw, nodes=(2, 3))
    mx, my = props._multi_mass_fields[0], props._multi_mass_fields[1]
    assert mx.text() == VARIES
    assert my.text() == "0"


@pytest.mark.gui
def test_one_mass_typed_for_two_joints_keeps_the_rest_of_each(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    props = _select(mw, nodes=(2, 3))
    props._multi_mass_fields[0].setValue(10.0)  # mx for both; mz still differs
    props._multi_node_apply.click()
    project = mw._vm.project
    assert project.node(2).mass == (10.0, 0.0, 2.0, 0.0, 0.0, 0.0)
    assert project.node(3).mass == (10.0, 0.0, 4.0, 0.0, 0.0, 0.0)
    mw._vm.undo_stack.undo()  # one step
    assert project.node(2).mass[0] == 2.0 and project.node(3).mass[0] == 4.0


@pytest.mark.gui
def test_a_mixed_restraint_stays_per_joint_and_a_set_one_applies_to_all(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    props = _select(mw, nodes=(1, 2))
    ux, _uy, uz = props._multi_restraint_boxes[:3]
    assert ux.checkState() == Qt.CheckState.PartiallyChecked
    uz.setCheckState(Qt.CheckState.Checked)  # Uz: fixed on 1, now on 2 too
    props._multi_node_apply.click()
    project = mw._vm.project
    assert project.node(1).restraint == FIXED_2D
    assert project.node(2).restraint == (False, False, True, False, False, False)


@pytest.mark.gui
def test_frames_take_a_section_and_a_transformation_in_one_step(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    props = _select(mw, elements=(1, 2, 3))
    controls = props._multi_element_controls
    section = controls["section_id"]
    assert section.currentText() == VARIES
    section.setCurrentIndex(section.findData(2))
    transf = controls["geom_transf"]
    transf.setCurrentIndex(transf.findData("PDelta"))
    props._multi_element_apply.click()
    project = mw._vm.project
    assert {project.element(i).section_id for i in (1, 2, 3)} == {2}
    assert {project.element(i).geom_transf for i in (1, 2, 3)} == {"PDelta"}
    mw._vm.undo_stack.undo()
    assert project.element(1).section_id == 1 and project.element(1).geom_transf == "Linear"


@pytest.mark.gui
def test_an_offset_field_left_alone_keeps_each_member_its_own(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    props = _select(mw, elements=(1, 3))
    controls = props._multi_element_controls
    assert controls["length_i"].text() == VARIES
    controls["rigid_factor"].setValue(0.5)
    props._multi_element_apply.click()
    project = mw._vm.project
    assert project.element(1).end_offsets == FrameEndOffsets(length_i=0.2, rigid_factor=0.5)
    assert project.element(3).end_offsets == FrameEndOffsets(length_i=0.4, rigid_factor=0.5)


@pytest.mark.gui
def test_a_mixed_selection_edits_each_field_where_it_exists(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    props = _select(mw, nodes=(2,), elements=(2, 4))
    controls = props._multi_element_controls
    controls["area"].setValue(0.02)  # the truss only
    transf = controls["geom_transf"]
    transf.setCurrentIndex(transf.findData("Corotational"))  # the beam only
    props._multi_element_apply.click()
    project = mw._vm.project
    assert project.element(4).area == 0.02
    assert project.element(2).geom_transf == "Corotational"


@pytest.mark.gui
def test_changing_the_type_converts_the_whole_selection(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    props = _select(mw, elements=(2, 4))
    kind = props._multi_element_controls["type"]
    assert kind.currentText() == VARIES
    kind.setCurrentIndex(kind.findData("ForceBeamColumn"))
    props._multi_element_apply.click()
    project = mw._vm.project
    assert {project.element(i).type for i in (2, 4)} == {"ForceBeamColumn"}


@pytest.mark.gui
def test_apply_without_changes_adds_nothing_to_undo(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    before = mw._vm.undo_stack.count()
    props = _select(mw, nodes=(2, 3), elements=(1, 2))
    props._multi_node_apply.click()
    props._multi_element_apply.click()
    assert mw._vm.undo_stack.count() == before
