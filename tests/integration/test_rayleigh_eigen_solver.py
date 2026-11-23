"""Mode-1 Rayleigh damping takes its eigen solver from resolve_modal_solver.

It used to call ``fullGenLapack`` whatever the model size: cubic in time and
quadratic in memory above the dense threshold. Now it follows the same rule as
a modal case, and a case that also has modal damping calls ``eigen`` once.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

import openseespy.opensees as real_ops

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
from opensees_studio.core.modal import DENSE_EIGEN_MAX_FREE_DOF_ENV
from opensees_studio.services.opensees_runner import OpenSeesRunner

N_FREE = 20  # one free DOF (Ux) per node after the fixed first one


class _EigenSpy:
    """``openseespy.opensees`` with every ``eigen`` call recorded."""

    def __init__(self) -> None:
        self.eigen_calls: list[tuple[Any, ...]] = []

    def eigen(self, *args: Any) -> Any:
        self.eigen_calls.append(args)
        return real_ops.eigen(*args)

    def __getattr__(self, name: str) -> Any:
        return getattr(real_ops, name)


def _chain(*, rayleigh: float | None, modal: float | None) -> tuple[Project, TransientCase]:
    """An axial bar chain pulled by a preload, released, then vibrating freely."""
    held = (False, False, True, False, False, False)
    nodes = [Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6)]
    nodes += [
        Node(id=i, coords=(float(i - 1), 0.0, 0.0), restraint=held, mass=(1.0, 0, 1.0, 0, 0, 0))
        for i in range(2, N_FREE + 2)
    ]
    elements = [
        TrussElement(id=i, nodes=(i, i + 1), area=1.0, material_id=1) for i in range(1, N_FREE + 1)
    ]
    project = Project(
        ndm=2,
        ndf=2,
        nodes=nodes,
        materials=[ElasticUniaxial(id=1, E=400.0)],
        elements=elements,
        time_series=[ConstantTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=N_FREE + 1, forces=(4.0, 0, 0, 0, 0, 0))],
            )
        ],
        analyses=[StaticCase(id=1, name="pull", pattern_ids=[1], n_steps=1)],
    )
    case = TransientCase(
        id=2,
        name="release",
        dt=0.01,
        n_steps=300,
        integrator_params=(0.5, 0.25),
        preload_case_ids=[1],
        remove_patterns=[1],
        rayleigh_mode1_damping=rayleigh,
        modal_damping=modal,
        modal_damping_modes=3,
    )
    project.analyses.append(case)
    return project, case


def _run(project: Project, case: TransientCase, tmp_path: Path) -> tuple[_EigenSpy, np.ndarray]:
    spy = _EigenSpy()
    results = OpenSeesRunner(project, ops_module=spy).run(case, results_dir=tmp_path)
    return spy, np.asarray(results.node_disp_history(N_FREE + 1)[:, 0])


def test_small_models_keep_the_dense_solver(tmp_path: Path) -> None:
    project, case = _chain(rayleigh=0.05, modal=None)
    spy, _ = _run(project, case, tmp_path)
    assert spy.eigen_calls == [("-fullGenLapack", 1)]


def test_above_the_threshold_rayleigh_uses_arpack_with_the_same_damping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, case = _chain(rayleigh=0.05, modal=None)
    _, dense = _run(project, case, tmp_path / "dense")

    monkeypatch.setenv(DENSE_EIGEN_MAX_FREE_DOF_ENV, "4")
    spy, arpack = _run(project, case, tmp_path / "arpack")

    assert spy.eigen_calls == [("-genBandArpack", 1)]
    np.testing.assert_allclose(arpack, dense, rtol=1e-6, atol=1e-12)


def test_rayleigh_and_modal_damping_share_one_eigen_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DENSE_EIGEN_MAX_FREE_DOF_ENV, "4")
    project, case = _chain(rayleigh=0.02, modal=0.03)
    spy, history = _run(project, case, tmp_path)
    assert spy.eigen_calls == [("-genBandArpack", 3)]
    assert np.all(np.isfinite(history))
