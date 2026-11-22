"""A transient case with modal damping calls eigen: the CLI routes it like a modal case."""

from __future__ import annotations

import pytest

from opensees_studio.core import Node, Project, TransientCase
from opensees_studio.run import _routed_to_arpack, _uses_eigen


def _project(n_nodes: int) -> Project:
    return Project(
        ndm=3, ndf=6, nodes=[Node(id=i, coords=(float(i), 0.0, 0.0)) for i in range(1, n_nodes + 1)]
    )


def _case(zeta: float | None, modes: int = 10) -> TransientCase:
    return TransientCase(
        id=1, name="t", dt=0.01, n_steps=1, modal_damping=zeta, modal_damping_modes=modes
    )


def test_modal_damping_uses_eigen() -> None:
    assert _uses_eigen(_case(0.05)) and not _uses_eigen(_case(None))


@pytest.mark.parametrize(("nodes", "arpack"), [(2, False), (200, True)])
def test_the_solver_follows_the_free_dof(nodes: int, arpack: bool) -> None:
    # 12 free DOF -> dense; 1200 free DOF -> above the dense threshold -> ARPACK.
    assert _routed_to_arpack(_project(nodes), _case(0.05)) is arpack
    assert _routed_to_arpack(_project(nodes), _case(None)) is False


def test_zeta_must_be_below_one() -> None:
    with pytest.raises(ValueError):
        _case(1.0)


@pytest.mark.parametrize(("nodes", "arpack"), [(2, False), (200, True)])
def test_mode1_rayleigh_is_routed_like_a_one_mode_eigen(nodes: int, arpack: bool) -> None:
    # Its single eigen call takes the solver from resolve_modal_solver too, so
    # above the dense threshold it is an ARPACK call the CLI must route.
    case = TransientCase(id=1, name="t", dt=0.01, n_steps=1, rayleigh_mode1_damping=0.05)
    assert _uses_eigen(case)
    assert _routed_to_arpack(_project(nodes), case) is arpack
