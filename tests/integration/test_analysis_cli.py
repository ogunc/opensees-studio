"""The analysis CLI as a subprocess: protocol, exit codes, manifest, hard-exit hook.

No Qt here: these tests drive ``python -m opensees_studio.run`` exactly as
the GUI's QProcess does and read what it writes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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
    StaticCase,
)
from opensees_studio.services import save_project
from opensees_studio.services.result_store import load_manifest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "opensees_studio.run", *args]
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(cmd, capture_output=True, text=True, env=full_env, timeout=300)


def _lines(proc: subprocess.CompletedProcess[str]) -> list[dict]:
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def _cantilever(tmp_path: Path, *, connected: bool = True) -> Path:
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, True, False, False, False, True)),
        Node(id=2, coords=(5.0, 0.0, 0.0)),
    ]
    if not connected:
        nodes.append(Node(id=3, coords=(9.0, 0.0, 0.0)))  # free node without any element
    project = Project(
        ndm=2,
        ndf=3,
        nodes=nodes,
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
        analyses=[StaticCase(id=1, name="Tip", pattern_ids=[1], n_steps=4)],
    )
    return save_project(project, tmp_path / "canti.osmodel")


def test_exit_0_protocol_and_manifest(tmp_path: Path) -> None:
    out = tmp_path / "out"
    proc = _run_cli(
        "--project", str(EXAMPLES / "ex1a_canti2d.osmodel"), "--cases", "1", "3", "--out", str(out)
    )

    assert proc.returncode == 0, proc.stderr[-2000:]
    lines = _lines(proc)
    types = [line["type"] for line in lines]
    assert set(types) <= {"log", "progress", "case_started", "case_finished", "error"}
    assert "error" not in types
    assert types[0] == "log" and lines[0]["message"].startswith("Building model")

    # Per case: case_started, then progress up to the total, then case_finished.
    for cid, total in ((1, 10), (3, 1000)):
        started = next(
            i
            for i, line in enumerate(lines)
            if line["type"] == "case_started" and line["case_id"] == cid
        )
        finished = next(
            i
            for i, line in enumerate(lines)
            if line["type"] == "case_finished" and line["case_id"] == cid
        )
        progress = [line for line in lines[started:finished] if line["type"] == "progress"]
        assert progress, f"no progress lines for case {cid}"
        steps = [line["step"] for line in progress]
        assert steps == sorted(steps)
        assert all(line["total"] == total for line in progress)
        assert steps[-1] == total
        assert len(progress) <= 102
    finished_ids = [line["case_id"] for line in lines if line["type"] == "case_finished"]
    assert finished_ids == [1, 3]
    static_done = next(
        line for line in lines if line["type"] == "case_finished" and line["case_id"] == 1
    )
    assert static_done["result_type"] == "StaticResults"
    assert static_done["completed_steps"] == 10
    assert static_done["early_stop"] is False

    # OpenSees native output never reaches stdout: every stdout line parsed above.
    assert "Terminating" not in proc.stdout

    manifest = load_manifest(out)
    assert manifest["schema"] == 1
    assert manifest["project"].endswith("ex1a_canti2d.osmodel")
    by_id = {c["case_id"]: c for c in manifest["cases"]}
    assert by_id[1]["files"] == ["case_1.results.h5"]
    assert by_id[3]["result_type"] == "TransientResults"
    assert by_id[3]["files"] == ["case_3.h5"]
    assert by_id[3]["completed_steps"] == 1000
    assert by_id[3]["n_steps_requested"] == 1000
    assert by_id[3]["dt"] == pytest.approx(0.02)
    for entry in manifest["cases"]:
        for name in entry["files"]:
            assert (out / name).is_file()


def test_early_stop_is_a_result_not_an_error(tmp_path: Path) -> None:
    out = tmp_path / "out"
    proc = _run_cli(
        "--project",
        str(EXAMPLES / "rc_frame_earthquake.osmodel"),
        "--cases",
        "1",
        "--out",
        str(out),
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    entry = load_manifest(out)["cases"][0]
    assert entry["result_type"] == "TransientResults"
    assert entry["early_stop"] is True
    assert entry["completed_steps"] < entry["n_steps_requested"]
    assert any("stopped early" in w for w in entry["warnings"])
    assert any(
        line["type"] == "log" and "stopped early" in line["message"] for line in _lines(proc)
    )


def test_exit_3_for_missing_project(tmp_path: Path) -> None:
    proc = _run_cli(
        "--project", str(tmp_path / "nope.osmodel"), "--cases", "1", "--out", str(tmp_path / "out")
    )
    assert proc.returncode == 3
    lines = _lines(proc)
    assert lines[-1]["type"] == "error"
    assert "not found" in lines[-1]["message"]


def test_exit_3_for_unknown_case_id(tmp_path: Path) -> None:
    path = _cantilever(tmp_path)
    proc = _run_cli("--project", str(path), "--cases", "42", "--out", str(tmp_path / "out"))
    assert proc.returncode == 3
    assert "42" in _lines(proc)[-1]["message"]


def test_exit_3_for_dangling_reference(tmp_path: Path) -> None:
    path = _cantilever(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["elements"][0]["section_id"] = 99
    path.write_text(json.dumps(payload), encoding="utf-8")
    proc = _run_cli("--project", str(path), "--cases", "1", "--out", str(tmp_path / "out"))
    assert proc.returncode == 3
    assert "99" in _lines(proc)[-1]["message"]


def test_exit_2_for_python_side_analysis_error(tmp_path: Path) -> None:
    path = _cantilever(tmp_path, connected=False)
    out = tmp_path / "out"
    proc = _run_cli("--project", str(path), "--cases", "1", "--out", str(out))
    assert proc.returncode == 2
    lines = _lines(proc)
    assert [line["type"] for line in lines if line["type"] == "case_started"] == ["case_started"]
    error = lines[-1]
    assert error["type"] == "error"
    assert "node 3" in error["message"].lower() or "3" in error["message"]
    assert "Traceback" in error["traceback"]
    assert load_manifest(out)["cases"] == []


def test_hard_exit_hook_leaves_exit_code_255(tmp_path: Path) -> None:
    out = tmp_path / "out"
    proc = _run_cli(
        "--project",
        str(EXAMPLES / "ex1a_canti2d.osmodel"),
        "--cases",
        "3",
        "--out",
        str(out),
        env={"OPENSEES_STUDIO_CLI_HARD_EXIT_AFTER": "3"},
    )
    assert proc.returncode == 255
    lines = _lines(proc)
    assert [line["type"] for line in lines if line["type"] == "progress"] == ["progress"] * 3
    assert all(line["type"] != "case_finished" for line in lines)
    assert not (out / "manifest.json").exists()


def test_case_override_replaces_the_case_for_this_run(tmp_path: Path) -> None:
    path = _cantilever(tmp_path)
    override = tmp_path / "override.json"
    case = StaticCase(id=1, name="Tip", pattern_ids=[1], n_steps=7)
    override.write_text(json.dumps([case.model_dump(mode="json", by_alias=True)]), encoding="utf-8")
    out = tmp_path / "out"
    proc = _run_cli(
        "--project", str(path), "--cases", "1", "--out", str(out), "--case-override", str(override)
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert load_manifest(out)["cases"][0]["completed_steps"] == 7
    assert json.loads(path.read_text(encoding="utf-8"))["analyses"][0]["n_steps"] == 4
