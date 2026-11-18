"""Assign → Frame → Pile Soil Springs: preview, then one undo step."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.core import ElasticBeamColumn, ElasticSection, Node, Project


def _pile() -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=[Node(id=k + 1, coords=(0.0, 0.0, -1.0 * k)) for k in range(6)],
        sections=[ElasticSection(id=1, E=30e9, A=0.28, Iz=6.4e-3, Iy=6.4e-3, G=12e9, J=1e-2)],
        elements=[
            ElasticBeamColumn(id=k + 1, nodes=(k + 1, k + 2), section_id=1) for k in range(5)
        ],
    )


@pytest.mark.gui
def test_the_dialog_previews_and_the_window_adds_in_one_step(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QDialog

    from opensees_studio.views.dialogs.pile_springs import PileSpringsDialog
    from opensees_studio.views.main_window import MainWindow

    dialog = PileSpringsDialog(_pile(), {1, 2, 3, 4, 5})
    qtbot.addWidget(dialog)
    springs = dialog.springs()
    assert springs is not None and len(springs.nodes) == 6
    assert "zero-length spring" in dialog._message.text()

    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.adopt(_pile())
    for eid in range(1, 6):
        window._canvas.selection.select_element(eid, additive=True)
    monkeypatch.setattr(PileSpringsDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    window._on_assign_pile_springs()
    project = window._vm.project
    assert len(project.nodes) == 12 and any(m.type == "QzSimple1" for m in project.materials)
    window._vm.undo_stack.undo()
    assert len(window._vm.project.nodes) == 6 and not window._vm.project.materials
