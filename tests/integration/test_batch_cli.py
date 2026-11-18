"""The batch CLI on bundled examples: results beside each project, reloadable later."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.services import load_project
from opensees_studio.services.batch import STORED_NAME, results_dir_for, stored_results
from opensees_studio.services.result_store import load_results
from opensees_studio.services.results import ModalResults, StaticResults, TransientResults
from opensees_studio.services.results_db import count_rows, database_path, read_runs

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
BATCH = ("cantilever", "portal_frame", "eigen_two_storey_shear_frame")


def _batch(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "opensees_studio.batch", *args, "--engine", "openseespy"]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600)


@pytest.fixture
def models(tmp_path: Path) -> Path:
    folder = tmp_path / "models"
    folder.mkdir()
    for name in BATCH:
        shutil.copy(EXAMPLES / f"{name}.osmodel", folder)
    return folder


def test_a_folder_runs_in_parallel_and_every_project_keeps_its_results(
    models: Path, tmp_path: Path
) -> None:
    proc = _batch(str(models), "--jobs", "2", "--summary", str(tmp_path / "summary"))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert payload["counts"]["ok"] == len(BATCH)
    with (tmp_path / "summary.csv").open(encoding="utf-8", newline="") as fh:
        assert [row["status"] for row in csv.DictReader(fh)] == ["ok"] * len(BATCH)

    for name in BATCH:
        path = models / f"{name}.osmodel"
        project = load_project(path)
        out_dir = results_dir_for(path)
        assert (out_dir / STORED_NAME).is_file()
        runs = read_runs(database_path(path))
        assert sorted(r["case_id"] for r in runs) == sorted(c.id for c in project.analyses)
        assert count_rows(database_path(path), "node_disp") > 0 or name.startswith("eigen")

        stored = stored_results(path, project)
        assert stored is not None
        loaded = [load_results(entry, stored.out_dir) for entry in stored.entries]
        assert [r.case_id for r in loaded] == [c.id for c in project.analyses]
        assert all(isinstance(r, StaticResults | ModalResults | TransientResults) for r in loaded)


def test_cases_by_name_and_an_unreadable_file(models: Path, tmp_path: Path) -> None:
    broken = models / "broken.osmodel"
    broken.write_text("{ not a project", encoding="utf-8")
    cantilever = models / "cantilever.osmodel"
    tip = next(c for c in load_project(cantilever).analyses if c.type == "Static")

    proc = _batch(
        str(cantilever), str(broken), "--cases", tip.name, "--summary", str(tmp_path / "s")
    )

    assert proc.returncode == 1
    jobs = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))["jobs"]
    assert [j["status"] for j in jobs] == ["ok", "skipped"]
    assert jobs[0]["cases"] == [tip.name]
    assert "Cannot read the project" in jobs[1]["message"]
    assert [r["case_id"] for r in read_runs(database_path(cantilever))] == [tip.id]
    assert not database_path(broken).exists()
