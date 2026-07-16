"""ImposedSupportMotion physics: equivalence with a uniform-excitation twin.

A grounded zeroLength isolator (elastic axial spring, ``-doRayleigh``) with a
tip mass, betaKinit Rayleigh damping — the wire-rope benchmark's damping
topology in miniature. The support is driven by a RAMPED sine displacement
d(t) (smooth start: d(0) = d'(0) = 0, so no startup velocity impulse), and the
relative response must match a UniformExcitation run whose accel series is the
ANALYTIC d''(t): OpenSees applies -m*a there, which is exactly the imposed-
motion experiment's relative-coordinate forcing -m*d''. Any residual is
mechanism error — in particular a support velocity that fails to reach the
betaKinit damping coupling of the -doRayleigh element would show up here at
the tens-of-percent level (that failure mode is real: a Plain-pattern ``sp``
under the Transformation handler exhibits it).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

ops = pytest.importorskip("openseespy.opensees")
h5py = pytest.importorskip("h5py")

from opensees_studio.core import (  # noqa: E402
    ElasticUniaxial,
    ImposedSupportMotionPattern,
    Node,
    PathTimeSeries,
    Project,
    TransientCase,
    UniformExcitationPattern,
    ZeroLengthElement,
)
from opensees_studio.services import OpenSeesRunner  # noqa: E402

W = 1.57  # drive (rad/s)
DT_SERIES = 0.01
NPTS = 1601  # 16 s
DT = 0.005
N_STEPS = 3200
K = math.pi**2  # with m=1: system omega = pi (T = 2 s)
BETA_K_INIT = 0.05  # exaggerated so a damping-coupling error is loud
T_RAMP = 8.0


def _series() -> tuple[list[float], list[float]]:
    t = np.arange(NPTS) * DT_SERIES
    ramp = np.where(t < T_RAMP, 0.5 * (1 - np.cos(math.pi * t / T_RAMP)), 1.0)
    dramp = np.where(t < T_RAMP, 0.5 * (math.pi / T_RAMP) * np.sin(math.pi * t / T_RAMP), 0.0)
    ddramp = np.where(t < T_RAMP, 0.5 * (math.pi / T_RAMP) ** 2 * np.cos(math.pi * t / T_RAMP), 0.0)
    s, c = np.sin(W * t), np.cos(W * t)
    disp = 0.1 * ramp * s
    acc = 0.1 * (ddramp * s + 2 * dramp * W * c - ramp * W * W * s)  # analytic d''
    return disp.tolist(), acc.tolist()


def _project(pattern, series_values) -> Project:  # type: ignore[no-untyped-def]
    return Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(
                id=2,
                coords=(0, 0, 0),
                restraint=(False, True, True, True, True, True),
                mass=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            ),
        ],
        materials=[ElasticUniaxial(id=1, E=K)],
        elements=[
            ZeroLengthElement(
                id=1,
                nodes=(1, 2),
                material_ids=(1,),
                dofs=(1,),
                do_rayleigh=True,
            ),
        ],
        # use_last: the final analyze step lands a float-accumulation hair past
        # the record end — without it the imposed support snaps to 0 there.
        time_series=[PathTimeSeries(id=1, dt=DT_SERIES, values=series_values, use_last=True)],
        load_patterns=[pattern],
        analyses=[
            TransientCase(
                id=1,
                name="drive",
                pattern_ids=[9],
                dt=DT,
                n_steps=N_STEPS,
                constraints="Transformation",
                algorithm="Newton",
                test="NormDispIncr",
                tolerance=1e-10,
                max_iter=100,
                rayleigh_beta_k_init=BETA_K_INIT,
            )
        ],
    )


def _run(project: Project, tmp_path) -> tuple[np.ndarray, np.ndarray]:  # type: ignore[no-untyped-def]
    runner = OpenSeesRunner(project)
    results = runner.run(project.analyses[0], tmp_path)
    with h5py.File(results.h5_path, "r") as f:
        u1 = np.asarray(f["nodes/1/disp"])[:, 0]
        u2 = np.asarray(f["nodes/2/disp"])[:, 0]
    return u1, u2


def test_imposed_disp_matches_uniform_excitation_twin(tmp_path) -> None:  # type: ignore[no-untyped-def]
    disp, acc = _series()

    imposed = ImposedSupportMotionPattern(
        id=9,
        direction=1,
        disp_series_id=1,
        node_ids=[1],
    )
    ground, absolute = _run(_project(imposed, disp), tmp_path / "imposed")

    # The support tracked the record (spot-check the steady peak).
    assert np.max(np.abs(ground)) == pytest.approx(0.1, rel=1e-3)

    uniform = UniformExcitationPattern(id=9, direction=1, accel_series_id=1)
    _, reference = _run(_project(uniform, acc), tmp_path / "uniform")

    relative = absolute - ground
    peak = np.max(np.abs(reference))
    residual = np.max(np.abs(relative - reference))
    # Round-3 mechanism experiment: ~0.006% of peak for this mechanism;
    # a broken velocity coupling sits at ~30%.
    assert residual < 0.001 * peak
