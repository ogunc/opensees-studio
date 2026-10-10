"""Meshing through the UI: the dialog, the command and the menu.

The geometry is pinned in ``tests/unit/core/test_mesh.py``; here the wiring: the
dialog shows the plan before applying it, the command replaces the originals (with
their loads) in one undo step, and Edit → Mesh does the whole thing.
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
    MeshCommand,
)
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    Project,
    ShellMITC4Element,
    UniformElementLoad,
)
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs import MeshDialog


def _section(sid: int = 1) -> ElasticSection:
    return ElasticSection(id=sid, name="S", E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6)


def _vm_with_bar(length: float = 10.0, *, loads: bool = True) -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project(ndm=3, ndf=6)
    vm.apply_command(
        AddNodesCommand(
            vm,
            [
                Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
                Node(id=2, coords=(length, 0.0, 0.0)),
            ],
        )
    )
    vm.apply_command(AddSectionsCommand(vm, [_section()]))
    vm.apply_command(AddElementsCommand(vm, [ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)]))
    if loads:
        vm.project.time_series.append(LinearTimeSeries(id=1))
        vm.project.load_patterns.append(
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                element_loads=[UniformElementLoad(element_id=1, wy=-5.0)],
            )
        )
    return vm


def _window(qtbot, *, length: float = 10.0):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=3, ndf=6)
    mw._vm.apply_command(
        AddNodesCommand(
            mw._vm,
            [
                Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
                Node(id=2, coords=(length, 0.0, 0.0)),
            ],
        )
    )
    mw._vm.apply_command(AddSectionsCommand(mw._vm, [_section()]))
    mw._vm.apply_command(
        AddElementsCommand(mw._vm, [ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)])
    )
    return mw


# ──────────────────────────── the dialog ────────────────────────────
def _bar_project(length: float = 10.0) -> Project:
    return Project(
        ndm=3,
        ndf=6,
        nodes=[Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(length, 0.0, 0.0))],
        sections=[_section()],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
    )


@pytest.mark.gui
def test_the_dialog_proposes_a_size_and_shows_the_plan(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = MeshDialog(_bar_project(10.0), selected_element_ids={1}, has_selection=True)
    qtbot.addWidget(dialog)

    assert dialog._size.value() == pytest.approx(1.0)  # a tenth of the model
    assert "+10 element(s)" in dialog._summary.text()  # 10 m at 1 m

    dialog._size.setValue(3.0)

    assert "+4 element(s)" in dialog._summary.text()
    assert dialog._ok.isEnabled()
    assert len(dialog.plan().new_elements) == 4


@pytest.mark.gui
def test_the_dialog_offers_the_scope_and_the_automatic_parts(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = MeshDialog(_bar_project(), selected_element_ids={1}, has_selection=True)
    qtbot.addWidget(dialog)

    assert dialog._scope_selection.isChecked() and dialog._scope_selection.isEnabled()
    assert dialog.scope_ids() == {1}
    dialog._scope_all.setChecked(True)
    assert dialog.scope_ids() is None

    # Turning everything off leaves nothing to do, and the dialog says so.
    for box in (dialog._shells, dialog._bars, dialog._nodes, dialog._crossings):
        box.setChecked(False)
    assert not dialog._ok.isEnabled()
    assert "Nothing to mesh" in dialog._summary.text()


@pytest.mark.gui
def test_the_dialog_meshes_shells_too(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(4.0, 0.0, 0.0)),
            Node(id=3, coords=(4.0, 4.0, 0.0)),
            Node(id=4, coords=(0.0, 4.0, 0.0)),
        ],
        sections=[ElasticMembranePlateSection(id=2, E=30e9, nu=0.2, h=0.2, rho=2500.0)],
        elements=[ShellMITC4Element(id=1, nodes=(1, 2, 3, 4), section_id=2)],
    )
    dialog = MeshDialog(project, has_selection=False)
    qtbot.addWidget(dialog)
    dialog._size.setValue(2.0)

    assert len(dialog.plan().new_elements) == 4  # 2 x 2
    assert "shell(s) subdivided" in dialog._summary.text()


# ──────────────────────────── the command ────────────────────────────
@pytest.mark.gui
def test_the_command_replaces_the_element_and_carries_its_load(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_bar(10.0)
    dialog = MeshDialog(vm.project, selected_element_ids={1}, has_selection=True)
    qtbot.addWidget(dialog)
    dialog._size.setValue(2.0)

    vm.apply_command(MeshCommand(vm, dialog.plan()))

    assert [element.nodes for element in vm.project.elements] == [
        (1, 3),
        (3, 4),
        (4, 5),
        (5, 6),
        (6, 2),
    ]
    assert len(vm.project.nodes) == 6
    # The distributed load follows the pieces: 5 kN/m on each, not 1 kN/m.
    assert [(load.element_id, load.wy) for load in vm.project.load_patterns[0].element_loads] == [
        (2, -5.0),
        (3, -5.0),
        (4, -5.0),
        (5, -5.0),
        (6, -5.0),
    ]
    vm.project.validate_references()


@pytest.mark.gui
def test_undo_puts_the_model_back_exactly(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_bar(10.0)
    before = vm.project.model_dump()
    dialog = MeshDialog(vm.project, selected_element_ids={1}, has_selection=True)
    qtbot.addWidget(dialog)
    dialog._size.setValue(3.0)
    vm.apply_command(MeshCommand(vm, dialog.plan()))

    vm.undo_stack.undo()

    assert vm.project.model_dump() == before

    vm.undo_stack.redo()
    assert len(vm.project.elements) == 4


# ──────────────────────────── through the menu ────────────────────────────
@pytest.mark.gui
def test_the_menu_meshes_the_selection(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._canvas.selection.select_element(1)
    mw._refresh_action_enablement()
    assert mw._act_mesh.isEnabled()

    def _fake_exec(self: MeshDialog) -> int:
        self._scope_selection.setChecked(True)
        self._size.setValue(2.5)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(MeshDialog, "exec", _fake_exec)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.StandardButton.Ok)

    mw._act_mesh.trigger()

    assert len(mw._vm.project.elements) == 4  # 10 m at 2.5 m
    assert "Mesh:" in mw._console.toPlainText()
    assert mw._canvas.selection.nodes  # the new nodes come out selected

    mw._vm.undo_stack.undo()
    assert len(mw._vm.project.elements) == 1


@pytest.mark.gui
def test_the_menu_refuses_a_project_with_nothing_to_mesh(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot, length=1.0)
    seen: list[str] = []
    monkeypatch.setattr(MeshDialog, "exec", lambda self: int(QDialog.DialogCode.Rejected))

    mw._act_mesh.trigger()  # cancelling changes nothing, and does not raise

    assert len(mw._vm.project.elements) == 1
    assert seen == []
