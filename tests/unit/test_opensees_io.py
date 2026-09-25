"""ASCII-safe staging for OpenSees file I/O (services.opensees_io).

OpenSees cannot open non-ASCII paths on Windows and then fails silently,
so the staging root must never be a non-ASCII path, whatever the temp
directory looks like; a missing, empty or short recorder file must be an
error; and staging directories left by dead runs are swept.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from opensees_studio.services import opensees_io
from opensees_studio.services.opensees_io import (
    OWNER_FILE,
    STAGING_PREFIX,
    UNMARKED_STAGE_GRACE_S,
    RecorderOutputError,
    check_recorder_output,
    fallback_staging_root,
    is_ascii_path,
    load_recorder_table,
    place_files,
    staging_dir,
    staging_root,
    sweep_stale_stages,
)

NON_ASCII_TEMPS = [
    "C:\\Users\\Öğünç\\AppData\\Local\\Temp",
    "/home/öğünç/tmp",
    "D:\\Deneme Öğünç\\temp",
]


@pytest.fixture
def ascii_root(monkeypatch) -> Iterator[Path]:  # type: ignore[no-untyped-def]
    """A throwaway ASCII staging root; every staging_dir() in the test uses it.

    Skips when the system temp directory itself is not ASCII (then there
    is no throwaway ASCII place to test in without touching the real
    fallback root).
    """
    base = Path(tempfile.mkdtemp(prefix="osv_stage_"))
    if not is_ascii_path(base):
        base.rmdir()
        pytest.skip("tempfile.gettempdir() is not ASCII on this machine")
    root = base / "runs"
    monkeypatch.setattr(tempfile, "tempdir", str(base))  # gettempdir() now returns base
    monkeypatch.setattr(opensees_io, "fallback_staging_root", lambda: root)
    yield base
    shutil.rmtree(base, ignore_errors=True)


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


# ─────────────────────── staging root ───────────────────────
def test_ascii_temp_dir_is_used_as_is() -> None:
    assert staging_root("C:\\Temp") == Path("C:\\Temp")
    assert staging_root("/var/tmp") == Path("/var/tmp")


@pytest.mark.parametrize("temp_dir", NON_ASCII_TEMPS)
def test_non_ascii_temp_dir_falls_back_to_an_ascii_root(temp_dir: str) -> None:
    root = staging_root(temp_dir)
    assert is_ascii_path(root)
    assert root == fallback_staging_root()


def test_default_temp_dir_is_checked_too(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(tempfile, "gettempdir", lambda: NON_ASCII_TEMPS[0])
    assert is_ascii_path(staging_root())
    assert staging_root() == fallback_staging_root()


def test_fallback_root_is_ascii_and_fixed() -> None:
    root = fallback_staging_root()
    assert is_ascii_path(root)
    assert root == fallback_staging_root()
    if os.name == "nt":
        assert root.parts[1:] == ("ProgramData", "OpenSeesStudio", "runs")
    else:
        assert root.parts[:2] == ("/", "tmp")


@pytest.mark.skipif(os.name != "nt", reason="SYSTEMDRIVE is a Windows variable")
def test_odd_system_drive_value_still_gives_an_ascii_root(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("SYSTEMDRIVE", "Ö:")
    assert fallback_staging_root() == Path("C:\\ProgramData\\OpenSeesStudio\\runs")


# ─────────────────────── staging directory ───────────────────────
def test_staging_dir_is_a_fresh_ascii_folder_removed_on_exit(ascii_root: Path) -> None:
    with staging_dir() as stage:
        assert stage.parent == ascii_root
        assert stage.is_dir()
        assert is_ascii_path(stage)
        assert stage.name.startswith(STAGING_PREFIX)
        assert (stage / OWNER_FILE).read_text() == str(os.getpid())
        (stage / "nodes_disp.out").write_text("0.1 0.0\n")
    assert not stage.exists()


def test_staging_dir_under_a_non_ascii_temp_uses_the_fallback(ascii_root: Path) -> None:
    with staging_dir(NON_ASCII_TEMPS[0]) as stage:
        assert stage.parent == ascii_root / "runs"  # created on demand
        assert is_ascii_path(stage)
    assert not stage.exists()


def test_staging_dir_is_removed_when_the_body_raises(ascii_root: Path) -> None:
    with pytest.raises(ValueError, match="boom"), staging_dir() as stage:
        raise ValueError("boom")
    assert not stage.exists()


def test_stages_of_dead_runs_are_swept(ascii_root: Path) -> None:
    dead = ascii_root / f"{STAGING_PREFIX}dead"
    dead.mkdir()
    (dead / OWNER_FILE).write_text(str(_dead_pid()))
    (dead / "nodes_disp.out").write_text("partial\n")
    alive = ascii_root / f"{STAGING_PREFIX}alive"
    alive.mkdir()
    (alive / OWNER_FILE).write_text(str(os.getpid()))
    fresh_unmarked = ascii_root / f"{STAGING_PREFIX}fresh"
    fresh_unmarked.mkdir()
    old_unmarked = ascii_root / f"{STAGING_PREFIX}old"
    old_unmarked.mkdir()
    long_ago = time.time() - 2 * UNMARKED_STAGE_GRACE_S
    os.utime(old_unmarked, (long_ago, long_ago))
    unrelated = ascii_root / "someone-elses-folder"
    unrelated.mkdir()

    with staging_dir():  # every new run sweeps first
        pass

    assert not dead.exists()
    assert not old_unmarked.exists()
    assert alive.is_dir()
    assert fresh_unmarked.is_dir()
    assert unrelated.is_dir()
    assert sweep_stale_stages(ascii_root) == []


# ─────────────────────── recorder output checks ───────────────────────
def test_complete_recorder_output_passes(tmp_path: Path) -> None:
    files = [tmp_path / "nodes_disp.out", tmp_path / "elements_localForce.out"]
    for f in files:
        f.write_text("0.01 0.5\n")
    check_recorder_output(files, steps_completed=1)


def test_missing_or_empty_recorder_file_is_named(tmp_path: Path) -> None:
    ok = tmp_path / "nodes_disp.out"
    ok.write_text("0.01 0.5\n")
    empty = tmp_path / "nodes_vel.out"
    empty.write_text("")
    missing = tmp_path / "nodes_accel.out"
    with pytest.raises(RecorderOutputError) as exc:
        check_recorder_output([ok, empty, missing], steps_completed=50)
    msg = str(exc.value)
    assert "nodes_vel.out" in msg
    assert "nodes_accel.out" in msg
    assert "nodes_disp.out" not in msg
    assert "2 of 3" in msg
    assert "50 committed step(s)" in msg


def test_long_missing_lists_are_shortened(tmp_path: Path) -> None:
    files = [tmp_path / f"f{i}.out" for i in range(1, 9)]
    with pytest.raises(RecorderOutputError, match=r"f5\.out and 3 more"):
        check_recorder_output(files, steps_completed=3)


def test_recorder_table_has_one_row_per_committed_step(tmp_path: Path) -> None:
    path = tmp_path / "nodes_disp.out"
    path.write_text("0.01 1 2\n0.02 3 4\n")
    table = load_recorder_table(path, rows=2, columns=3)
    assert np.array_equal(table, [[0.01, 1, 2], [0.02, 3, 4]])
    one_row = tmp_path / "one.out"
    one_row.write_text("0.01 1 2\n")
    assert load_recorder_table(one_row, rows=1, columns=3).shape == (1, 3)
    time_only = tmp_path / "time_only.out"
    time_only.write_text("0.01\n0.02\n")
    assert load_recorder_table(time_only, rows=2, columns=1).shape == (2, 1)


def test_short_recorder_table_is_named(tmp_path: Path) -> None:
    path = tmp_path / "nodes_vel.out"
    path.write_text("0.01 1 2\n")  # cut off after one of two steps
    with pytest.raises(RecorderOutputError, match=r"nodes_vel\.out holds 1 row\(s\) x 3"):
        load_recorder_table(path, rows=2, columns=3)


def test_ragged_recorder_table_is_named(tmp_path: Path) -> None:
    path = tmp_path / "elements_localForce.out"
    path.write_text("0.01 1 2\n0.02 3\n")  # last row cut mid-line
    with pytest.raises(RecorderOutputError, match=r"elements_localForce\.out is unreadable"):
        load_recorder_table(path, rows=2, columns=3)


# ─────────────────────── placing files ───────────────────────
def test_place_files_into_a_non_ascii_destination(tmp_path: Path) -> None:
    src_dir = tmp_path / "stage"
    src_dir.mkdir()
    a = src_dir / "nodes_disp.out"
    a.write_text("0.01 0.5\n")
    dest = tmp_path / "Deneme Öğünç" / "recorders"
    dest.mkdir(parents=True)
    (dest / "nodes_disp.out").write_text("stale\n")

    placed = place_files([a], dest)

    assert placed == [dest / "nodes_disp.out"]
    assert placed[0].read_text() == "0.01 0.5\n"
    assert sorted(p.name for p in dest.iterdir()) == ["nodes_disp.out"]  # no temp left
