"""File → Import / Export → SAP2000 Text through the menu.

The translation is pinned in ``tests/unit/test_sap2000_text.py``; here the
wiring is: Import makes the file the current, unsaved project and logs what did
not come across, Export writes a file that imports back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from opensees_studio.services.sap2000_text import import_s2k

PORTAL = Path(__file__).resolve().parents[1] / "fixtures" / "s2k" / "portal_2d.s2k"


@pytest.mark.gui
def test_import_makes_the_file_the_unsaved_project(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(PORTAL), ""))
    )

    assert mw._act_import_s2k.isEnabled()
    mw._act_import_s2k.trigger()

    project = mw._vm.project
    assert project.meta.name == "portal_2d"
    assert project.ndm == 2 and len(project.nodes) == 4 and len(project.elements) == 3
    assert mw._vm.path is None and mw._vm.is_dirty
    log = mw._console.toPlainText()
    assert "Imported portal_2d.s2k (KN, m, C → SI (m, N, kg, s, Pa))" in log
    assert "4 joint(s), 3 frame(s)" in log
    # The fixture's added mass now comes across (MY is out of plane in this 2D model).
    assert project.nodes[1].mass[0] == pytest.approx(1000.0)


@pytest.mark.gui
def test_import_asks_for_the_nonprismatic_subdivision_count(qtbot, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    text = PORTAL.read_text(encoding="utf-8-sig").replace("AnalSect=R30x50", "AnalSect=VAR")
    text = text.replace(
        "END TABLE DATA",
        'TABLE:  "FRAME SECTION PROPERTIES 01 - GENERAL"\n'
        "   SectionName=VAR   Shape=Nonprismatic\n"
        'TABLE:  "FRAME SECTION PROPERTIES 05 - NONPRISMATIC"\n'
        "   SectionName=VAR   StartSect=R30x50   EndSect=R30x50 _\n"
        "      LengthType=Relative   RelLength=1   EI33Var=Linear   EI22Var=Linear\n"
        "END TABLE DATA",
        1,
    )
    source = tmp_path / "taper.s2k"
    source.write_text(text, encoding="utf-8")
    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(source), ""))
    )
    monkeypatch.setattr(QInputDialog, "getInt", staticmethod(lambda *a, **k: (24, True)))

    mw._act_import_s2k.trigger()

    project = mw._vm.project
    assert len(project.elements) == 72  # three frames, 24 pieces each
    template = next(s for s in project.sections if s.type == "NonprismaticSection")
    assert template.subdivisions == 24
    assert "24 pieces per member" in mw._console.toPlainText()


@pytest.mark.gui
def test_a_broken_file_is_reported_and_the_project_kept(qtbot, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    before = mw._vm.project
    broken = tmp_path / "broken.s2k"
    broken.write_text("not a table\n", encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(broken), ""))
    )
    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "critical", staticmethod(lambda _p, _t, text, *a: shown.append(text))
    )

    mw._act_import_s2k.trigger()

    assert shown and "no SAP2000 table" in shown[0]
    assert mw._vm.project is before


@pytest.mark.gui
def test_export_writes_a_file_that_imports_back(qtbot, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.adopt(import_s2k(PORTAL).project)
    target = tmp_path / "out"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )

    assert mw._act_export_s2k.isEnabled()
    mw._act_export_s2k.trigger()

    written = tmp_path / "out.s2k"
    assert written.is_file()
    again = import_s2k(written).project
    assert len(again.nodes) == 4 and len(again.combinations) == 2
    assert "Exported out.s2k: Wrote 4 joint(s)" in mw._console.toPlainText()
