"""Check Model → Show the motion: a mechanism is animated on the model."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog

from opensees_studio.core import ElasticBeamColumn, ElasticSection, Node, Project
from opensees_studio.core.model_check import check_model
from opensees_studio.services.deformation import motion_to_deformation
from opensees_studio.views.dialogs.model_check import ModelCheckDialog

ROLLER = (False, False, True, False, False, False)


def _rolling_beam() -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=ROLLER),
            Node(id=2, coords=(4.0, 0.0, 0.0), restraint=ROLLER),
        ],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
    )


@pytest.mark.gui
def test_show_the_motion_closes_the_dialog_with_the_mechanism(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _rolling_beam()
    dialog = ModelCheckDialog(project, pre_run=True)
    qtbot.addWidget(dialog)
    row = next(k for k, f in enumerate(dialog.report().findings) if f.code == "mechanism")
    assert not dialog._motion_button.isEnabled()
    dialog._table.selectRow(row)
    assert dialog._motion_button.isEnabled()
    dialog._motion_button.click()
    assert dialog.result() == QDialog.DialogCode.Rejected  # the run is not started
    finding = dialog.mechanism_to_show()
    assert finding is not None and finding.modes[0].kind == "rigid_translation"


def test_the_motion_draws_as_a_translation_of_both_joints() -> None:
    project = _rolling_beam()
    finding = next(f for f in check_model(project).findings if f.code == "mechanism")
    src = motion_to_deformation(project, finding.modes[0].motion)
    assert src.displacements[:, 0] == pytest.approx([0.2, 0.2])  # 5 % of the 4 m box
    assert src.displacements[:, 2] == pytest.approx([0.0, 0.0])


@pytest.mark.gui
def test_the_window_animates_the_mechanism(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.adopt(_rolling_beam())
    finding = next(f for f in check_model(window._vm.project).findings if f.code == "mechanism")
    window._show_mechanism(finding)
    assert window._post_dock is not None and window._post_dock.windowTitle() == "Mechanism"
    assert window._canvas.selection.nodes == {1, 2}
