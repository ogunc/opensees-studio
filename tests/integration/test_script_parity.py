"""The exported script must give the same numbers as the application.

This is the test that makes the export trustworthy. Anyone can print
``ops.element(...)`` lines; the claim being checked here is that the script the
user downloads is *the same analysis* — so it is run in a fresh interpreter
against real OpenSees and its results are compared with the runner's, exactly.

Static, modal and transient are covered, which also pins the one path the
exporter cannot record by dry-running: a transient run writes recorder files
and reads them back, so its step loop is written from the case instead
(see ``services/opensees_script.py``).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.services import load_project
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.opensees_script import export_script

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

#: Runs an exported script in a fresh interpreter and prints the probes as JSON.
#: The last line matters: OpenSees prints its own banner to stdout.
_RUN_EXPORTED = r"""
import json, runpy, sys
import openseespy.opensees as ops

script, probes = sys.argv[1], json.loads(sys.argv[2])
def _numbers(value):
    # nodeDisp returns a float for a single DOF and a list for the vector.
    if isinstance(value, (int, float)):
        return [float(value)]
    return [float(v) for v in value]


# An eigen probe reads the value of the script's OWN eigen call. Calling eigen
# again afterwards would be a second eigen call in the same process, which is a
# different analysis (that is why the CLI re-executes such cases in a fresh
# child), so the call is wrapped before the script runs.
captured = {}
if any(kind == "eigen" for kind, _ in probes.values()):
    _real_eigen = ops.eigen

    def _spy(*args, **kwargs):
        value = _real_eigen(*args, **kwargs)
        captured["eigen"] = _numbers(value)
        return value

    ops.eigen = _spy

runpy.run_path(script, run_name="__main__")

out = {}
for name, (kind, args) in probes.items():
    if kind == "nodeDisp":
        out[name] = _numbers(ops.nodeDisp(*args))
    elif kind == "eigen":
        out[name] = captured["eigen"]
    elif kind == "time":
        out[name] = [float(ops.getTime())]
    else:
        raise SystemExit(f"unknown probe {kind}")
print("PROBE_JSON " + json.dumps(out))
"""


def _run_exported(script: Path, probes: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", _RUN_EXPORTED, str(script), json.dumps(probes)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    marker = [line for line in proc.stdout.splitlines() if line.startswith("PROBE_JSON ")]
    assert marker, f"the exported script printed no probes:\n{proc.stdout[-2000:]}"
    return json.loads(marker[-1][len("PROBE_JSON ") :])


def _export(tmp_path: Path, example: str, case_id: int) -> tuple[Path, object]:
    project = load_project(EXAMPLES / f"{example}.osmodel")
    case = next(c for c in project.analyses if c.id == case_id)
    script = tmp_path / f"{example}_{case_id}.py"
    # Explicit UTF-8, as the application does: the platform default is cp1252 on
    # Windows, and a script is a downloaded artefact, not a locale-bound file.
    script.write_text(
        export_script(project, case, version="test", filename=script.name),
        encoding="utf-8",
    )
    return script, (project, case)


# ─────────────────────── static ───────────────────────
def test_static_export_reproduces_the_runner_displacements(tmp_path: Path) -> None:
    script, (project, case) = _export(tmp_path, "cantilever", 1)
    reference = OpenSeesRunner(project).run(case)

    probes = _run_exported(script, {"tip": ["nodeDisp", [6, 2]]})

    # DOF 2 is index 1 of the stored vector.
    assert probes["tip"] == [reference.node_disp[6][-1][1]]


def test_static_export_matches_every_node_and_dof(tmp_path: Path) -> None:
    """Not just the tip: every displacement the runner recorded, exactly."""
    script, (project, case) = _export(tmp_path, "portal_frame", 1)
    reference = OpenSeesRunner(project).run(case)
    ndf = len(reference.node_disp[next(iter(reference.node_disp))][0])

    probes = {f"n{node.id}": ["nodeDisp", [node.id]] for node in project.nodes}
    got = _run_exported(script, probes)

    for node in project.nodes:
        assert np.allclose(
            got[f"n{node.id}"][:ndf], reference.node_disp[node.id][-1], atol=0, rtol=0
        )


# ─────────────────────── modal ───────────────────────
def test_modal_export_reproduces_the_eigenvalues(tmp_path: Path) -> None:
    """The exported script's first eigen call is the one the GUI's dense solver makes."""
    from opensees_studio.core.modal import free_dof_count, resolve_modal_solver

    script, (project, case) = _export(tmp_path, "eigen_two_storey_one_bay_frame", 1)
    reference = OpenSeesRunner(project).run(case)
    solver, _ = resolve_modal_solver(case.solver, free_dof_count(project), case.n_modes)

    probes = _run_exported(script, {"eig": ["eigen", [f"-{solver}", case.n_modes]]})

    # The script's eigen values are the script's own run: bit-identical to the
    # GUI's, which is the point of routing both through the dense solver.
    assert probes["eig"] == list(reference.eigenvalues)


# ─────────────────────── transient ───────────────────────
@pytest.mark.slow
def test_transient_export_reproduces_the_history(tmp_path: Path) -> None:
    """The step loop the exporter writes by hand, checked against the real run."""
    script, (project, case) = _export(tmp_path, "portal_frame", 3)
    reference = OpenSeesRunner(project).run(case, results_dir=tmp_path / "ref")

    probes = _run_exported(script, {"top": ["nodeDisp", [4]], "time": ["time", []]})
    history = reference.node_disp_history(4)

    # The export records no history by design (result extraction is left out),
    # so what is compared is the state the script reaches. The time probe is
    # what proves the loop ran the case's steps: getTime() reads
    # n_steps * dt back from the solver.
    assert probes["time"][0] == pytest.approx(case.n_steps * case.dt, rel=1e-12)
    # Relative, not exact: the runner's transient history comes back through
    # OpenSees' ASCII recorder files (about seven significant digits), while the
    # exported script computes in double precision. The 1e-6 is the recorder's
    # resolution, not the model's.
    assert np.allclose(probes["top"], history[-1], rtol=1e-6, atol=0.0), (
        f"script {probes['top']} vs runner {history[-1].tolist()}"
    )
