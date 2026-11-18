"""File → Import → IFC in the interface: the dialog and the menu entry.

What is read is pinned in ``tests/unit/test_ifc_import.py``; here, that the
dialog offers only the model a file has, turns off the options that do not apply
to the chosen one, and that the menu entry replaces the project and logs what it
did.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")
pytest.importorskip("ifcopenshell")

from PySide6.QtWidgets import QDialog, QFileDialog

from opensees_studio.core.units import UnitSystem
from opensees_studio.services.ifc_import import inspect_ifc
from opensees_studio.views.dialogs import IfcImportDialog
from tests.ifc_samples import analytical_portal, physical_frame


@pytest.mark.gui
def test_a_file_without_an_analysis_model_offers_only_the_physical_one(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    dialog = IfcImportDialog(inspect_ifc(physical_frame(tmp_path / "frame.ifc")))
    qtbot.addWidget(dialog)

    assert not dialog._analytical.isEnabled()
    assert dialog._physical.isChecked()
    assert dialog._bases.isEnabled()
    assert not dialog._loads.isEnabled()  # a physical model has no loads
    assert dialog.options().source == "physical"
    assert dialog.options().units is UnitSystem.SI_MM_N  # the file is in millimetres


@pytest.mark.gui
def test_the_analytical_model_is_the_default_and_the_choices_reach_the_options(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    dialog = IfcImportDialog(inspect_ifc(analytical_portal(tmp_path / "portal.ifc")))
    qtbot.addWidget(dialog)

    assert dialog._analytical.isChecked()
    assert not dialog._physical.isEnabled()
    assert not dialog._bases.isEnabled()
    dialog._units.setCurrentIndex(list(UnitSystem).index(UnitSystem.US_IN_KIP))
    dialog._shells.setChecked(False)
    options = dialog.options()
    assert (options.source, options.units, options.include_shells) == (
        "analytical",
        UnitSystem.US_IN_KIP,
        False,
    )


@pytest.mark.gui
def test_the_menu_entry_replaces_the_project_and_logs_the_import(
    qtbot, monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    path = analytical_portal(tmp_path / "portal.ifc")
    mw = MainWindow()
    qtbot.addWidget(mw)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))
    monkeypatch.setattr(IfcImportDialog, "exec", lambda self: int(QDialog.DialogCode.Accepted))
    monkeypatch.setattr(mw, "_confirm_discard_changes", lambda action: True)

    mw._act_import_ifc.trigger()

    project = mw._vm.project
    assert project is not None
    assert project.meta.units is UnitSystem.SI_MM_N
    assert len(project.elements) == 4
    log = mw._console.toPlainText()
    assert "Imported portal.ifc: From the analytical model" in log
    assert "concrete defaults" in log


@pytest.mark.gui
def test_cancelling_the_dialog_leaves_the_project_alone(qtbot, monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    path = physical_frame(tmp_path / "frame.ifc")
    mw = MainWindow()
    qtbot.addWidget(mw)
    before = mw._vm.project
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))
    monkeypatch.setattr(IfcImportDialog, "exec", lambda self: int(QDialog.DialogCode.Rejected))
    monkeypatch.setattr(mw, "_confirm_discard_changes", lambda action: True)

    mw._act_import_ifc.trigger()

    assert mw._vm.project is before
