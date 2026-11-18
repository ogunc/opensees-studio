"""The Calculation Memory dialog and File → Export action."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")
pytest.importorskip("openseespy")

from PySide6.QtWidgets import QDialog, QFileDialog

from opensees_studio.views.dialogs.calc_memory import CalculationMemoryDialog
from opensees_studio.views.main_window import MainWindow


def _beam_project():  # type: ignore[no-untyped-def]
    from tests.integration.test_steel_design_run import _beam

    return _beam()


def _results(project):  # type: ignore[no-untyped-def]
    from opensees_studio.services.opensees_runner import OpenSeesRunner

    return {case.id: OpenSeesRunner(project).run(case) for case in project.analyses}


@pytest.mark.gui
def test_the_dialog_defaults_to_english_html_and_all_members(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = CalculationMemoryDialog()
    qtbot.addWidget(dialog)
    assert dialog.language() == "en"
    assert dialog.format() == "html"
    assert dialog.member_filter() == "all"


@pytest.mark.gui
def test_the_action_writes_the_memory(qtbot, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    project = _beam_project()
    results = _results(project)
    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.adopt(project)
    monkeypatch.setattr(window._case_results, "current", lambda _project: results)
    monkeypatch.setattr(
        CalculationMemoryDialog, "exec", lambda self: int(QDialog.DialogCode.Accepted)
    )
    target = tmp_path / "memory.html"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    window._on_calc_memory()
    assert target.exists()
    page = target.read_text(encoding="utf-8")
    assert "Calculation Memory" in page
    assert "W18X50" in page
