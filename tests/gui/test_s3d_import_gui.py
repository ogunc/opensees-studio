"""Importing a PORTICO model through the dialog and the File menu.

The translation is pinned in ``tests/unit/test_s3d_import.py``; here the wiring
is: the dialog reads the file, preselects its units and the project's, shows the
factors and what will not come across, and the menu action makes the result the
current, unsaved project.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog

from opensees_studio.core import UnitSystem
from opensees_studio.views.dialogs import S3dImportDialog


def _portico(tmp_path: Path, *, units: str = "kN-m", name: str = "frame.s3d") -> Path:
    """A cantilever with one tip load, plus a degenerate area the importer cannot take."""
    free = {"ux": 0, "uy": 0, "uz": 0, "rx": 0, "ry": 0, "rz": 0}
    data = {
        "units": units,
        "mode": "3D",
        "nodes": [
            {"id": 1, "x": 0, "y": 0, "z": 0, "restraints": dict.fromkeys(free, 1)},
            {"id": 2, "x": 5, "y": 0, "z": 0, "restraints": free},
        ],
        "elements": [{"id": 1, "n1": 1, "n2": 2, "matId": 1, "secId": 1}],
        "areas": [{"id": 1, "nodes": [1, 2, 2, 1], "matId": 1, "thickness": 0.2}],
        "materials": [{"id": 1, "name": "G30", "E": 2.8e7, "G": 1.2e7, "rho": 2.5}],
        "sections": [{"id": 1, "name": "C40", "A": 0.16, "Iz": 2e-3, "Iy": 2e-3, "J": 3e-3}],
        "loadCases": [
            {
                "id": 1,
                "name": "CM",
                "type": "static",
                "selfWeight": True,
                "loads": [{"type": "nodal", "nodeId": 2, "F": [0, 0, -10, 0, 0, 0]}],
            }
        ],
    }
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.gui
def test_the_dialog_preselects_units_and_shows_the_factors(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    dialog = S3dImportDialog()
    qtbot.addWidget(dialog)
    assert not dialog._ok.isEnabled()  # nothing loaded yet

    assert dialog.load(_portico(tmp_path))

    assert dialog.source_units() == "kN-m"
    assert dialog.target_units() is UnitSystem.SI_M_N
    assert "1 force unit = 1000 N" in dialog._factors.text()
    summary = dialog._summary.text()
    assert "2 node(s), 1 member(s)" in summary
    assert "triangular or degenerate area" in summary  # what does not come across is said
    assert dialog._ok.isEnabled()


@pytest.mark.gui
def test_changing_the_project_units_rescales(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    dialog = S3dImportDialog()
    qtbot.addWidget(dialog)
    dialog.load(_portico(tmp_path))

    dialog._target.setCurrentIndex(dialog._target.findData(UnitSystem.SI_MM_N.name))

    imported = dialog.imported()
    assert imported is not None
    assert imported.project.meta.units is UnitSystem.SI_MM_N
    assert (5000.0, 0.0, 0.0) in [node.coords for node in imported.project.nodes]
    assert "1 length unit of the file = 1000 mm" in dialog._factors.text()


@pytest.mark.gui
def test_a_us_file_opens_in_kip_inches(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    dialog = S3dImportDialog()
    qtbot.addWidget(dialog)
    dialog.load(_portico(tmp_path, units="kip-in"))
    assert dialog.target_units() is UnitSystem.US_IN_KIP
    # A non-metric file's self weight is not PORTICO's: the note says so.
    assert "PORTICO multiplies by 9.80665" in dialog._notes.text()


@pytest.mark.gui
def test_a_broken_file_is_reported_in_the_dialog(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "broken.s3d"
    path.write_text("{oops", encoding="utf-8")
    dialog = S3dImportDialog()
    qtbot.addWidget(dialog)

    assert dialog.load(path) is False
    assert "not a readable PORTICO file" in dialog._summary.text()
    assert not dialog._ok.isEnabled()


@pytest.mark.gui
def test_the_menu_makes_the_import_the_unsaved_project(qtbot, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    path = _portico(tmp_path)

    real_init = S3dImportDialog.__init__

    def _init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        real_init(self, *args, **kwargs)
        assert self.load(path)

    monkeypatch.setattr(S3dImportDialog, "__init__", _init)
    monkeypatch.setattr(S3dImportDialog, "exec", lambda self: int(QDialog.DialogCode.Accepted))

    assert mw._act_import_s3d.isEnabled()
    mw._act_import_s3d.trigger()

    project = mw._vm.project
    assert project.meta.name == "frame"
    assert len(project.nodes) == 2 and len(project.elements) == 1
    assert mw._vm.path is None and mw._vm.is_dirty
    log = mw._console.toPlainText()
    assert "Imported frame.s3d (kN-m → SI (m, N, kg, s, Pa))" in log
    assert "triangular or degenerate area" in log
