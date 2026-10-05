"""Nothing the suites run leaves a folder in the system temp directory.

Each test points the system temp directory (``tempfile`` and the TEMP, TMP and
TMPDIR variables a child process reads) at a fresh empty folder, runs a
representative piece of the unit and integration suites, and compares the listing
before and after. The fallback staging root, used when that folder is not ASCII,
must keep its listing too.
"""

from __future__ import annotations

import gc
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

import openseespy.opensees as ops

from opensees_studio.core import Hardening
from opensees_studio.services import load_project, save_project, write_run_snapshot
from opensees_studio.services.material_tester import LoadProtocol, test_uniaxial_material
from opensees_studio.services.opensees_io import (
    fallback_staging_root,
    staging_dir,
    sweep_stale_stages,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.results import TransientResults
from tests.integration._recorder_faults import DropOneRecorder

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _listing(path: Path) -> list[str]:
    return sorted(os.listdir(path)) if path.is_dir() else []


@pytest.fixture
def system_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    temp = tmp_path / "system-temp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    for name in ("TEMP", "TMP", "TMPDIR"):
        monkeypatch.setenv(name, str(temp))
    fallback = fallback_staging_root()
    sweep_stale_stages(fallback)  # leftovers of earlier crashed runs
    before = _listing(fallback)
    yield temp
    gc.collect()
    assert _listing(fallback) == before


def _example(name: str, tmp_path: Path) -> Path:
    target = tmp_path / "work" / f"{name}.osmodel"
    target.parent.mkdir(parents=True)
    shutil.copy(EXAMPLES / f"{name}.osmodel", target)
    shutil.copytree(EXAMPLES / "data", target.parent / "data")
    return target


def test_transient_run_keeps_its_own_folder_only_while_the_results_live(
    system_temp: Path, tmp_path: Path
) -> None:
    project = load_project(_example("ex1a_canti2d", tmp_path))
    case = next(c for c in project.analyses if c.id == 3)
    results = OpenSeesRunner(project).run(case)
    assert isinstance(results, TransientResults)
    assert results.h5_path.parent.parent == system_temp
    assert results.node_disp_history(2).shape == (1000, 3)
    del results
    gc.collect()
    assert _listing(system_temp) == []


def test_failed_transient_run_removes_its_folder(system_temp: Path, tmp_path: Path) -> None:
    from opensees_studio.services.opensees_io import RecorderOutputError

    project = load_project(_example("ex1a_canti2d", tmp_path))
    case = next(c for c in project.analyses if c.id == 3)
    with pytest.raises(RecorderOutputError):
        OpenSeesRunner(project, DropOneRecorder(ops, "nodes_disp.out")).run(case)
    assert _listing(system_temp) == []


def test_static_modal_and_pushover_runs_leave_nothing(system_temp: Path, tmp_path: Path) -> None:
    for name in ("cantilever", "ex1a_canti2d"):
        project = load_project(_example(name, tmp_path / name))
        for case in project.analyses:
            if case.type != "Transient":
                OpenSeesRunner(project).run(case)
    assert _listing(system_temp) == []


def test_cli_run_writes_only_its_output_folder(system_temp: Path, tmp_path: Path) -> None:
    path = _example("ex1a_canti2d", tmp_path)
    out = tmp_path / "out"
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(path),
            "--cases",
            "1",
            "3",
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert done.returncode == 0, done.stderr
    assert (out / "manifest.json").is_file()
    assert _listing(system_temp) == []


def test_save_snapshot_material_tester_and_staging_leave_nothing(
    system_temp: Path, tmp_path: Path
) -> None:
    project = load_project(_example("cantilever", tmp_path))
    save_project(project, tmp_path / "again.osmodel")
    write_run_snapshot(project, tmp_path / "again.osmodel")
    test_uniaxial_material(
        Hardening(id=1, E=29000.0, sigmaY=36.0, H_iso=0.0, H_kin=1500.0),
        LoadProtocol(kind="monotonic", max_compressive=-0.004, n_steps_per_branch=10),
    )
    with staging_dir() as stage:
        (stage / "probe.out").write_text("1\n", encoding="ascii")
    assert _listing(system_temp) == []
