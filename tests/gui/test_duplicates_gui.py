"""Repairing duplicates: what it merges, what it refuses to touch, and undo.

The policies the command promises are pinned here — restraints combined, equal
masses kept once, differing masses added, references following the keeper,
copied loads dropped rather than doubled, and deliberate coincidences left
alone. The geometry of the *report* is pinned in ``tests/unit/test_duplicates.py``
and the effect on a real solve in ``tests/integration/test_duplicate_repair.py``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog, QMessageBox

from opensees_studio.commands import (
    AddElementsCommand,
    AddNodesCommand,
    AddSectionsCommand,
    FixDuplicatesCommand,
)
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    EqualDOFConstraint,
    ImposedSupportMotionPattern,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    UniformElementLoad,
    ZeroLengthElement,
)
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs import DuplicatesDialog


def _section(sid: int = 1, *, name: str = "S") -> ElasticSection:
    return ElasticSection(id=sid, name=name, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6)


def _vm(nodes: list[Node], elements: list, *, sections: list | None = None) -> ProjectViewModel:  # type: ignore[type-arg]
    vm = ProjectViewModel()
    vm.new_project(ndm=3, ndf=6)
    vm.apply_command(AddNodesCommand(vm, nodes))
    vm.apply_command(AddSectionsCommand(vm, sections or [_section()]))
    if elements:
        vm.apply_command(AddElementsCommand(vm, elements))
    return vm


def _beam(element_id: int, first: int, second: int, section_id: int = 1) -> ElasticBeamColumn:
    return ElasticBeamColumn(id=element_id, nodes=(first, second), section_id=section_id)


def _duplicated_cantilever() -> ProjectViewModel:
    """A cantilever whose every node was copied, so every member exists twice."""
    return _vm(
        [
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(2.0, 0.0, 0.0)),
            Node(id=3, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=4, coords=(2.0, 0.0, 0.0)),
        ],
        [_beam(1, 1, 2), _beam(2, 3, 4)],
    )


# ──────────────────────────── the repair ────────────────────────────
@pytest.mark.gui
def test_the_repair_merges_the_copies_and_removes_the_repeated_member(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _duplicated_cantilever()
    command = FixDuplicatesCommand(vm)

    vm.apply_command(command)

    assert [node.id for node in vm.project.nodes] == [1, 2]
    assert [element.id for element in vm.project.elements] == [1]
    assert vm.project.elements[0].nodes == (1, 2)
    assert command.report.removed_nodes == 2
    # Element 2 only *becomes* element 1 after its nodes merge: the report is
    # recomputed on the merged model, which is why one fix removes it.
    assert command.report.removed_elements == 1
    vm.project.validate_references()


@pytest.mark.gui
def test_the_keeper_keeps_the_union_of_the_restraints(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Releasing a support by accident produces an unstable model: never do it."""
    vm = _vm(
        [
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(False, False, True, False, False, False)),
            Node(id=2, coords=(0.0, 0.0, 0.0), restraint=(False, False, False, False, False, True)),
        ],
        [],
    )
    vm.apply_command(FixDuplicatesCommand(vm))

    restraint = vm.project.node(1).restraint
    assert restraint[2] and restraint[5]  # the two fixed DOFs, not the first one's
    assert [node.id for node in vm.project.nodes] == [1]


@pytest.mark.gui
def test_equal_masses_are_kept_once_and_different_ones_are_added(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm(
        [
            Node(id=1, coords=(0.0, 0.0, 0.0), mass=(5.0, 5.0, 0.0, 0.0, 0.0, 0.0)),
            Node(id=2, coords=(0.0, 0.0, 0.0), mass=(5.0, 5.0, 0.0, 0.0, 0.0, 0.0)),
        ],
        [],
    )
    command = FixDuplicatesCommand(vm)
    vm.apply_command(command)

    assert vm.project.node(1).mass == (5.0, 5.0, 0.0, 0.0, 0.0, 0.0)  # a copy is not 10
    assert command.report.mass_conflicts == 0

    vm = _vm(
        [
            Node(id=1, coords=(0.0, 0.0, 0.0), mass=(1.0, 1.0, 0.0, 0.0, 0.0, 0.0)),
            Node(id=2, coords=(0.0, 0.0, 0.0), mass=(2.0, 2.0, 0.0, 0.0, 0.0, 0.0)),
        ],
        [],
    )
    command = FixDuplicatesCommand(vm)
    vm.apply_command(command)

    assert vm.project.node(1).mass == (3.0, 3.0, 0.0, 0.0, 0.0, 0.0)
    assert command.report.mass_conflicts == 1


@pytest.mark.gui
def test_loads_constraints_and_imposed_motion_follow_the_keeper(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _duplicated_cantilever()
    vm.apply_command(AddNodesCommand(vm, [Node(id=5, coords=(4.0, 0.0, 0.0))]))
    vm.project.time_series.append(LinearTimeSeries(id=1))
    vm.project.load_patterns.append(
        PlainLoadPattern(
            id=1,
            time_series_id=1,
            nodal_loads=[
                NodalLoad(node_id=2, forces=(0.0, 0.0, -1.0, 0, 0, 0)),
                NodalLoad(node_id=4, forces=(0.0, 0.0, -1.0, 0, 0, 0)),  # the copy's load
                NodalLoad(node_id=5, forces=(0.0, 0.0, -7.0, 0, 0, 0)),
            ],
            element_loads=[
                UniformElementLoad(element_id=1, wy=-3.0),
                UniformElementLoad(element_id=2, wy=-3.0),  # the copy's load
                UniformElementLoad(element_id=2, wy=-5.0),  # only the copy carries this one
            ],
        )
    )
    vm.project.mp_constraints.append(
        EqualDOFConstraint(retained_node=2, constrained_node=5, dofs=(1, 2))
    )
    vm.project.load_patterns.append(
        ImposedSupportMotionPattern(id=2, direction=1, disp_series_id=1, node_ids=[4, 5])
    )
    command = FixDuplicatesCommand(vm)

    vm.apply_command(command)

    pattern = vm.project.load_patterns[0]
    assert [(load.node_id, load.forces[2]) for load in pattern.nodal_loads] == [
        (2, -1.0),
        (5, -7.0),
    ]
    assert {(load.element_id, load.wy) for load in pattern.element_loads} == {
        (1, -3.0),
        (1, -5.0),
    }
    assert command.report.dropped_copy_loads == 2  # the nodal and element copies
    assert command.report.repointed_loads == 1  # the one only the copy carried

    constraint = vm.project.mp_constraints[0]
    assert (constraint.retained_node, constraint.constrained_node) == (2, 5)
    motion = vm.project.load_patterns[1]
    assert isinstance(motion, ImposedSupportMotionPattern)
    assert motion.node_ids == [2, 5]
    vm.project.validate_references()


@pytest.mark.gui
def test_a_member_left_with_no_length_is_removed_and_reported(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm(
        [
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(0.0, 0.0, 0.0)),
        ],
        [_beam(1, 1, 2)],
    )
    command = FixDuplicatesCommand(vm)

    vm.apply_command(command)

    assert vm.project.elements == []
    assert command.report.degenerate_elements == 1
    assert "no length" in command.report.summary()
    vm.project.validate_references()


@pytest.mark.gui
def test_deliberate_coincidences_are_left_alone(qtbot) -> None:  # type: ignore[no-untyped-def]
    """An isolator is two coincident nodes; a hinge can be two tied by equalDOF."""
    vm = _vm(
        [
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(0.0, 0.0, 0.0)),
            Node(id=3, coords=(1.0, 0.0, 0.0)),
            Node(id=4, coords=(1.0, 0.0, 0.0)),
        ],
        [
            ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=(1, 2)),
            _beam(2, 3, 4),
        ],
    )
    vm.project.mp_constraints.append(
        EqualDOFConstraint(retained_node=3, constrained_node=4, dofs=(1, 2, 3))
    )
    command = FixDuplicatesCommand(vm)

    vm.apply_command(command)

    assert [node.id for node in vm.project.nodes] == [1, 2, 3, 4]
    assert [element.id for element in vm.project.elements] == [1, 2]
    assert not command.report.changed_anything
    assert command.report.summary() == "Nothing to fix: no duplicate nodes or elements."


@pytest.mark.gui
def test_undo_restores_the_model_exactly_and_redo_does_it_again(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _duplicated_cantilever()
    before = vm.project.model_dump()
    vm.apply_command(FixDuplicatesCommand(vm))

    vm.undo_stack.undo()

    assert vm.project.model_dump() == before

    vm.undo_stack.redo()

    assert [node.id for node in vm.project.nodes] == [1, 2]
    assert [element.id for element in vm.project.elements] == [1]


@pytest.mark.gui
def test_a_clean_model_is_untouched(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm(
        [Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(1.0, 0.0, 0.0))],
        [_beam(1, 1, 2)],
    )
    before = vm.project.model_dump()
    vm.apply_command(FixDuplicatesCommand(vm))

    assert vm.project.model_dump() == before


# ──────────────────────────── the dialog ────────────────────────────
def _dialog_project() -> Project:
    """One deliberate coincidence and one parallel pair — nothing to fix."""
    return Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(0.0, 0.0, 0.0)),
            Node(id=3, coords=(1.0, 0.0, 0.0)),
        ],
        sections=[_section(1, name="A"), _section(2, name="B")],
        elements=[
            ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=(1, 2)),
            _beam(2, 1, 3, section_id=1),
            _beam(3, 1, 3, section_id=2),  # same nodes, another section: parallel
        ],
    )


@pytest.mark.gui
def test_the_dialog_lists_what_is_duplicated_and_what_is_left_alone(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = DuplicatesDialog(_dialog_project())
    qtbot.addWidget(dialog)

    notes = [
        dialog._nodes_table.item(row, 3).text() for row in range(dialog._nodes_table.rowCount())
    ]
    assert any("zero-length" in note for note in notes)
    # Parallel elements (same nodes, different sections) are information only.
    assert dialog._elements_table.rowCount() >= 1
    assert "left alone" in dialog._summary.text()


@pytest.mark.gui
def test_the_dialog_rechecks_with_the_tolerance_the_user_typed(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(0.5, 0.0, 0.0)),
            Node(id=3, coords=(1.0, 0.0, 0.0)),
        ],
        sections=[_section()],
    )
    dialog = DuplicatesDialog(project)
    qtbot.addWidget(dialog)
    assert not dialog._fix_button.isEnabled()  # only the exempt group: nothing to fix

    dialog._tolerance.setValue(2.0)  # wide enough to swallow the whole model
    dialog._refresh()

    assert dialog._fix_button.isEnabled()
    assert dialog.report().duplicate_node_count >= 2


@pytest.mark.gui
def test_the_dialog_can_hand_a_row_to_the_canvas(qtbot) -> None:  # type: ignore[no-untyped-def]
    seen: list[tuple[list[int], list[int]]] = []
    dialog = DuplicatesDialog(
        _dialog_project(),
        on_select=lambda nodes, elements: seen.append((list(nodes), list(elements))),
    )
    qtbot.addWidget(dialog)
    dialog._tolerance.setValue(2.0)
    dialog._refresh()

    dialog._nodes_table.selectRow(0)
    dialog._select_current()

    assert seen and seen[0][0]  # the row's node ids reached the callback


# ──────────────────────────── through the menu ────────────────────────────
@pytest.mark.gui
def test_the_menu_action_repairs_the_model(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=3, ndf=6)
    mw._vm.apply_command(
        AddNodesCommand(
            mw._vm,
            [
                Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
                Node(id=2, coords=(2.0, 0.0, 0.0)),
                Node(id=3, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
                Node(id=4, coords=(2.0, 0.0, 0.0)),
            ],
        )
    )
    mw._vm.apply_command(AddSectionsCommand(mw._vm, [_section()]))
    mw._vm.apply_command(AddElementsCommand(mw._vm, [_beam(1, 1, 2), _beam(2, 3, 4)]))
    monkeypatch.setattr(DuplicatesDialog, "exec", lambda self: int(QDialog.DialogCode.Accepted))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.StandardButton.Ok)

    assert mw._act_check_duplicates.isEnabled()
    mw._act_check_duplicates.trigger()

    assert [node.id for node in mw._vm.project.nodes] == [1, 2]
    assert [element.id for element in mw._vm.project.elements] == [1]
    assert "Duplicates:" in mw._console.toPlainText()
    assert "merged 2 coincident node group(s)" in mw._console.toPlainText()
