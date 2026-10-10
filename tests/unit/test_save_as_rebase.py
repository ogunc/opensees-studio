"""Save As rebases relative record paths to the new project folder."""

from __future__ import annotations

import ntpath
import posixpath
import shutil
from pathlib import Path

from opensees_studio.core import PathTimeSeries, Project, import_record
from opensees_studio.core.ground_motion import rebase_record_path
from opensees_studio.services import load_project, save_project

VALUES = [0.0, 0.01, -0.02, 0.015, -0.005, 0.0]


def _record_backed_project(project_dir: Path) -> Path:
    """A project in ``project_dir`` whose record lives in ``project_dir/data``."""
    data = project_dir / "data"
    data.mkdir(parents=True)
    record_file = data / "quake.txt"
    record_file.write_text("\n".join(repr(v) for v in VALUES) + "\n", encoding="ascii")
    record, values = import_record(
        record_file, project_dir, 1, format="single_column", dt=0.01, accel_units="g"
    )
    project = Project(
        ndm=2,
        ndf=3,
        ground_motions=[record],
        time_series=[PathTimeSeries(id=1, dt=0.01, values=values, record_id=1)],
    )
    return save_project(project, project_dir / "model.osmodel")


def _save_as(src: Path, dest: Path) -> Project:
    """Open ``src``, save it to ``dest`` the way File > Save As does, reopen ``dest``."""
    project = load_project(src)
    save_project(project, dest, previous_path=src)
    return load_project(dest)


# ── the path function ─────────────────────────────────────────────
def test_rebase_to_sibling_subfolder_and_parent_posix() -> None:
    old = "/work/proj"
    assert rebase_record_path("data/a.txt", old, "/work/other", pathmod=posixpath) == (
        "../proj/data/a.txt"
    )
    assert rebase_record_path("data/a.txt", old, "/work/proj/v2", pathmod=posixpath) == (
        "../data/a.txt"
    )
    assert rebase_record_path("data/a.txt", old, "/work", pathmod=posixpath) == "proj/data/a.txt"


def test_rebase_on_the_same_windows_drive_is_relative_with_forward_slashes() -> None:
    assert rebase_record_path(
        "data/a.txt", "C:\\work\\proj", "C:\\work\\other", pathmod=ntpath
    ) == ("../proj/data/a.txt")


def test_rebase_to_another_windows_drive_stores_the_absolute_path() -> None:
    # ntpath.relpath raises ValueError across drives: the absolute path is kept.
    assert rebase_record_path("data/a.txt", "C:\\work\\proj", "D:\\new", pathmod=ntpath) == (
        "C:/work/proj/data/a.txt"
    )


def test_rebase_keeps_an_absolute_source_pointing_at_the_same_file() -> None:
    assert rebase_record_path("/rec/a.txt", "/work/proj", "/work/other", pathmod=posixpath) == (
        "../../rec/a.txt"
    )


# ── Save As through save_project ──────────────────────────────────
def test_save_as_to_a_subfolder_reopens_with_the_record(tmp_path: Path) -> None:
    src = _record_backed_project(tmp_path / "proj")
    before = load_project(src).ground_motions[0].content_hash

    reopened = _save_as(src, tmp_path / "proj" / "v2" / "model.osmodel")

    rec = reopened.ground_motions[0]
    assert rec.source_path == "../data/quake.txt"
    assert rec.status == "ok"
    assert rec.content_hash == before
    assert reopened.time_series[0].values == VALUES


def test_save_as_to_a_parent_folder_reopens_with_the_record(tmp_path: Path) -> None:
    src = _record_backed_project(tmp_path / "work" / "proj")

    reopened = _save_as(src, tmp_path / "work" / "model.osmodel")

    rec = reopened.ground_motions[0]
    assert rec.source_path == "proj/data/quake.txt"
    assert rec.status == "ok"
    assert reopened.time_series[0].values == VALUES


def test_save_to_the_same_folder_leaves_paths_byte_identical(tmp_path: Path) -> None:
    src = _record_backed_project(tmp_path / "proj")
    original = src.read_bytes()

    project = load_project(src)
    save_project(project, src, previous_path=src)
    assert src.read_bytes() == original

    renamed = save_project(
        load_project(src), tmp_path / "proj" / "renamed.osmodel", previous_path=src
    )
    assert load_project(renamed).ground_motions[0].source_path == "data/quake.txt"


def test_missing_record_stays_missing_but_is_rebased_so_it_can_be_found_again(
    tmp_path: Path,
) -> None:
    src = _record_backed_project(tmp_path / "proj")
    record_file = tmp_path / "proj" / "data" / "quake.txt"
    stash = tmp_path / "stash.txt"
    shutil.move(record_file, stash)

    project = load_project(src)
    assert project.ground_motions[0].status == "missing"
    dest = tmp_path / "other" / "model.osmodel"
    save_project(project, dest, previous_path=src)

    reopened = load_project(dest)
    assert reopened.ground_motions[0].source_path == "../proj/data/quake.txt"
    assert reopened.ground_motions[0].status == "missing"

    # The file comes back where the project always pointed: the rebased path finds it.
    shutil.move(stash, record_file)
    healed = load_project(dest)
    assert healed.ground_motions[0].status == "ok"
    assert healed.time_series[0].values == VALUES
