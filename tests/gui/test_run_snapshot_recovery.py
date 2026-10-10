"""Crash recovery: snapshot before every run, restore or discard on open."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("openseespy.opensees")

from opensees_studio.commands import AddNodesCommand
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
)
from opensees_studio.services import load_project, run_snapshot_path, save_project
from opensees_studio.viewmodels import AnalysisRunner, ProjectViewModel
from opensees_studio.views.main_window import MainWindow


def _cantilever() -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, True, False, False, False, True)),
            Node(id=2, coords=(5.0, 0.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=8.333e-6)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(0.0, -1000.0, 0.0, 0.0, 0.0, 0.0))],
            )
        ],
        analyses=[StaticCase(id=1, name="Tip", pattern_ids=[1])],
    )


def _saved_project(tmp_path: Path) -> Path:
    return save_project(_cantilever(), tmp_path / "frame.osmodel")


def _make_newer(snapshot: Path, project_path: Path) -> None:
    later = project_path.stat().st_mtime + 60.0
    os.utime(snapshot, (later, later))


@pytest.mark.gui
def test_snapshot_is_written_before_the_run_starts(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = _saved_project(tmp_path)
    vm = ProjectViewModel()
    vm.open(path)
    # A fully restrained extra node: an unsaved change that keeps the model solvable.
    vm.apply_command(
        AddNodesCommand(vm, [Node(id=3, coords=(9.0, 0.0, 0.0), restraint=(True,) * 6)])
    )
    snapshot = run_snapshot_path(path)
    assert not snapshot.exists()

    runner = AnalysisRunner()
    with qtbot.waitSignal(runner.finished, timeout=10000):
        runner.run(vm.project, vm.project.analyses[0], project_path=path)
        # run() returns before the worker thread starts: the snapshot is already there.
        assert snapshot.is_file()

    assert [n.id for n in load_project(snapshot).nodes] == [1, 2, 3]
    assert [n.id for n in load_project(path).nodes] == [1, 2]


@pytest.mark.gui
def test_open_offers_restore_and_restore_loads_unsaved_changes(
    qtbot, tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    path = _saved_project(tmp_path)
    changed = _cantilever()
    changed.nodes.append(Node(id=3, coords=(9.0, 0.0, 0.0)))
    vm = ProjectViewModel()
    vm._project = changed  # type: ignore[attr-defined]
    vm._path = path  # type: ignore[attr-defined]
    snapshot = vm.write_run_snapshot()
    _make_newer(snapshot, path)
    file_bytes = path.read_bytes()

    window = MainWindow()
    qtbot.addWidget(window)
    asked: list[Path] = []
    monkeypatch.setattr(window, "_ask_restore_snapshot", lambda p: asked.append(p) or True)

    assert window.open_project(path)

    assert asked == [snapshot]
    assert [n.id for n in window._vm.project.nodes] == [1, 2, 3]
    assert window._vm.path == path
    assert window._vm.is_dirty
    assert path.read_bytes() == file_bytes
    assert snapshot.is_file()  # kept until the user saves or closes normally

    # A normal save writes the recovered state and retires the snapshot.
    window._vm.save()
    assert not snapshot.exists()
    assert [n.id for n in load_project(path).nodes] == [1, 2, 3]


@pytest.mark.gui
def test_open_discard_deletes_the_snapshot_and_keeps_the_file(qtbot, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    path = _saved_project(tmp_path)
    changed = _cantilever()
    changed.nodes.append(Node(id=3, coords=(9.0, 0.0, 0.0)))
    vm = ProjectViewModel()
    vm._project = changed  # type: ignore[attr-defined]
    vm._path = path  # type: ignore[attr-defined]
    snapshot = vm.write_run_snapshot()
    _make_newer(snapshot, path)
    file_bytes = path.read_bytes()

    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "_ask_restore_snapshot", lambda p: False)

    assert window.open_project(path)

    assert not snapshot.exists()
    assert [n.id for n in window._vm.project.nodes] == [1, 2]
    assert not window._vm.is_dirty
    assert path.read_bytes() == file_bytes


@pytest.mark.gui
def test_open_without_a_newer_snapshot_does_not_ask(qtbot, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    path = _saved_project(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(
        window, "_ask_restore_snapshot", lambda p: pytest.fail("prompt shown without snapshot")
    )
    assert window.open_project(path)
    assert [n.id for n in window._vm.project.nodes] == [1, 2]


@pytest.mark.gui
def test_normal_close_removes_the_snapshot(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = _saved_project(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.open_project(path)
    snapshot = window._vm.write_run_snapshot()
    assert snapshot.is_file()

    window.close()

    assert not snapshot.exists()
    assert path.is_file()
