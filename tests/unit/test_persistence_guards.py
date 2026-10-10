"""Guards around writing and loading ``.osmodel`` files.

Two failures are covered here:

- the user's project file must survive a write that dies halfway
  (disk full, kill), which means the save has to go through a temp file
  and a rename, like the pre-run snapshot already did;
- a file written by a *newer* build must be refused instead of loaded
  and silently rewritten one schema version down.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from opensees_studio.core import Node, Project
from opensees_studio.services import PROJECT_FILE_SUFFIX, load_project, save_project
from opensees_studio.services.persistence import SCHEMA_VERSION


def _project() -> Project:
    return Project(nodes=[Node(id=1, coords=(0.0, 0.0, 0.0))])


def _downgrade(target: Path) -> dict:
    """Return the payload of ``target`` after replacing its schema version."""
    return json.loads(target.read_text(encoding="utf-8"))


# ─────────────────────── atomic write ───────────────────────
def test_save_project_writes_the_file_and_leaves_no_temp_behind(tmp_path: Path) -> None:
    target = save_project(_project(), tmp_path / "model")

    assert target.suffix == PROJECT_FILE_SUFFIX
    assert [p.name for p in tmp_path.iterdir()] == [target.name]


def test_save_project_keeps_the_previous_file_when_the_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed save must not truncate the file the user already had."""
    target = save_project(_project(), tmp_path / "model")
    before = target.read_text(encoding="utf-8")

    def _explode(self: Path, *args: object, **kwargs: object) -> int:
        raise OSError("No space left on device")

    monkeypatch.setattr(Path, "write_text", _explode)
    with pytest.raises(OSError):
        save_project(_project(), target)

    assert target.read_text(encoding="utf-8") == before
    # The half-written temp file is cleaned up too.
    assert [p.name for p in tmp_path.iterdir()] == [target.name]


def test_save_project_overwrites_the_previous_content(tmp_path: Path) -> None:
    target = save_project(_project(), tmp_path / "model")

    grown = Project(nodes=[Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(1.0, 0.0, 0.0))])
    save_project(grown, target)

    assert len(load_project(target).nodes) == 2


# ─────────────────────── schema version guard ───────────────────────
def test_load_rejects_a_file_from_a_newer_schema(tmp_path: Path) -> None:
    target = save_project(_project(), tmp_path / "model")
    payload = _downgrade(target)
    payload["schema_version"] = SCHEMA_VERSION + 1
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="newer version"):
        load_project(target)

    # The refused file is left exactly as it was found.
    assert json.loads(target.read_text(encoding="utf-8"))["schema_version"] == SCHEMA_VERSION + 1


def test_load_accepts_the_current_schema(tmp_path: Path) -> None:
    target = save_project(_project(), tmp_path / "model")
    assert _downgrade(target)["schema_version"] == SCHEMA_VERSION
    assert load_project(target).nodes[0].id == 1


def test_load_still_accepts_a_file_without_a_schema_version(tmp_path: Path) -> None:
    """Schema 1 files had no version field; they must keep loading."""
    target = save_project(_project(), tmp_path / "model")
    payload = _downgrade(target)
    payload.pop("schema_version")
    target.write_text(json.dumps(payload), encoding="utf-8")

    assert load_project(target).nodes[0].id == 1


def test_load_ignores_a_non_integer_schema_version(tmp_path: Path) -> None:
    """A hand-edited string must not crash the guard; Pydantic judges the field."""
    target = save_project(_project(), tmp_path / "model")
    payload = _downgrade(target)
    payload["schema_version"] = "two"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_project(target)
