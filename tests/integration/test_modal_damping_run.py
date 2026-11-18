"""Modal damping (``modalDamping``) against the free vibration of a damped SDOF."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    ConstantTimeSeries,
    ElasticUniaxial,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    TransientCase,
    TrussElement,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

K, M = 400.0, 1.0  # bar stiffness EA/L and tip mass: omega = 20 rad/s


def _sdof(zeta: float | None, modes: int = 10) -> tuple[Project, TransientCase]:
    """A bar pulled to u0 = P/K by a preload, released, then vibrating freely."""
    period = 2 * math.pi / math.sqrt(K / M)
    project = Project(
        ndm=2,
        ndf=2,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(
                id=2,
                coords=(1.0, 0.0, 0.0),
                restraint=(False, False, True, False, False, False),
                mass=(M, 0.0, M, 0.0, 0.0, 0.0),
            ),
        ],
        materials=[ElasticUniaxial(id=1, E=K)],
        elements=[TrussElement(id=1, nodes=(1, 2), area=1.0, material_id=1)],
        time_series=[ConstantTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(4.0, 0, 0, 0, 0, 0))],
            )
        ],
        analyses=[StaticCase(id=1, name="pull", pattern_ids=[1], n_steps=1)],
    )
    case = TransientCase(
        id=2,
        name="release",
        dt=period / 200,
        n_steps=1000,
        integrator_params=(0.5, 0.25),
        preload_case_ids=[1],
        remove_patterns=[1],
        modal_damping=zeta,
        modal_damping_modes=modes,
    )
    project.analyses.append(case)
    return project, case


def _peaks(u: np.ndarray) -> np.ndarray:
    inner = u[1:-1]
    return inner[(inner > u[:-2]) & (inner > u[2:])]


@pytest.mark.parametrize("modes", [1, 10])  # 10 is capped at the one free DOF
def test_the_logarithmic_decrement_gives_back_zeta(modes: int, tmp_path: Path) -> None:
    zeta = 0.05
    project, case = _sdof(zeta, modes)
    results = OpenSeesRunner(project).run(case, results_dir=tmp_path)
    peaks = _peaks(results.node_disp_history(2)[:, 0])
    assert len(peaks) >= 4
    delta = math.log(peaks[0] / peaks[3]) / 3
    measured = delta / math.sqrt(4 * math.pi**2 + delta**2)
    assert measured == pytest.approx(zeta, rel=0.02)


def test_without_modal_damping_the_motion_does_not_decay(tmp_path: Path) -> None:
    project, case = _sdof(None)
    results = OpenSeesRunner(project).run(case, results_dir=tmp_path)
    peaks = _peaks(results.node_disp_history(2)[:, 0])
    assert peaks[-1] == pytest.approx(peaks[0], rel=1e-4)  # sampled peaks, no decay


def test_a_case_without_modal_damping_dumps_no_new_keys() -> None:
    _project, case = _sdof(None)
    dumped = case.model_dump()
    assert "modal_damping" not in dumped and "modal_damping_modes" not in dumped
    assert _sdof(0.02)[1].model_dump()["modal_damping"] == 0.02
