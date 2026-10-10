"""``TrigTimeSeries`` against the same sine sampled as a ``PathTimeSeries``.

An elastic SDOF cantilever under uniform excitation: once with the native
OpenSees Trig series, once with the sine sampled at the analysis dt as a
Path series. The Path series is interpolated linearly between samples and
the integrator evaluates the load at the step instants, where both series
agree exactly, so the two displacement histories must coincide.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")
pytest.importorskip("h5py")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    Node,
    PathTimeSeries,
    Project,
    TransientCase,
    TrigTimeSeries,
    UniformExcitationPattern,
    sine_excitation,
)
from opensees_studio.services import OpenSeesRunner

DT = 0.005
N_STEPS = 1200
FREQUENCY = 1.5
AMPLITUDE = 2.0  # m/s^2


def _project(series) -> Project:  # type: ignore[no-untyped-def]
    L, E, A, I = 3.0, 200e9, 0.01, 8.333e-6  # noqa: E741 - second moment of area
    m_tip = 1000.0
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, True, False, False, False, True)),
            Node(id=2, coords=(0.0, L, 0.0), mass=(m_tip, m_tip, 0.0, 0.0, 0.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, E=E, A=A, Iz=I)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[series],
        load_patterns=[UniformExcitationPattern(id=1, direction=1, accel_series_id=1)],
        analyses=[
            TransientCase(
                id=1,
                name="Sine",
                pattern_ids=[1],
                dt=DT,
                n_steps=N_STEPS,
                algorithm="Linear",
            )
        ],
    )


def _run(project: Project) -> np.ndarray:
    case = project.analyses[0]
    results_dir = Path(tempfile.mkdtemp(prefix="trig_vs_path_"))
    result = OpenSeesRunner(project).run(case, results_dir=results_dir)
    return result.node_disp_history(2)[:, 0]


def test_trig_series_matches_sampled_sine_path_series() -> None:
    duration = N_STEPS * DT
    trig = TrigTimeSeries(id=1, factor=AMPLITUDE, t_end=duration, period=1.0 / FREQUENCY)
    generated = sine_excitation(AMPLITUDE, FREQUENCY, duration, DT)
    path = PathTimeSeries(id=1, dt=DT, values=generated.accel.tolist(), file_path="generated:sine")

    ux_trig = _run(_project(trig))
    ux_path = _run(_project(path))

    assert ux_trig.shape == ux_path.shape == (N_STEPS,)
    peak = float(np.max(np.abs(ux_trig)))
    assert peak > 0.0
    # the sine is resonant enough to move the mass visibly: k = 3EI/L^3
    omega_n = math.sqrt(3.0 * 200e9 * 8.333e-6 / 3.0**3 / 1000.0)
    assert 0.0 < peak < 10.0 * AMPLITUDE / omega_n**2 * 5.0
    assert np.allclose(ux_trig, ux_path, rtol=1e-9, atol=1e-9 * peak)
