"""File → Export → Report: HTML or PDF, with the results the session has for the model."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QFileDialog

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.open(EXAMPLES / "cantilever.osmodel")
    return mw


@pytest.mark.gui
@pytest.mark.parametrize(
    ("name", "chosen"), [("r.html", "HTML page (*.html)"), ("r", "PDF (*.pdf)")]
)
def test_export_report(qtbot, monkeypatch, tmp_path: Path, name: str, chosen: str) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    assert mw._act_export_report.isEnabled()
    target = tmp_path / name
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), chosen))
    )
    mw._on_export_report()
    if name.endswith(".html"):
        page = target.read_text(encoding="utf-8")
        assert "<h2>Model</h2>" in page and "No results for the model" in page
    else:
        pdf = target.with_suffix(".pdf")
        assert pdf.read_bytes().startswith(b"%PDF")


@pytest.mark.gui
def test_the_report_keeps_modal_results_until_the_model_changes(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.services.results import ModalResults

    mw = _window(qtbot)
    modal = ModalResults(case_id=7, case_name="Modal", eigenvalues=[4.0])
    mw._on_case_finished(modal)
    assert mw.report_results() == [modal]
    project = mw._vm.project
    project.nodes[0].coords = (1.0, 2.0, 3.0)
    assert mw.report_results() == []
