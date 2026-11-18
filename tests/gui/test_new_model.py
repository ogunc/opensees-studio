"""File → New Model: units and a template, as SAP2000 starts a model."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog

from opensees_studio.core import UnitSystem
from opensees_studio.views.dialogs.new_model import NewModelDialog

pytestmark = pytest.mark.gui


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    return window


def _answer(monkeypatch, key: str, units: UnitSystem, **numbers) -> None:  # type: ignore[no-untyped-def]
    def exec_(dialog: NewModelDialog) -> int:
        dialog.select_template(key)
        dialog.units_combo.setCurrentIndex(list(UnitSystem).index(units))
        for name, value in numbers.items():
            getattr(dialog, name).setValue(value)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(NewModelDialog, "exec", exec_)


def test_ctrl_n_is_new_model(qtbot) -> None:
    window = _window(qtbot)
    try:
        assert window._act_new_model.shortcut().toString() == "Ctrl+N"
        assert window._act_new.shortcut().isEmpty()
    finally:
        window._help_controller.uninstall()


def test_the_3d_frame_template_builds_the_frame_its_grid_and_units(qtbot, monkeypatch) -> None:
    window = _window(qtbot)
    try:
        _answer(
            monkeypatch,
            "frame3d",
            UnitSystem.US_FT_KIP,
            bays_x=2,
            bays_y=1,
            storeys=2,
            spacing_x=20.0,
            spacing_y=25.0,
            storey_height=12.0,
        )
        window._act_new_model.trigger()
        project = window._vm.project
        assert (project.ndm, project.ndf) == (3, 6)
        assert project.meta.units is UnitSystem.US_FT_KIP
        assert len(project.nodes) == 3 * 2 * 3
        assert len(project.elements) == 6 * 2 + (2 * 2 + 3) * 2
        (grid,) = project.coord_systems
        assert [line.ordinate for line in grid.grid.z_grid_lines] == [0.0, 12.0, 24.0]
        assert project.load_patterns, "every new model has the Dead case"
        # One undo step takes the whole frame back.
        window._vm.undo_stack.undo()
        assert window._vm.project.elements == []
        # The units are offered again next time.
        assert QSettings().value("new_model/units") == UnitSystem.US_FT_KIP.value
    finally:
        QSettings().remove("new_model/units")
        window._help_controller.uninstall()


def test_the_beam_template_is_a_2d_frame_model(qtbot, monkeypatch) -> None:
    window = _window(qtbot)
    try:
        _answer(monkeypatch, "beam", UnitSystem.SI_M_N, beam_spans=2, beam_span=4.0)
        window._act_new_model.trigger()
        project = window._vm.project
        assert (project.ndm, project.ndf) == (2, 3)
        assert [n.coords[0] for n in project.nodes] == [0.0, 4.0, 8.0]
        assert len(project.elements) == 2
        assert window._canvas.working_plane_type() == "XZ"
    finally:
        QSettings().remove("new_model/units")
        window._help_controller.uninstall()


def test_the_blank_template_and_a_cancelled_dialog(qtbot, monkeypatch) -> None:
    window = _window(qtbot)
    try:
        monkeypatch.setattr(NewModelDialog, "exec", lambda _d: QDialog.DialogCode.Rejected)
        window._act_new_model.trigger()
        assert window._vm.project is None
        _answer(monkeypatch, "blank", UnitSystem.SI_MM_N)
        window._act_new_model.trigger()
        project = window._vm.project
        assert project.nodes == [] and project.meta.units is UnitSystem.SI_MM_N
    finally:
        QSettings().remove("new_model/units")
        window._help_controller.uninstall()
