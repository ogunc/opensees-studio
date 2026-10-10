"""A real hard exit inside OpenSees reaches the caller with OpenSees' own message.

With ``OPENSEES_STUDIO_TEST_SKIP_BEARING_ORIENT=1`` the runner leaves
``-orient`` off the bearings, and OpenSees 3.8 itself terminates the
process on the zero-length (coincident-node) bearing of
``isolated_portal2d``. The CLI runs exactly as the GUI starts it
(``python -u -m opensees_studio.run``): the exit code is none of the
CLI's own codes and stderr carries the orientation message.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.run import EXIT_ANALYSIS_ERROR, EXIT_INVALID_PROJECT, EXIT_OK
from opensees_studio.services.opensees_runner import SKIP_BEARING_ORIENT_ENV

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_bearing_without_orient_crashes_opensees_and_the_message_is_captured(tmp_path) -> None:  # type: ignore[no-untyped-def]
    project = tmp_path / "isolated_portal2d.osmodel"
    shutil.copy(EXAMPLES / "isolated_portal2d.osmodel", project)
    shutil.copytree(EXAMPLES / "data", tmp_path / "data")
    cmd = [
        sys.executable,
        "-u",
        "-m",
        "opensees_studio.run",
        "--project",
        str(project),
        "--cases",
        "1",
        "--out",
        str(tmp_path / "out"),
    ]
    env = {**os.environ, SKIP_BEARING_ORIENT_ENV: "1"}
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)

    assert proc.returncode not in (EXIT_OK, EXIT_ANALYSIS_ERROR, EXIT_INVALID_PROJECT)
    assert "orientation" in proc.stderr
    assert "element: 4" in proc.stderr
    kinds = [json.loads(line)["type"] for line in proc.stdout.splitlines() if line.strip()]
    assert "case_started" in kinds
    assert "error" not in kinds and "case_finished" not in kinds  # died inside OpenSees


def test_without_the_hook_the_same_case_runs(tmp_path) -> None:  # type: ignore[no-untyped-def]
    project = tmp_path / "isolated_portal2d.osmodel"
    shutil.copy(EXAMPLES / "isolated_portal2d.osmodel", project)
    shutil.copytree(EXAMPLES / "data", tmp_path / "data")
    env = {k: v for k, v in os.environ.items() if k != SKIP_BEARING_ORIENT_ENV}
    proc = subprocess.run(
        [
            sys.executable,
            "-u",
            "-m",
            "opensees_studio.run",
            "--project",
            str(project),
            "--cases",
            "1",
            "--out",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    assert proc.returncode == EXIT_OK, proc.stderr
