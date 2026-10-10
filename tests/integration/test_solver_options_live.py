"""Every offered numberer and system runs a static case in the live build."""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

import openseespy.opensees as ops

from opensees_studio.core import NUMBERERS, SYSTEM_ARGS, SYSTEMS, StaticCase
from opensees_studio.services import load_project
from opensees_studio.services.opensees_runner import OpenSeesRunner

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
OPTIONS = [(system, ()) for system in SYSTEMS] + [
    (system, (arg,)) for system, allowed in SYSTEM_ARGS.items() for arg in allowed
]


def _run(example: str, ops_module=None, **options):  # type: ignore[no-untyped-def]
    project = load_project(EXAMPLES / f"{example}.osmodel")
    case = next(c for c in project.analyses if isinstance(c, StaticCase))
    case = case.model_copy(update=options)
    project.analyses = [case]
    if ops_module is None:
        return OpenSeesRunner(project).run(case)
    return OpenSeesRunner(project, ops_module=ops_module).run(case)


def _disp(result) -> np.ndarray:  # type: ignore[no-untyped-def]
    return np.array([result.node_disp[n][-1] for n in sorted(result.node_disp)])


@pytest.mark.parametrize(
    ("numberer", "option"),
    list(itertools.product(NUMBERERS, OPTIONS)),
    ids=lambda v: v if isinstance(v, str) else " ".join([v[0], *v[1]]),
)
def test_each_offered_option_runs_a_small_static_case(numberer: str, option) -> None:  # type: ignore[no-untyped-def]
    system, args = option
    reference = _disp(_run("portal_frame"))
    result = _disp(_run("portal_frame", numberer=numberer, system=system, system_args=args))
    scale = float(np.max(np.abs(reference)))
    assert float(np.max(np.abs(result - reference))) <= 1e-9 * scale


def test_plain_sparse_general_runs_the_nonlinear_gravity_case() -> None:
    default = _run("rc_frame_gravity")
    source = _run("rc_frame_gravity", numberer="Plain", system="SparseGeneral")
    assert source.n_steps == default.n_steps
    assert np.allclose(_disp(source), _disp(default), rtol=1e-9, atol=1e-14)


class _WithPiv:
    """The live module with ``-piv`` appended to ``system SparseGeneral``."""

    def __init__(self) -> None:
        self.systems: list[tuple[str, ...]] = []

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        return getattr(ops, name)

    def system(self, name: str, *args: str) -> object:
        command = (name, *args, "-piv") if name == "SparseGeneral" else (name, *args)
        self.systems.append(command)
        return ops.system(*command)


def test_piv_changes_no_result_bit_in_this_build() -> None:
    """Why -piv is not offered: SuperLU always pivots here, with or without the flag."""
    plain = _disp(_run("rc_frame_gravity", system="SparseGeneral"))
    with_piv = _WithPiv()
    piv = _disp(_run("rc_frame_gravity", ops_module=with_piv, system="SparseGeneral"))
    assert with_piv.systems == [("SparseGeneral", "-piv")]
    assert np.array_equal(plain, piv)
