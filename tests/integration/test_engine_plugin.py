"""A third-party engine, registered as an entry point, solves through the real CLI.

The plug-in is a module plus a ``*.dist-info`` folder with ``entry_points.txt``
on ``PYTHONPATH``: exactly how ``pip install`` would register it, with nothing
in OpenSees Studio changed. Its runner returns a ``StaticResults`` with a
recognisable displacement, so the test sees that the CLI dispatched to it, and
a modal case (which it does not declare) is refused before anything runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    ModalCase,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
)
from opensees_studio.services.persistence import save_project
from opensees_studio.services.result_store import load_results

TOY = """
import numpy as np
from opensees_studio.services.engines import EngineStatus
from opensees_studio.services.results import StaticResults

class ToyEngine:
    key = "toy"
    name = "Toy solver"
    case_types = frozenset({"Static"})

    def status(self, settings):
        return EngineStatus(engine=self.key, name=self.name, available=True, version="1.0")

    def child_environment(self, settings):
        return {}

    def create_runner(self, project, on_progress=None):
        return ToyRunner(project)

class ToyRunner:
    def __init__(self, project):
        self.project = project

    def run(self, case, results_dir=None):
        disp = {n.id: np.full((1, self.project.ndf), 0.125) for n in self.project.nodes}
        return StaticResults(case_id=case.id, case_name=case.name, n_steps=1, node_disp=disp)
"""


def _plugin(tmp_path: Path) -> Path:
    site = tmp_path / "plugins"
    site.mkdir()
    (site / "toy_engine.py").write_text(TOY, encoding="utf-8")
    info = site / "toy_engine-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: toy-engine\nVersion: 1.0\n", encoding="utf-8"
    )
    (info / "entry_points.txt").write_text(
        "[opensees_studio.engines]\ntoy = toy_engine:ToyEngine\n", encoding="utf-8"
    )
    return site


def _project(tmp_path: Path) -> Path:
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, False, True, False, True, False)),
            Node(id=2, coords=(5.0, 0.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=8.333e-6)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(0.0, 0.0, -1.0, 0.0, 0.0, 0.0))],
            )
        ],
        analyses=[StaticCase(id=1, name="Tip", pattern_ids=[1]), ModalCase(id=2, name="Modes")],
    )
    return save_project(project, tmp_path / "toy.osmodel")


def _run(tmp_path: Path, cases: list[str]) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(_plugin(tmp_path)), os.environ.get("PYTHONPATH", "")]),
        "OPENSEES_STUDIO_ENGINE": "toy",
    }
    cmd = [sys.executable, "-m", "opensees_studio.run", "--project", str(_project(tmp_path))]
    cmd += ["--cases", *cases, "--out", str(tmp_path / "out")]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)


def test_the_cli_solves_with_a_plugin_engine(tmp_path: Path) -> None:
    proc = _run(tmp_path, ["1"])

    assert proc.returncode == 0, proc.stdout + proc.stderr
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    (entry,) = manifest["cases"]
    results = load_results(entry, tmp_path / "out")
    assert float(results.node_disp[2][0][0]) == 0.125  # the toy engine's answer


def test_a_case_the_engine_does_not_run_is_refused(tmp_path: Path) -> None:
    proc = _run(tmp_path, ["1", "2"])

    assert proc.returncode == 2
    errors = [json.loads(line) for line in proc.stdout.splitlines() if '"error"' in line]
    assert "Toy solver does not run 'Modes' (Modal)" in errors[-1]["message"]
    assert not (tmp_path / "out" / "manifest.json").exists()
