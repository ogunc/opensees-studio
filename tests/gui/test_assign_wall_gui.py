"""Assign → Frame → RC Wall (MVLEM): the dialog previews, the menu converts in one undo step."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog, QDialogButtonBox

from opensees_studio.core import (
    Concrete02,
    ElasticBeamColumn,
    ElasticSection,
    MVLEMElement,
    Node,
    Project,
    Steel02,
)
from opensees_studio.views.dialogs.assign_wall import AssignWallDialog


def _project(ndm: int = 2) -> Project:
    nodes = [Node(id=k + 1, coords=(0.0, 0.0, 1.5 * k)) for k in range(3)]
    nodes.append(Node(id=4, coords=(5.0, 0.0, 3.0)))
    return Project(
        ndm=ndm,
        ndf=3 if ndm == 2 else 6,
        nodes=nodes,
        materials=[
            Concrete02(
                id=1,
                fpc=-30e6,
                epsc0=-0.002,
                fpcu=-6e6,
                epsU=-0.01,
                ft=2e6,
                Ets=1e9,
                **{"lambda": 0.1},
            ),
            Steel02(id=2, Fy=420e6, E0=200e9, b=0.01),
        ],
        sections=[ElasticSection(id=1, E=30e9, A=0.2, Iz=0.01)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
            ElasticBeamColumn(id=3, nodes=(3, 4), section_id=1),
        ],
    )


@pytest.mark.gui
def test_dialog_previews_the_conversion(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = AssignWallDialog(_project(), {1, 2, 3})
    qtbot.addWidget(dialog)
    conversion = dialog.conversion()
    assert conversion is not None
    assert [e.id for e in conversion.elements] == [1, 2]
    assert conversion.skipped == [3]
    assert len(conversion.materials) == 1  # both segments are 1.5 high
    # G from the concrete's initial modulus 2 fpc / epsc0 = 30 GPa, over 2.4.
    assert dialog._shear_modulus.value() == pytest.approx(30e9 / 2.4)
    assert "2 member(s) become wall segments" in dialog._message.text()


@pytest.mark.gui
def test_dialog_refuses_a_3d_model(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = AssignWallDialog(_project(ndm=3), {1})
    qtbot.addWidget(dialog)
    assert not dialog._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    assert "2D" in dialog._message.text()


@pytest.mark.gui
def test_the_menu_converts_in_one_undo_step(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.adopt(_project())
    mw._canvas.selection.set_selection(set(), {1, 2})
    monkeypatch.setattr(AssignWallDialog, "exec", lambda self: int(QDialog.DialogCode.Accepted))
    assert mw._act_assign_wall.isEnabled()
    mw._act_assign_wall.trigger()
    project = mw._vm.project
    assert isinstance(project.elements[0], MVLEMElement)
    assert len(project.materials) == 3
    assert "became MVLEM segments" in mw._console.toPlainText()
    mw._vm.undo_stack.undo()
    assert isinstance(project.elements[0], ElasticBeamColumn)
    assert len(project.materials) == 2
