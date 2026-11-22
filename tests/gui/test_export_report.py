"""File → Export → Report: HTML or PDF, with the results the session has for the model."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QFileDialog

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture(autouse=True)
def _report_dialog_accepts(monkeypatch):  # type: ignore[no-untyped-def]
    """The options dialog opens with the defaults and OK is pressed."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QDialog

    from opensees_studio.views.dialogs.report_options import ReportOptionsDialog

    QSettings().remove("report")
    monkeypatch.setattr(ReportOptionsDialog, "exec", lambda self: QDialog.DialogCode.Accepted.value)
    yield
    QSettings().remove("report")


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
        assert "Model</a></h2>" in page and "No results for the model" in page
        assert '<div class="cover">' in page and "Contents</h2>" in page
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


@pytest.mark.gui
def test_export_report_leaves_out_what_the_dialog_unchecks(  # type: ignore[no-untyped-def]
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QDialog

    from opensees_studio.views.dialogs.report_options import ReportOptionsDialog, load_options

    def run(self):  # type: ignore[no-untyped-def]
        self.set_checked("materials", False)
        self._cover.setChecked(False)
        return QDialog.DialogCode.Accepted.value

    monkeypatch.setattr(ReportOptionsDialog, "exec", run)
    mw = _window(qtbot)
    target = tmp_path / "r.html"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "HTML page (*.html)")),
    )
    mw._on_export_report()
    page = target.read_text(encoding="utf-8")
    assert "Materials</a></h2>" not in page and "Sections</a></h2>" in page
    assert '<div class="cover">' not in page
    remembered = load_options(QSettings())
    assert "materials" in remembered.excluded and not remembered.cover


@pytest.mark.gui
def test_cancelling_the_options_writes_nothing(qtbot, monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QDialog

    from opensees_studio.views.dialogs.report_options import ReportOptionsDialog

    monkeypatch.setattr(ReportOptionsDialog, "exec", lambda self: QDialog.DialogCode.Rejected.value)
    asked: list[object] = []
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: asked.append(a) or ("", ""))
    )
    _window(qtbot)._on_export_report()
    assert asked == []
