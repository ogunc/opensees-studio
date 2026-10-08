"""The command sequence of models that use neither twoNodeLink nor a rigid link is
unchanged by those two capabilities.

The pinned SHA-256 values were taken from the sources of commit 668a946 (before
twoNodeLink and rigidLink existed) with this file's own ``command_log``. The log is
the ``build()`` sequence plus the analysis set-up of every static and transient
case, against a ``MagicMock`` ops module, so no solver runs.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    HystereticSM,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    TransientCase,
    ZeroLengthElement,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.persistence import load_project

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def zero_length_isolator() -> Project:
    """A grounded zeroLength isolator with HystereticSM materials under a frame."""
    env_pos = [(1.57, 0.00207), (3.0, 0.00436), (69.1, 0.0399)]
    env_neg = [(-1.4, -0.00057), (-2.89, -0.00244), (-15.31, -0.0483)]
    return Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(id=2, coords=(0, 0, 0)),
            Node(id=3, coords=(0, 0, 2.0)),
        ],
        materials=[HystereticSM(id=k, pos_env=env_pos, neg_env=env_neg) for k in (1, 2, 3)],
        sections=[ElasticSection(id=1, E=2e8, A=0.01, Iz=1e-4, Iy=1e-4, G=8e7, J=2e-4)],
        elements=[
            ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1, 2, 3), dofs=(3, 1, 2)),
            ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1, rho=0.1),
        ],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=3, forces=(0, 0, -1.0, 0, 0, 0))],
            )
        ],
        analyses=[
            StaticCase(id=1, pattern_ids=[1], constraints="Transformation"),
            TransientCase(id=2, dt=0.01, n_steps=10, rayleigh_beta_k_init=0.001),
        ],
    )


def command_log(project: Project) -> str:
    ops = MagicMock()
    runner = OpenSeesRunner(project, ops_module=ops)
    runner.build()
    for case in project.analyses:
        if isinstance(case, StaticCase | TransientCase):
            runner._setup_analysis(case)
    return "\n".join(repr(c) for c in ops.mock_calls)


MODELS = {
    "eigen_two_storey_shear_frame": lambda: load_project(
        EXAMPLES / "eigen_two_storey_shear_frame.osmodel"
    ),
    "isolated_portal2d": lambda: load_project(EXAMPLES / "isolated_portal2d.osmodel"),
    "space_frame_3d": lambda: load_project(EXAMPLES / "space_frame_3d.osmodel"),
    "zero_length_isolator": zero_length_isolator,
}

PINNED = {
    "eigen_two_storey_shear_frame": "b591d05a241592cd5cf931c8c5371e94f976922a46ce12549dad6786754a6124",
    "isolated_portal2d": "bd928d12a0ef10f0303f3e5cb4df05da814439b5690366f59f5e4ac033fe04a2",
    "space_frame_3d": "5ea481fa7ee04e2160d4fc4381d604ee5d419b94e708d7d70c708d28ab6c578b",
    "zero_length_isolator": "2806856a913335fd5c379147ef4f9a2ea4a74c07dd627359f72403ce2314a0ed",
}


@pytest.mark.parametrize("name", list(MODELS))
def test_command_sequence_unchanged(name: str) -> None:
    project = MODELS[name]()
    log = command_log(project)
    assert hashlib.sha256(log.encode()).hexdigest() == PINNED[name]


def test_pinned_models_cover_equal_dof_and_zero_length() -> None:
    assert MODELS["eigen_two_storey_shear_frame"]().mp_constraints
    assert MODELS["isolated_portal2d"]().mp_constraints
    assert any(isinstance(e, ZeroLengthElement) for e in MODELS["zero_length_isolator"]().elements)
