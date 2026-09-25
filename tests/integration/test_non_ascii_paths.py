"""OpenSees I/O under non-ASCII paths, on the real OpenSeesPy build.

OpenSees on Windows opens nothing under a path it cannot map to the ANSI
code page and reports no error, so a recorder under ``C:\\Users\\Öğünç``
used to leave an empty history. The runner now stages recorder files in
an ASCII directory and moves them with Python; a recorder that still
writes nothing fails the case with the file named.

The project and its results live in a folder named ``Deneme Öğünç``, so
these tests exercise a non-ASCII path on every platform, with pytest's
default temp directory (no ASCII temp workaround).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import h5py
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    TransientCase,
)
from opensees_studio.services import OpenSeesRunner, load_project, save_project
from opensees_studio.services.opensees_io import (
    STAGING_PREFIX,
    RecorderOutputError,
    staging_dir,
    staging_root,
)
from opensees_studio.services.result_store import load_manifest, load_results
from tests.integration._recorder_faults import DropOneRecorder

REPO = Path(__file__).resolve().parents[2]
N_STEPS = 50
FOLDER = "Deneme Öğünç"


def _sdof_project() -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, True, False, False, False, True)),
            Node(id=2, coords=(0.0, 3.0, 0.0), mass=(1000.0,) * 3 + (0.0,) * 3),
        ],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=8.333e-6)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(10.0, 0, 0, 0, 0, 0))],
            )
        ],
        analyses=[TransientCase(id=1, name="T1", pattern_ids=[1], dt=0.01, n_steps=N_STEPS)],
    )


def _saved_in_non_ascii_folder(tmp_path: Path) -> Path:
    folder = tmp_path / FOLDER
    return save_project(_sdof_project(), folder / "sdof.osmodel")


def _stages() -> set[Path]:
    return set(staging_root().glob(f"{STAGING_PREFIX}*"))


def test_transient_under_a_non_ascii_directory_has_full_results(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = _saved_in_non_ascii_folder(tmp_path)
    assert not str(path).isascii()
    project = load_project(path)
    results_dir = path.parent / "sdof_results"
    before = _stages()

    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=results_dir)

    assert results.n_steps == N_STEPS
    assert results.h5_path == results_dir / "case_1.h5"
    assert len(results.time()) == N_STEPS
    assert results.node_disp_history(2).shape == (N_STEPS, 3)
    recorders = sorted(p.name for p in (results_dir / "recorders").iterdir())
    assert recorders == [
        "elements_localForce.out",
        "nodes_accel.out",
        "nodes_disp.out",
        "nodes_vel.out",
    ]
    assert _stages() == before, "the staging directory is removed after the run"


def test_cli_child_under_a_non_ascii_directory_has_full_results(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The GUI runs analyses through this CLI, with --out next to the project."""
    path = _saved_in_non_ascii_folder(tmp_path)
    out = path.parent / "sdof_results"
    argv = ["-m", "opensees_studio.run", "--project", str(path), "--cases", "1", "--out", str(out)]
    proc = subprocess.run(
        [sys.executable, *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    entry = load_manifest(out)["cases"][0]
    assert entry["completed_steps"] == N_STEPS
    results = load_results(entry, out)
    assert results.node_disp_history(2).shape == (N_STEPS, 3)


def test_missing_recorder_output_fails_the_case_with_the_file_named(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import openseespy.opensees as ops

    project = _sdof_project()
    before = _stages()
    runner = OpenSeesRunner(project, ops_module=DropOneRecorder(ops, "nodes_disp.out"))
    with pytest.raises(RecorderOutputError, match=r"nodes_disp\.out") as exc:
        runner.run(project.analyses[0], results_dir=tmp_path / FOLDER / "results")
    assert f"after {N_STEPS} committed step(s)" in str(exc.value)
    assert not (tmp_path / FOLDER / "results" / "case_1.h5").exists()
    assert _stages() == before, "the staging directory is removed after a failure too"


def test_missing_recorder_output_is_cli_exit_2_with_an_error_line(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = _saved_in_non_ascii_folder(tmp_path)
    script = textwrap.dedent(
        f"""
        import sys

        sys.path.insert(0, {str(REPO)!r})

        import openseespy.opensees as ops

        import opensees_studio.services.opensees_runner as runner_module
        from opensees_studio import run
        from tests.integration._recorder_faults import DropOneRecorder

        class Runner(runner_module.OpenSeesRunner):
            def __init__(self, project, ops_module=None, on_progress=None):
                super().__init__(project, DropOneRecorder(ops, "elements_localForce.out"), on_progress)

        runner_module.OpenSeesRunner = Runner
        sys.exit(run.main(sys.argv[1:]))
        """
    )
    argv = ["--project", str(path), "--cases", "1", "--out", str(path.parent / "out")]
    proc = subprocess.run(
        [sys.executable, "-c", script, *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    assert proc.returncode == 2, proc.stdout[-2000:] + proc.stderr[-2000:]
    errors = [
        line
        for line in (json.loads(raw) for raw in proc.stdout.splitlines() if raw.startswith("{"))
        if line.get("type") == "error"
    ]
    assert len(errors) == 1
    assert "elements_localForce.out" in errors[0]["message"]
    assert "RecorderOutputError" in errors[0]["traceback"]


def test_large_model_keeps_every_node_and_element_history(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """260 nodes would need 1039 recorder files one per node and element, beyond
    the C runtime's ~509 open files; the grouped recorders need four."""
    n_nodes = 260
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(
                id=i,
                coords=(0.0, 0.5 * (i - 1), 0.0),
                restraint=(True,) * 6 if i == 1 else (False,) * 6,
                mass=(0.0,) * 6 if i == 1 else (10.0, 10.0, 0.0, 0.0, 0.0, 0.01),
            )
            for i in range(1, n_nodes + 1)
        ],
        sections=[ElasticSection(id=1, E=200e9, A=0.05, Iz=5.0e-3)],
        elements=[
            ElasticBeamColumn(id=i, nodes=(i, i + 1), section_id=1) for i in range(1, n_nodes)
        ],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=n_nodes, forces=(100.0, 0, 0, 0, 0, 0))],
            )
        ],
        analyses=[TransientCase(id=1, name="T1", pattern_ids=[1], dt=0.01, n_steps=10)],
    )
    results = OpenSeesRunner(project).run(
        project.analyses[0], results_dir=tmp_path / FOLDER / "tall_results"
    )
    assert results.n_steps == 10
    for nid in (1, n_nodes // 2, n_nodes):
        assert results.node_disp_history(nid).shape == (10, 3)
    assert abs(results.node_disp_history(n_nodes)[-1, 0]) > 0.0  # the tip moves
    with h5py.File(results.h5_path) as f:
        assert len(f["nodes"]) == n_nodes
        assert len(f["elements"]) == n_nodes - 1
        assert f[f"elements/{n_nodes - 1}/forces"].shape == (10, 6)


def test_stage_left_by_a_hard_exit_is_swept_by_the_next_run(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A child that dies inside OpenSees skips every cleanup; the next run removes
    the staging directory it left behind."""
    path = _saved_in_non_ascii_folder(tmp_path)
    before = _stages()
    argv = ["-m", "opensees_studio.run", "--project", str(path), "--cases", "1"]
    proc = subprocess.run(
        [sys.executable, *argv, "--out", str(path.parent / "out")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        env={**os.environ, "OPENSEES_STUDIO_CLI_HARD_EXIT_AFTER": "2"},
    )
    assert proc.returncode == 255
    left = _stages() - before
    assert len(left) == 1, "the dead child leaves exactly its own staging directory"

    with staging_dir():
        pass

    assert not any(stage.exists() for stage in left)
