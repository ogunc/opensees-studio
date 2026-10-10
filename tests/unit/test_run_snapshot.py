"""Pre-run project snapshot: atomic write, record resolution, recovery bookkeeping.

The snapshot is the crash-recovery copy written before every analysis
run. It lives next to the project file so relative record paths resolve
exactly as they do for the project, never mutates the project in memory
and never touches the user's own ``.osmodel``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from opensees_studio.core import (
    Node,
    PathTimeSeries,
    Project,
    UniformExcitationPattern,
    import_record,
)
from opensees_studio.services.persistence import (
    RUN_SNAPSHOT_SUFFIX,
    app_data_dir,
    discard_run_snapshot,
    load_project,
    newer_run_snapshot,
    run_snapshot_path,
    save_project,
    write_run_snapshot,
)

VALUES = [0.0, 0.1, -0.25, 0.3, -0.15, 0.05, -0.325, 0.2]
DT = 0.01


def _record_backed_project(tmp_path: Path) -> tuple[Project, Path]:
    record = tmp_path / "data" / "motion.txt"
    record.parent.mkdir(parents=True)
    record.write_text("\n".join(repr(v) for v in VALUES) + "\n")
    rec, values = import_record(record, base_dir=tmp_path, record_id=1, dt=DT)
    project = Project(
        ground_motions=[rec],
        time_series=[PathTimeSeries(id=1, dt=DT, values=values, record_id=1)],
        load_patterns=[UniformExcitationPattern(id=1, direction=1, accel_series_id=1)],
    )
    path = save_project(project, tmp_path / "proj.osmodel")
    return load_project(path), path


def test_snapshot_path_is_next_to_the_project_file(tmp_path: Path) -> None:
    assert run_snapshot_path(tmp_path / "frame.osmodel") == tmp_path / (
        "frame" + RUN_SNAPSHOT_SUFFIX
    )


def test_snapshot_of_a_never_saved_project_goes_to_the_app_data_dir(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OPENSEES_STUDIO_DATA_DIR", str(tmp_path / "data-dir"))
    assert app_data_dir() == tmp_path / "data-dir"
    out = write_run_snapshot(Project(), None)
    assert out == tmp_path / "data-dir" / ("untitled" + RUN_SNAPSHOT_SUFFIX)
    assert out.is_file()


def test_snapshot_is_written_atomically_and_leaves_the_project_file_alone(tmp_path: Path) -> None:
    project, path = _record_backed_project(tmp_path)
    before = path.read_bytes()
    mtime = path.stat().st_mtime_ns
    project.nodes.append(Node(id=1, coords=(1.0, 2.0, 3.0)))

    out = write_run_snapshot(project, path)

    assert out == run_snapshot_path(path)
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime
    leftovers = [f for f in tmp_path.iterdir() if f.name.endswith(".tmp")]
    assert leftovers == []
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["nodes"][0]["coords"] == [1.0, 2.0, 3.0]
    # Record values are not embedded: the snapshot resolves them like the project.
    assert "values" not in payload["time_series"][0]


def test_record_backed_series_loads_from_the_snapshot(tmp_path: Path) -> None:
    project, path = _record_backed_project(tmp_path)
    snapshot = write_run_snapshot(project, path)

    restored = load_project(snapshot)

    assert restored.ground_motions[0].status == "ok"
    assert restored.time_series[0].values == VALUES
    assert restored.time_series[0].values == project.time_series[0].values


def test_snapshot_does_not_mutate_the_project(tmp_path: Path) -> None:
    project = Project(
        ground_motions=[],
        time_series=[PathTimeSeries(id=1, dt=DT, values=VALUES)],
    )
    dumped = project.model_dump()
    write_run_snapshot(project, tmp_path / "never-saved" / "p.osmodel")
    assert project.model_dump() == dumped


def test_newer_snapshot_detection(tmp_path: Path) -> None:
    project, path = _record_backed_project(tmp_path)
    assert newer_run_snapshot(path) is None

    snapshot = write_run_snapshot(project, path)
    # Make the snapshot older than the project file: it is stale and ignored.
    old = path.stat().st_mtime - 60.0
    os.utime(snapshot, (old, old))
    assert newer_run_snapshot(path) is None

    new = path.stat().st_mtime + 60.0
    os.utime(snapshot, (new, new))
    assert newer_run_snapshot(path) == snapshot


def test_discard_snapshot(tmp_path: Path) -> None:
    project, path = _record_backed_project(tmp_path)
    assert discard_run_snapshot(path) is False
    snapshot = write_run_snapshot(project, path)
    assert discard_run_snapshot(path) is True
    assert not snapshot.exists()
    assert path.is_file()
