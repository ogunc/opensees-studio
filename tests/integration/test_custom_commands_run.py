"""Custom command blocks run in the build, only when enabled, and fail by name."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from opensees_studio.child_cli import ALLOW_CUSTOM_COMMANDS_FLAG, analysis_cli_command
from opensees_studio.core import (
    CustomCommandBlock,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.opensees_script import export_script
from opensees_studio.services.persistence import save_project

pytest.importorskip("openseespy.opensees")

SPRING = """
ops.uniaxialMaterial("Elastic", tag, 400.0)
ops.element("zeroLength", tag, 1, 2, "-mat", tag, "-dir", 1)
"""


def _project(*blocks: CustomCommandBlock) -> Project:
    """Two coincident joints with nothing between them but what a custom block adds."""
    return Project(
        ndm=2,
        ndf=2,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(0.0, 0.0, 0.0), restraint=(False, False, True, False, False, False)),
        ],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(8.0, 0, 0, 0, 0, 0))],
            )
        ],
        analyses=[StaticCase(id=1, name="s", pattern_ids=[1])],
        custom_commands=list(blocks),
    )


def test_a_block_adds_a_spring_the_solver_uses() -> None:
    project = _project(CustomCommandBlock(id=1, name="spring", code=SPRING))
    disp = OpenSeesRunner(project).run(project.analyses[0]).node_disp[2][-1][0]
    assert float(disp) == pytest.approx(8.0 / 400.0)


def test_a_disabled_block_does_not_run_and_a_broken_one_names_itself() -> None:
    disabled = _project(
        CustomCommandBlock(id=1, name="off", code="raise SystemExit", enabled=False)
    )
    OpenSeesRunner(disabled).build()  # nothing raised: the block never ran
    broken = _project(CustomCommandBlock(id=1, name="typo", code="ops.nodee(1)"))
    with pytest.raises(RuntimeError, match=r"'typo'.*AttributeError"):
        OpenSeesRunner(broken).build()


def test_the_exported_script_carries_the_block_commands() -> None:
    script = export_script(_project(CustomCommandBlock(id=1, name="spring", code=SPRING)))
    assert 'ops.element("zeroLength", 1000000, 1, 2' in script.replace("'", '"')


def test_no_blocks_no_key() -> None:
    assert "custom_commands" not in _project().model_dump()


# ── A file's blocks run outside the GUI only when the caller trusts them ──
def _sentinel_project(folder: Path) -> tuple[Path, Path]:
    """A saved project whose block writes ``sentinel.txt`` beside it when it runs."""
    sentinel = folder / "sentinel.txt"
    code = SPRING + f"open({str(sentinel)!r}, 'w').write('ran')\n"
    path = folder / "blocks.osmodel"
    save_project(_project(CustomCommandBlock(id=1, name="spring", code=code)), path)
    return path, sentinel


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [*analysis_cli_command(), *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def test_the_analysis_cli_refuses_untrusted_blocks(tmp_path: Path) -> None:
    path, sentinel = _sentinel_project(tmp_path)
    out = tmp_path / "out"

    refused = _cli("--project", str(path), "--cases", "1", "--out", str(out))
    assert refused.returncode == 3, refused.stdout + refused.stderr
    assert "--allow-custom-commands" in refused.stdout
    assert not sentinel.exists()

    stability = _cli("--project", str(path), "--check-stability")
    assert stability.returncode == 3
    assert not sentinel.exists()

    trusted = _cli(
        "--project", str(path), "--cases", "1", "--out", str(out), ALLOW_CUSTOM_COMMANDS_FLAG
    )
    assert trusted.returncode == 0, trusted.stdout + trusted.stderr
    assert sentinel.read_text() == "ran"


def test_the_batch_skips_untrusted_blocks(tmp_path: Path) -> None:
    path, sentinel = _sentinel_project(tmp_path)
    batch = [sys.executable, "-m", "opensees_studio.batch", str(path), "--engine", "openseespy"]

    skipped = subprocess.run(
        [*batch, "--summary", str(tmp_path / "a")], capture_output=True, text=True, timeout=300
    )
    assert skipped.returncode == 1
    jobs = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))["jobs"]
    assert jobs[0]["status"] == "skipped"
    assert "--allow-custom-commands" in jobs[0]["message"]
    assert not sentinel.exists()

    ran = subprocess.run(
        [*batch, "--summary", str(tmp_path / "b"), ALLOW_CUSTOM_COMMANDS_FLAG],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert sentinel.read_text() == "ran"
