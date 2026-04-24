"""Integration test for Elastic Frame example (OpenSees Ex 4)."""

from __future__ import annotations

import math

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import ModalCase, StaticCase  # noqa: E402
from opensees_studio.services import load_project, save_project  # noqa: E402
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402


BASE_NODES = (1, 2, 3, 4)


def _reload(proj, tmp_path):  # type: ignore[no-untyped-def]
    path = tmp_path / "ef.osmodel"
    save_project(proj, path)
    reloaded = load_project(path)
    reloaded.validate_references()
    return reloaded


def test_elastic_frame_gravity_reactions(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """ΣFy at base = total applied gravity (distributed w × beam × floors)."""
    from examples.elastic_frame import (
        BAY, LOAD_F1, LOAD_F2, LOAD_F3, N_BAYS, build_elastic_frame,
    )
    proj = _reload(build_elastic_frame(), tmp_path)

    gravity_case = next(
        c for c in proj.analyses
        if isinstance(c, StaticCase) and c.name == "Gravity"
    )
    r = OpenSeesRunner(proj).run(gravity_case)

    sum_fy = sum(r.node_reaction[nid][-1, 1] for nid in BASE_NODES)
    sum_fx = sum(r.node_reaction[nid][-1, 0] for nid in BASE_NODES)

    # Expected: w_floor × N_BAYS × BAY per floor, summed over 3 floors.
    # w_floor = Load_floor / ((N_BAYS + 1) × BAY) — the Tcl reference
    # tributary formula (weight divided by number of column lines).
    w_sum = (LOAD_F1 + LOAD_F2 + LOAD_F3) / (N_BAYS + 1)
    expected_total = w_sum * N_BAYS
    assert sum_fy == pytest.approx(expected_total, abs=1.0)
    # Symmetric frame + symmetric gravity → no horizontal drift.
    assert abs(sum_fx) < 1e-6

    # By symmetry exterior-column reactions pair up, as do interior.
    assert r.node_reaction[1][-1, 1] == pytest.approx(
        r.node_reaction[4][-1, 1], abs=1e-6,
    )
    assert r.node_reaction[2][-1, 1] == pytest.approx(
        r.node_reaction[3][-1, 1], abs=1e-6,
    )


def test_elastic_frame_gravity_plus_lateral_reactions(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """ΣFx at base must equal -(lateral applied) within PDelta tolerance."""
    from examples.elastic_frame import (
        BAY, LOAD_F1, LOAD_F2, LOAD_F3,
        N_BAYS, P_F1, P_F2, P_F3, build_elastic_frame,
    )
    proj = _reload(build_elastic_frame(), tmp_path)

    combined = next(
        c for c in proj.analyses
        if isinstance(c, StaticCase) and c.name == "Gravity+Lateral"
    )
    r = OpenSeesRunner(proj).run(combined)

    sum_fx = sum(r.node_reaction[nid][-1, 0] for nid in BASE_NODES)
    sum_fy = sum(r.node_reaction[nid][-1, 1] for nid in BASE_NODES)
    # Linear solve with PDelta transformation: horizontal equilibrium
    # picks up a ~2% second-order contribution from gravity acting on
    # the displaced configuration.
    applied_fx = P_F1 + P_F2 + P_F3
    assert sum_fx == pytest.approx(-applied_fx, rel=0.03)
    # Vertical reaction matches the applied distributed gravity total.
    expected_fy = (LOAD_F1 + LOAD_F2 + LOAD_F3) * N_BAYS / (N_BAYS + 1)
    assert sum_fy == pytest.approx(expected_fy, abs=1.0)


def test_elastic_frame_modal_periods(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """5-mode eigen analysis: first periods match the Tcl reference values."""
    from examples.elastic_frame import build_elastic_frame
    proj = _reload(build_elastic_frame(), tmp_path)

    modal = next(c for c in proj.analyses if isinstance(c, ModalCase))
    r = OpenSeesRunner(proj).run(modal)

    assert len(r.eigenvalues) == 5
    # Eigenvalues strictly positive and ascending.
    for i in range(5):
        assert r.eigenvalues[i] > 0.0
    for i in range(1, 5):
        assert r.eigenvalues[i] > r.eigenvalues[i - 1]

    # Reference periods from the OpenSees Ex 4 Tcl: 1.040, 0.3526,
    # 0.1930, 0.1562, 0.130 s. Our solve nails these within 1.5%.
    expected = [1.040, 0.3526, 0.1930, 0.1562, 0.130]
    periods = [2.0 * math.pi / math.sqrt(v) for v in r.eigenvalues]
    for i, (T, T_ref) in enumerate(zip(periods, expected), start=1):
        assert T == pytest.approx(T_ref, rel=0.02), (
            f"T{i} = {T:.4f} s, reference {T_ref:.4f} s"
        )
