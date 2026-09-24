"""CLI results match in-process results, array by array.

Each example case below runs twice: with ``OpenSeesRunner`` called
directly and through ``python -m opensees_studio.run`` in a child. The
result objects rebuilt from the child's output directory must equal the
direct ones. The transport is float64 HDF5, so the comparison is exact
(a tolerance of zero), which also proves that OpenSees itself is
deterministic across processes for these models.

Modal and response-spectrum references run in a fresh interpreter rather
than in the pytest process: ARPACK keeps its random start vector across
``eigen`` calls, so only the first eigen call of a process is
reproducible. A second ARPACK call in the same process flips signs of
distinct modes, rotates the basis of a repeated eigenvalue pair
(space_frame_3d) and moves the SRSS combination with it. The routing in
``core.modal`` solves models at or below 500 free DOF with the dense
solver (bit-identical on every call) and the CLI runs every later ARPACK
case in a fresh process; the multi-case tests at the end prove both.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.services import load_project
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.result_store import load_manifest, load_results
from opensees_studio.services.results import (
    ModalResults,
    PushoverResults,
    ResponseSpectrumResults,
    StaticResults,
    TransientResults,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

CASES = [
    ("cantilever", 1, StaticResults),
    ("rc_frame_gravity", 1, StaticResults),
    ("space_frame_3d", 1, StaticResults),
    ("cantilever", 3, ModalResults),
    ("eigen_two_storey_shear_frame", 1, ModalResults),
    ("space_frame_3d", 2, ModalResults),
    ("ex1a_canti2d", 2, PushoverResults),
    ("rc_frame_pushover", 1, PushoverResults),
    ("moment_curvature", 1, PushoverResults),
    ("ex1a_canti2d", 3, TransientResults),
    ("rc_frame_earthquake", 1, TransientResults),
    ("isolated_portal2d_fp", 2, TransientResults),
    ("space_frame_3d", 4, ResponseSpectrumResults),
]


def _max_diff(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    assert a.shape == b.shape, (a.shape, b.shape)
    if a.size == 0:
        return 0.0
    return float(np.max(np.abs(a - b)))


def _dict_diff(a: dict[int, np.ndarray], b: dict[int, np.ndarray]) -> float:
    assert list(a) == list(b), (list(a), list(b))
    return max((_max_diff(a[k], b[k]) for k in a), default=0.0)


def compare(inproc, cli) -> float:  # type: ignore[no-untyped-def]
    """Return the largest absolute difference over every array of the two results."""
    assert type(inproc) is type(cli)
    assert (inproc.case_id, inproc.case_name) == (cli.case_id, cli.case_name)
    diffs: list[float] = []
    if isinstance(inproc, StaticResults):
        assert inproc.n_steps == cli.n_steps
        diffs += [
            _dict_diff(inproc.node_disp, cli.node_disp),
            _dict_diff(inproc.node_reaction, cli.node_reaction),
            _dict_diff(inproc.element_forces, cli.element_forces),
        ]
    elif isinstance(inproc, PushoverResults):
        assert (inproc.n_steps, inproc.control_node, inproc.control_dof) == (
            cli.n_steps,
            cli.control_node,
            cli.control_dof,
        )
        diffs += [
            _max_diff(inproc.control_disp, cli.control_disp),
            _max_diff(inproc.base_shear, cli.base_shear),
            _dict_diff(inproc.node_disp, cli.node_disp),
            _dict_diff(inproc.element_forces, cli.element_forces),
        ]
    elif isinstance(inproc, ModalResults):
        assert list(inproc.mode_shapes) == list(cli.mode_shapes)
        diffs.append(_max_diff(inproc.eigenvalues, cli.eigenvalues))
        diffs += [_dict_diff(inproc.mode_shapes[m], cli.mode_shapes[m]) for m in inproc.mode_shapes]
    elif isinstance(inproc, ResponseSpectrumResults):
        assert (inproc.direction, inproc.combination) == (cli.direction, cli.combination)
        diffs.append(_dict_diff(inproc.combined_disp, cli.combined_disp))
        assert len(inproc.modes) == len(cli.modes)
        for a, b in zip(inproc.modes, cli.modes, strict=True):
            for name in (
                "period",
                "frequency",
                "angular_frequency",
                "participation_factor",
                "effective_mass",
                "mass_ratio",
                "sa_at_period",
            ):
                diffs.append(abs(float(getattr(a, name)) - float(getattr(b, name))))
            assert a.mode_number == b.mode_number
            diffs.append(_dict_diff(a.modal_peak_disp, b.modal_peak_disp))
    elif isinstance(inproc, TransientResults):
        assert (inproc.n_steps, inproc.dt, inproc.n_steps_requested) == (
            cli.n_steps,
            cli.dt,
            cli.n_steps_requested,
        )
        diffs.append(_max_diff(inproc.time(), cli.time()))
        import h5py

        with h5py.File(inproc.h5_path, "r") as fa, h5py.File(cli.h5_path, "r") as fb:
            keys_a = sorted(_leaf_keys(fa))
            keys_b = sorted(_leaf_keys(fb))
            assert keys_a == keys_b
            diffs += [_max_diff(fa[k][()], fb[k][()]) for k in keys_a]
    else:  # pragma: no cover
        raise AssertionError(type(inproc))
    return max(diffs)


def _leaf_keys(f) -> list[str]:  # type: ignore[no-untyped-def]
    import h5py

    keys: list[str] = []
    f.visititems(lambda name, obj: keys.append(name) if isinstance(obj, h5py.Dataset) else None)
    return keys


_FRESH_REFERENCE = """
import sys
from pathlib import Path
from opensees_studio.services import load_project
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.result_store import write_manifest, write_results
path, case_id, out = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
project = load_project(path)
case = next(c for c in project.analyses if c.id == case_id)
results = OpenSeesRunner(project).run(case, results_dir=out)
write_manifest(out, [write_results(results, out)], str(path))
"""


def run_both(example: str, case_id: int, kind: type, tmp_path: Path):  # type: ignore[no-untyped-def]
    """Run ``case_id`` of ``example`` directly and through the CLI; return both results."""
    path = EXAMPLES / f"{example}.osmodel"
    project = load_project(path)
    case = next(c for c in project.analyses if c.id == case_id)
    ref_dir = tmp_path / "inproc"
    if kind in (ModalResults, ResponseSpectrumResults):
        proc = subprocess.run(
            [sys.executable, "-c", _FRESH_REFERENCE, str(path), str(case_id), str(ref_dir)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        inproc = load_results(load_manifest(ref_dir)["cases"][0], ref_dir)
    else:
        inproc = OpenSeesRunner(project).run(case, results_dir=ref_dir)

    out = tmp_path / "cli"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(path),
            "--cases",
            str(case_id),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    entry = load_manifest(out)["cases"][0]
    return inproc, load_results(entry, out)


@pytest.mark.parametrize(
    ("example", "case_id", "kind"), CASES, ids=[f"{e}-{c}" for e, c, _ in CASES]
)
def test_cli_results_match_in_process(
    example: str, case_id: int, kind: type, tmp_path: Path
) -> None:
    inproc, cli = run_both(example, case_id, kind, tmp_path)
    assert isinstance(inproc, kind)
    assert compare(inproc, cli) == 0.0


# ─────────────────────── multi-case runs ───────────────────────
def _fresh_reference(path: Path, case_id: int, ref_dir: Path, env: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    proc = subprocess.run(
        [sys.executable, "-c", _FRESH_REFERENCE, str(path), str(case_id), str(ref_dir)],
        capture_output=True,
        text=True,
        timeout=600,
        env={**os.environ, **(env or {})},
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return load_results(load_manifest(ref_dir)["cases"][0], ref_dir)


def _multi_case_cli(path: Path, case_ids: list[int], out: Path, env: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(path),
            "--cases",
            *[str(c) for c in case_ids],
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        env={**os.environ, **(env or {})},
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    entries = load_manifest(out)["cases"]
    assert [e["case_id"] for e in entries] == case_ids
    logs = [
        json.loads(line)["message"]
        for line in proc.stdout.splitlines()
        if line.strip() and json.loads(line).get("type") == "log"
    ]
    return [load_results(e, out) for e in entries], logs


MULTI_CASE_RUNS = [
    ("space_frame_3d", [2, 4, 2]),
    ("space_frame_3d", [4, 2]),
    ("cantilever", [3, 1, 3]),
    ("elastic_frame", [3, 1, 3]),
]


@pytest.mark.parametrize(
    ("example", "case_ids"), MULTI_CASE_RUNS, ids=[f"{e}-{c}" for e, c in MULTI_CASE_RUNS]
)
def test_multi_case_cli_run_matches_fresh_process_references(
    example: str, case_ids: list[int], tmp_path: Path
) -> None:
    """Several eigen calls in one CLI process give the fresh-process results exactly.

    Before the dense routing the second eigen call of these runs differed
    from a fresh process (space_frame_3d RS case by 4548 in effective mass,
    cantilever modes by 4.75e-2, elastic_frame modes by 1.616).
    """
    path = EXAMPLES / f"{example}.osmodel"
    results, logs = _multi_case_cli(path, case_ids, tmp_path / "cli")
    for position, (case_id, cli) in enumerate(zip(case_ids, results, strict=True)):
        reference = _fresh_reference(path, case_id, tmp_path / f"ref{position}")
        assert compare(reference, cli) == 0.0, f"case {case_id} at position {position}"
    assert not any("fresh process" in line for line in logs), logs
    solver_lines = [line for line in logs if line.startswith("Eigen solver:")]
    assert solver_lines and all("fullGenLapack" in line for line in solver_lines)


def test_multi_case_cli_run_above_threshold_reexecs_arpack_cases(tmp_path: Path) -> None:
    """A 900 free DOF grid routed to ARPACK (threshold lowered by the environment
    override): the second and third eigen cases run in a fresh child process and
    match fresh-process references exactly.
    """
    from opensees_studio.services import save_project
    from tests.integration._synthetic import grid_frame

    project = grid_frame(4, 4, 6)
    path = save_project(project, tmp_path / "grid.osmodel")
    env = {"OPENSEES_STUDIO_DENSE_EIGEN_MAX_DOF": "100"}
    case_ids = [1, 2, 1]
    results, logs = _multi_case_cli(path, case_ids, tmp_path / "cli", env)
    for position, (case_id, cli) in enumerate(zip(case_ids, results, strict=True)):
        assert isinstance(cli, ModalResults)
        assert cli.solver == "genBandArpack"
        assert cli.n_free_dof == 900
        reference = _fresh_reference(path, case_id, tmp_path / f"ref{position}", env)
        assert compare(reference, cli) == 0.0, f"case {case_id} at position {position}"
    assert sum("fresh process" in line for line in logs) == 2, logs
