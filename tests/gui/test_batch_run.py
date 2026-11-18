"""File → Run Batch…: the dialog runs files in children and the results reopen."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("openseespy.opensees")

from PySide6.QtWidgets import QMessageBox

from opensees_studio.core import Node
from opensees_studio.services import batch, engines, load_project, save_project
from opensees_studio.viewmodels import batch_runner
from opensees_studio.views.dialogs.batch_run import BatchRunDialog
from opensees_studio.views.main_window import MainWindow

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture(autouse=True)
def _opensees_engine(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(engines, "load_settings", lambda: engines.SolverSettings())


def _copy(tmp_path: Path, *names: str) -> list[Path]:
    paths = []
    for name in names:
        target = tmp_path / f"{name}.osmodel"
        shutil.copy(EXAMPLES / f"{name}.osmodel", target)
        paths.append(target)
    return paths


def _column(dlg: BatchRunDialog, column: int) -> list[str]:
    table = dlg.table()
    return [table.item(row, column).text() for row in range(table.rowCount())]


@pytest.mark.gui
def test_the_dialog_runs_every_file_and_writes_the_summary(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = _copy(tmp_path, "cantilever", "eigen_two_storey_shear_frame")
    missing = tmp_path / "gone.osmodel"
    dlg = BatchRunDialog()
    qtbot.addWidget(dlg)
    dlg.add_paths([*paths, missing, paths[0]])
    assert len(dlg.paths()) == 3
    dlg.set_parallel_jobs(2)

    with qtbot.waitSignal(dlg.runner.finished, timeout=300_000):
        dlg.start()

    assert _column(dlg, 1) == ["Done", "Done", "Skipped"]
    assert _column(dlg, 4)[2] == "File not found."
    assert dlg.summary_paths is not None
    assert all(p.is_file() for p in dlg.summary_paths)
    for path in paths:
        assert batch.stored_results(path, load_project(path)) is not None


@pytest.mark.gui
def test_named_cases_run_only_those(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    (path,) = _copy(tmp_path, "cantilever")
    first = load_project(path).analyses[0]
    dlg = BatchRunDialog()
    qtbot.addWidget(dlg)
    dlg.add_paths([path])
    dlg.set_case_selector(first.name)

    with qtbot.waitSignal(dlg.runner.finished, timeout=300_000):
        dlg.start()

    assert _column(dlg, 1) == ["Done"]
    assert _column(dlg, 2) == [first.name]


@pytest.mark.gui
def test_cancel_stops_the_running_file_and_drops_the_queue(qtbot, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # A child that cannot finish on its own: a real solve may exit 0 before the
    # cancel reaches it (on Windows terminate() only kills after 1.5 s), and an
    # exit 0 is a finished job by design (services.batch.finish_job).
    sleeper = [sys.executable, "-c", "import time; time.sleep(120)"]
    monkeypatch.setattr(batch_runner, "analysis_cli_command", sleeper.copy)
    paths = _copy(tmp_path, "cantilever", "portal_frame")
    dlg = BatchRunDialog()
    qtbot.addWidget(dlg)
    dlg.add_paths(paths)

    with qtbot.waitSignal(dlg.runner.finished, timeout=60_000):
        with qtbot.waitSignal(dlg.runner.jobStarted, timeout=10_000):
            dlg.start()
        dlg.reject()  # refused while running
        assert dlg.runner.is_running
        assert _column(dlg, 1) == ["Running", "Queued"]
        dlg.runner.cancel()

    assert _column(dlg, 1) == ["Cancelled", "Cancelled"]
    assert batch.stored_results(paths[0], load_project(paths[0])) is None


@pytest.mark.gui
def test_opening_a_batch_solved_project_offers_its_results(qtbot, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    (path,) = _copy(tmp_path, "cantilever")
    dlg = BatchRunDialog()
    qtbot.addWidget(dlg)
    dlg.add_paths([path])
    with qtbot.waitSignal(dlg.runner.finished, timeout=300_000):
        dlg.start()

    asked: list[str] = []

    def _yes(_parent, title, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        asked.append(title)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", _yes)
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.open_project(path)

    assert asked == ["Stored results"]
    n_cases = len(load_project(path).analyses)
    assert window._case_combo.count() + len(window._report_extra) == n_cases
    assert window._latest_results is not None

    # An edited model no longer matches: nothing is offered.
    edited = load_project(path)
    edited.nodes.append(Node(id=999, coords=(50.0, 0.0, 0.0), restraint=(True,) * 6))
    save_project(edited, path)
    asked.clear()
    assert window.open_project(path)
    assert asked == []
