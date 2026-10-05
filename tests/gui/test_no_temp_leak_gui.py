"""A run started from the GUI without a results folder removes the folder it made."""

from __future__ import annotations

import gc
import os
import shutil
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("openseespy.opensees")

from opensees_studio.services import load_project
from opensees_studio.services.opensees_io import fallback_staging_root, sweep_stale_stages
from opensees_studio.services.results import StaticResults, TransientResults
from opensees_studio.viewmodels import AnalysisRunner
from opensees_studio.viewmodels.analysis_runner import IN_PROCESS_ENV

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture
def system_temp(tmp_path, monkeypatch) -> Path:  # type: ignore[no-untyped-def]
    temp = tmp_path / "system-temp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    for name in ("TEMP", "TMP", "TMPDIR"):
        monkeypatch.setenv(name, str(temp))
    return temp


def _project(tmp_path: Path):  # type: ignore[no-untyped-def]
    path = tmp_path / "ex1a_canti2d.osmodel"
    shutil.copy(EXAMPLES / "ex1a_canti2d.osmodel", path)
    shutil.copytree(EXAMPLES / "data", tmp_path / "data")
    return path, load_project(path)


@pytest.mark.gui
@pytest.mark.parametrize("in_process", [False, True])
def test_runner_removes_the_folder_it_made(
    qtbot, tmp_path, system_temp, monkeypatch, in_process
) -> None:  # type: ignore[no-untyped-def]
    if in_process:
        monkeypatch.setenv(IN_PROCESS_ENV, "1")
    else:
        monkeypatch.delenv(IN_PROCESS_ENV, raising=False)
    path, project = _project(tmp_path)
    runner = AnalysisRunner()

    with qtbot.waitSignal(runner.finished, timeout=60000) as blocker:
        runner.run(project, project.analyses[0], project_path=path)
    assert isinstance(blocker.args[0], StaticResults)
    assert os.listdir(system_temp) == []  # static results are in memory

    with qtbot.waitSignal(runner.finished, timeout=60000) as blocker:
        runner.run(project, project.analyses[2], project_path=path)
    results = blocker.args[0]
    assert isinstance(results, TransientResults)
    assert results.h5_path.parent.parent == system_temp  # read lazily: kept while alive
    assert results.node_disp_history(2).shape == (1000, 3)
    del results, blocker
    gc.collect()
    assert os.listdir(system_temp) == []


@pytest.mark.gui
def test_failed_child_run_removes_the_folder_it_made(
    qtbot, tmp_path, system_temp, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv(IN_PROCESS_ENV, raising=False)
    monkeypatch.setenv("OPENSEES_STUDIO_CLI_HARD_EXIT_AFTER", "2")
    path, project = _project(tmp_path)
    runner = AnalysisRunner()
    stages = fallback_staging_root()
    sweep_stale_stages(stages)  # leftovers of earlier crashed runs
    before = sorted(os.listdir(stages)) if stages.is_dir() else []
    with qtbot.waitSignal(runner.failed, timeout=60000):
        runner.run(project, project.analyses[2], project_path=path)
    assert os.listdir(system_temp) == []
    # the dead child's staging folder (here in the fallback root: tmp_path need not be ASCII)
    assert (sorted(os.listdir(stages)) if stages.is_dir() else []) == before
