"""Options → Lock Model: results lock the model, and an edit asks before it unlocks."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("openseespy.opensees")

from opensees_studio.commands import AddNodesCommand, SetDesignSettingsCommand
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    UniformElementLoad,
)
from opensees_studio.core.design.settings import DesignSettings
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.views.main_window import MainWindow

pytestmark = pytest.mark.gui


def _project() -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, False, True, False, False, False)),
            Node(id=2, coords=(6.0, 0.0, 0.0), restraint=(False, False, True, False, False, False)),
        ],
        sections=[ElasticSection(id=1, E=200e9, A=5.7e-3, Iz=1.21e-4)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="DEAD",
                time_series_id=1,
                element_loads=[UniformElementLoad(element_id=1, wy=-10e3)],
            )
        ],
        analyses=[StaticCase(id=1, name="DEAD", pattern_ids=[1])],
    )


@pytest.fixture
def window(qtbot, monkeypatch):  # type: ignore[no-untyped-def]
    """A window with a solved model; ``answers`` is what the unlock box will say."""
    win = MainWindow()
    qtbot.addWidget(win)
    win._vm.adopt(_project())
    win.answers = []  # type: ignore[attr-defined]
    win.asked = 0  # type: ignore[attr-defined]

    def _answer(self: MainWindow) -> bool:
        self.asked += 1  # type: ignore[attr-defined]
        return self.answers.pop(0)  # type: ignore[attr-defined]

    monkeypatch.setattr(MainWindow, "_confirm_unlock", _answer)
    return win


def _solve(win: MainWindow) -> None:
    project = win._vm.project
    results = OpenSeesRunner(project).run(project.analyses[0])
    win._on_case_finished(results)
    win._on_analysis_finished(results)


def _add_node(win: MainWindow) -> None:
    # Fully restrained, so the model still solves with it.
    node = Node(id=9, coords=(3.0, 0.0, 1.0), restraint=(True,) * 6)
    win._vm.apply_command(AddNodesCommand(win._vm, [node]))


def test_results_lock_the_model(window: MainWindow) -> None:
    assert not window._model_locked
    assert window._lock_button.text() == "Unlocked"

    _solve(window)

    assert window._model_locked
    assert window._act_lock_model.isChecked()
    assert window._lock_button.text() == "Locked"


def test_a_refused_edit_is_taken_back_and_the_results_stay(window: MainWindow) -> None:
    _solve(window)
    window.answers = [False]  # type: ignore[attr-defined]

    _add_node(window)

    assert window.asked == 1  # type: ignore[attr-defined]
    assert [n.id for n in window._vm.project.nodes] == [1, 2]
    assert window._model_locked
    assert window._latest_results is not None


def test_an_accepted_edit_unlocks_and_discards_the_results(window: MainWindow) -> None:
    _solve(window)
    window.answers = [True]  # type: ignore[attr-defined]

    _add_node(window)

    assert [n.id for n in window._vm.project.nodes] == [1, 2, 9]
    assert not window._model_locked
    assert window._latest_results is None
    assert window._lock_button.text() == "Unlocked"
    _add_node_again = AddNodesCommand(window._vm, [Node(id=10, coords=(1.0, 0.0, 1.0))])
    window._vm.apply_command(_add_node_again)  # unlocked: nobody is asked
    assert window.asked == 1  # type: ignore[attr-defined]


def test_what_no_result_depends_on_is_not_asked_about(window: MainWindow) -> None:
    _solve(window)
    window._vm.apply_command(SetDesignSettingsCommand(window._vm, DesignSettings(method="ASD")))

    assert window.asked == 0  # type: ignore[attr-defined]
    assert window._model_locked
    assert window._latest_results is not None


def test_renaming_a_case_does_not_ask_to_unlock(window: MainWindow) -> None:
    """A name is a label: the results stay and the lock is not in the way."""
    from opensees_studio.commands import RenameAnalysisCaseCommand

    _solve(window)

    window._vm.apply_command(RenameAnalysisCaseCommand(window._vm, 1, "GRAVITY"))

    assert window.asked == 0  # type: ignore[attr-defined]
    assert window._model_locked
    assert window._latest_results is not None
    assert window._vm.project.analyses[0].name == "GRAVITY"


def test_an_undo_of_the_locked_model_asks_too(window: MainWindow) -> None:
    _add_node(window)  # before the run: part of the solved model
    _solve(window)
    window.answers = [False]  # type: ignore[attr-defined]

    window._vm.undo_stack.undo()

    assert window.asked == 1  # type: ignore[attr-defined]
    assert [n.id for n in window._vm.project.nodes] == [1, 2, 9]  # redone
    assert window._model_locked


def test_locking_by_hand_protects_a_model_without_results(window: MainWindow) -> None:
    window._act_lock_model.trigger()
    assert window._model_locked
    window.answers = [False, True]  # type: ignore[attr-defined]

    _add_node(window)
    assert [n.id for n in window._vm.project.nodes] == [1, 2]

    window._act_lock_model.trigger()  # unlock by hand
    assert not window._model_locked
    _add_node(window)
    assert [n.id for n in window._vm.project.nodes] == [1, 2, 9]


def test_another_project_starts_unlocked(window: MainWindow) -> None:
    _solve(window)
    window._vm.adopt(_project())
    assert not window._model_locked
