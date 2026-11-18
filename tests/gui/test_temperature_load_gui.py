"""Assign → Frame → Temperature Load: the dialog, the refusals, one undoable command."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog, QMessageBox

from opensees_studio.core import ElasticBeamColumn, ElasticSection, Node, Project
from opensees_studio.core.geometry.frame_options import EndRelease, FrameReleases
from opensees_studio.views.dialogs import AssignTemperatureLoadDialog


def _project() -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(4.0, 0.0, 0.0)),
            Node(id=3, coords=(8.0, 0.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-4)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(
                id=2,
                nodes=(2, 3),
                section_id=1,
                releases=FrameReleases(j=EndRelease(released=("M3",))),
            ),
        ],
    )


@pytest.mark.gui
def test_the_dialog_hides_the_z_gradient_in_2d(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = AssignTemperatureLoadDialog(3, ndm=2)
    qtbot.addWidget(dialog)
    dialog._uniform.setValue(25.0)
    values = dialog.values()
    assert values["alpha"] == pytest.approx(1.2e-5)
    assert values["uniform"] == 25.0 and values["gradient_z"] == 0.0


@pytest.mark.gui
def test_the_action_adds_the_loads_in_one_undo_step(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.adopt(_project())
    mw._canvas.selection.set_selection(set(), {1})

    def _accept(self) -> int:  # type: ignore[no-untyped-def]
        self._uniform.setValue(30.0)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(AssignTemperatureLoadDialog, "exec", _accept)
    assert mw._act_assign_temperature_load.isEnabled()
    mw._act_assign_temperature_load.trigger()
    pattern = mw._vm.project.load_patterns[0]
    assert [(t.element_id, t.uniform) for t in pattern.temperature_loads] == [(1, 30.0)]
    mw._vm.undo_stack.undo()
    assert mw._vm.project.load_patterns == []


@pytest.mark.gui
def test_a_member_with_releases_is_refused_before_anything_changes(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.adopt(_project())
    mw._canvas.selection.set_selection(set(), {1, 2})
    warned: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kw: warned.append(args[2]) or 0)
    mw._act_assign_temperature_load.trigger()
    assert warned and "Element 2" in warned[0]
    assert mw._vm.project.load_patterns == []
