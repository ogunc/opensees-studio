"""Project persistence — read/write ``.osmodel`` JSON files.

The on-disk format is the result of ``Project.model_dump(by_alias=True)``
with indented JSON. The schema is fully captured by the Pydantic models;
external schema files are intentionally avoided.

Loading routes through Pydantic validation, so a corrupt or
out-of-spec file fails loudly with a precise error message rather than
loading half-broken data.
"""

from __future__ import annotations

import json
from pathlib import Path

from opensees_studio.core import Project

PROJECT_FILE_SUFFIX = ".osmodel"


def save_project(project: Project, path: str | Path) -> Path:
    """Serialize ``project`` to disk as indented JSON.

    Args:
        project: The project to save.
        path: Destination path. The ``.osmodel`` suffix is appended if missing.

    Returns:
        The resolved path actually written.
    """
    target = Path(path)
    if target.suffix != PROJECT_FILE_SUFFIX:
        target = target.with_suffix(PROJECT_FILE_SUFFIX)
    target.parent.mkdir(parents=True, exist_ok=True)

    payload = project.model_dump(mode="json", by_alias=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def load_project(path: str | Path) -> Project:
    """Load and validate a project from disk.

    Args:
        path: Path to a ``.osmodel`` file.

    Returns:
        A fully validated :class:`Project`.

    Raises:
        FileNotFoundError: if the path does not exist.
        pydantic.ValidationError: if the file is structurally invalid.
        ValueError: re-raised from upstream invariants (ndm/ndf, duplicate ids).
    """
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"Project file not found: {src}")
    payload = json.loads(src.read_text(encoding="utf-8"))
    return Project.model_validate(payload)
