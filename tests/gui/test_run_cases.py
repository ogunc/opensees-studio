"""Analyze → Run All / Run Selected: the batch doors and their dialog."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.core import Project
from opensees_studio.core.analysis import StaticCase


def _project() -> Project:
    return Project(
        analyses=[
            StaticCase(id=1, name="DEAD", pattern_ids=[1]),
            StaticCase(id=2, name="LIVE", pattern_ids=[1]),
        ]
    )


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    return window


@pytest.mark.gui
def test_the_batch_actions_need_cases(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(qtbot)

    assert not window._act_run_all.isEnabled()
    assert not window._act_run_selected.isEnabled()

    window._vm.new_project()
    assert window._vm.project is not None
    window._vm.project.analyses.extend(_project().analyses)
    window._refresh_action_enablement()

    assert window._act_run_all.isEnabled()
    assert window._act_run_selected.isEnabled()


@pytest.mark.gui
def test_run_all_hands_every_case_to_the_runner(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(qtbot)
    window._vm.new_project()
    assert window._vm.project is not None
    window._vm.project.analyses.extend(_project().analyses)
    seen: list[list[int]] = []

    def _fake_run_cases(_project, cases, **_kwargs):  # type: ignore[no-untyped-def]
        seen.append([case.id for case in cases])

    window._runner.run_cases = _fake_run_cases  # type: ignore[method-assign]

    window._on_run_all_cases()

    assert seen == [[1, 2]]


@pytest.mark.gui
def test_the_dialog_reports_only_the_ticked_cases(qtbot) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    from opensees_studio.views.dialogs.run_cases import RunCasesDialog

    dialog = RunCasesDialog(_project())
    qtbot.addWidget(dialog)

    assert dialog.selected_case_ids() == [1, 2]
    dialog._list.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert dialog.selected_case_ids() == [2]


@pytest.mark.gui
def test_a_finished_case_writes_the_results_database(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The window hook: a finished case lands in <project>_results.sqlite."""
    import numpy as np

    from opensees_studio.services.results import StaticResults
    from opensees_studio.services.results_db import count_rows, read_runs

    window = _window(qtbot)
    window._vm.new_project()
    window._vm._path = tmp_path / "model.osmodel"  # never saved otherwise

    results = StaticResults(
        case_id=1,
        case_name="DEAD",
        n_steps=1,
        node_disp={1: np.zeros((1, 6)), 2: np.ones((1, 6))},
        element_forces={9: np.zeros((1, 12))},
    )

    window._on_case_finished(results)

    db = tmp_path / "model_results.sqlite"
    assert db.exists()
    assert [r["case_name"] for r in read_runs(db)] == ["DEAD"]
    assert count_rows(db, "node_disp") == 2
    assert count_rows(db, "element_forces") == 1


@pytest.mark.gui
def test_the_batch_actions_come_back_when_the_run_ends(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Regression: they stayed disabled because nothing refreshed after teardown.

    ``finished`` is emitted while the runner still reports running, and the flag
    only drops in the teardown that follows; the window must listen to
    ``runningChanged`` for the actions to light up again.
    """
    window = _window(qtbot)
    window._vm.new_project()
    assert window._vm.project is not None
    window._vm.project.analyses.extend(_project().analyses)
    window._refresh_action_enablement()
    assert window._act_run_all.isEnabled()

    window._runner._set_running(True)
    assert not window._act_run_all.isEnabled()

    window._runner._set_running(False)
    assert window._act_run_all.isEnabled()
    assert window._act_run_selected.isEnabled()
