"""Closely spaced mode warning of an SRSS run reaches the results panel and the log."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLabel

from opensees_studio.core import ResponseSpectrumCase
from opensees_studio.services.results import ResponseSpectrumResults
from opensees_studio.viewmodels.analysis_runner import IN_PROCESS_ENV
from opensees_studio.views.main_window import MainWindow

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture(autouse=True)
def _child_process_mode(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv(IN_PROCESS_ENV, raising=False)


def _warning_labels(window: MainWindow) -> list[str]:
    return [
        label.text()
        for label in window._results_panel.findChildren(QLabel)
        if label.objectName() == "resultWarning"
    ]


def _run(
    window: MainWindow, qtbot, case: ResponseSpectrumCase, path: Path
) -> ResponseSpectrumResults:  # type: ignore[no-untyped-def]
    with qtbot.waitSignal(window._runner.finished, timeout=60000) as blocker:
        window._runner.run(window._vm.project, case, project_path=path)
    results = blocker.args[0]
    assert isinstance(results, ResponseSpectrumResults)
    return results


@pytest.mark.gui
def test_switching_to_srss_on_space_frame_3d_shows_the_warning_after_a_run(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "space_frame_3d.osmodel"
    shutil.copy(EXAMPLES / "space_frame_3d.osmodel", path)
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.open_project(path)
    saved = next(c for c in window._vm.project.analyses if isinstance(c, ResponseSpectrumCase))
    logs: list[str] = []
    window._runner.log.connect(logs.append)

    cqc = _run(window, qtbot, saved.model_copy(update={"combination": "CQC"}), path)
    assert cqc.warnings == []
    assert _warning_labels(window) == []
    assert "CQC" in window._results_panel._title.text()
    assert any(line.startswith("Eigen solver: fullGenLapack") for line in logs)

    logs.clear()
    srss = _run(window, qtbot, saved.model_copy(update={"combination": "SRSS"}), path)
    assert len(srss.warnings) == 1
    labels = _warning_labels(window)
    assert labels and all("closely spaced modes" in text for text in labels)
    assert "modes 1 and 2 (ratio 1.000)" in labels[0]
    assert any("Warning: SRSS with closely spaced modes" in line for line in logs)
    assert "SRSS" in window._results_panel._title.text()
