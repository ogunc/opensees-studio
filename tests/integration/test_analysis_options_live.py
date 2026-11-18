"""Every convergence test, algorithm and integrator the case forms offer runs in OpenSees."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    TransientCase,
)
from opensees_studio.core.analysis import (
    ALGORITHMS,
    TESTS,
    TRANSIENT_PARAMS,
)
from opensees_studio.core.analysis import test_args as convergence_test_args
from opensees_studio.services.opensees_runner import OpenSeesRunner

P, L, E, I = 10.0, 3.0, 2e8, 1e-4  # noqa: E741


def _cantilever(case) -> Project:  # type: ignore[no-untyped-def]
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(0.0, 0.0, L), mass=(1.0, 0, 1.0, 0, 0.01, 0)),
        ],
        sections=[ElasticSection(id=1, E=E, A=0.01, Iz=I)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(P, 0, 0, 0, 0, 0))],
            )
        ],
        analyses=[case],
    )


@pytest.mark.parametrize("test", TESTS)
@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_every_test_and_algorithm_gives_the_cantilever_tip(test: str, algorithm: str) -> None:
    if (algorithm, test) == ("SecantNewton", "FixedNumIter"):
        pytest.skip("OpenSees divides by a zero secant update after convergence: NaN")
    if (
        sys.platform == "darwin"
        and algorithm in ("BFGS", "Broyden")
        and test in ("RelativeNormDispIncr", "RelativeEnergyIncr", "RelativeTotalNormDispIncr")
    ):
        pytest.skip("macOS OpenSees 3.8: BFGS/Broyden never meet a relative test (any tolerance)")
    case = StaticCase(id=1, name="s", pattern_ids=[1], algorithm=algorithm, test=test)
    results = OpenSeesRunner(_cantilever(case)).run(case)
    assert float(results.node_disp[2][-1][0]) == pytest.approx(P * L**3 / (3 * E * I), rel=1e-6)


def test_min_unbal_disp_norm_is_a_static_integrator() -> None:
    case = StaticCase(
        id=1, name="s", pattern_ids=[1], integrator="MinUnbalDispNorm", algorithm="Newton"
    )
    results = OpenSeesRunner(_cantilever(case)).run(case)
    assert float(results.node_disp[2][-1][0]) == pytest.approx(P * L**3 / (3 * E * I), rel=1e-6)


@pytest.mark.parametrize("integrator", ["Newmark", "HHT", "GeneralizedAlpha", "TRBDF2"])
def test_transient_integrators_run(integrator: str, tmp_path: Path) -> None:
    params = tuple(v for _n, v in TRANSIENT_PARAMS[integrator]) or (0.5, 0.25)
    case = TransientCase(
        id=1,
        name="t",
        pattern_ids=[1],
        dt=0.001,
        n_steps=20,
        integrator=integrator,
        integrator_params=params[:2],
    )
    results = OpenSeesRunner(_cantilever(case)).run(case, results_dir=tmp_path)
    assert results.n_steps == 20


def test_test_args() -> None:
    assert convergence_test_args("FixedNumIter", 1e-6, 7) == (7,)
    assert convergence_test_args("NormDispOrUnbalance", 1e-6, 7) == (1e-6, 1e-6, 7)
    assert convergence_test_args("NormDispIncr", 1e-6, 7) == (1e-6, 7)
