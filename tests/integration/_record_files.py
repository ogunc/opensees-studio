"""Shared helper: make catalogued record files travel with a saved project.

Ground-motion records are referenced by path relative to the project
file, so a project saved into ``tmp_path`` finds its records only if
they are copied along - exactly like a user moving a project together
with its record files. Tests that save an example-built project to a
temporary directory call this before reloading it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from opensees_studio.core import Project

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


def copy_record_files(project: Project, dest_dir: Path, source_dir: Path = EXAMPLES_DIR) -> None:
    """Copy every catalogued record file of ``project`` under ``dest_dir``."""
    for record in project.ground_motions:
        src = source_dir / record.source_path
        dst = dest_dir / record.source_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
