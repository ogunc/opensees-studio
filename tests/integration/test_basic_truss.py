"""OpenSees integration test for the Basic Truss example.

Verifies the Example 1 (3-bar truss) model builds, runs, and produces
a physically reasonable tip deflection. This is the first of the
OpenSees Examples Manual regression tests.
"""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402


def test_basic_truss_converges_and_matches_expected_tip_displacement() -> None:
    """The 3-bar truss Example-1 model should return the crown displacement
    it did on the reference run — a single-step static solution."""
    from examples.basic_truss import build_basic_truss

    proj = build_basic_truss()
    runner = OpenSeesRunner(proj)
    result = runner.run(proj.analyses[0])

    assert 4 in result.node_disp, "Crown node (4) must have recorded displacement"
    ux, uy = result.node_disp[4][-1]

    # Expected: +21 mm horizontal (to the right, under 444.8 kN push),
    # -4.6 mm vertical (downward, under -222.4 kN gravity). Loose tolerance
    # because the OpenSees solve is single-precision-ish and the geometry
    # uses exact imperial→SI conversions.
    assert ux == pytest.approx(0.0208, rel=1e-2), f"Ux = {ux}"
    assert uy == pytest.approx(-0.00456, rel=1e-2), f"Uy = {uy}"

    # All three truss bars must have recorded forces.
    assert set(result.element_forces.keys()) == {1, 2, 3}


def test_basic_truss_round_trips(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The example project must survive save/load without any information loss."""
    from examples.basic_truss import build_basic_truss
    from opensees_studio.services import load_project, save_project

    p = build_basic_truss()
    path = tmp_path / "basic_truss.osmodel"
    save_project(p, path)
    r = load_project(path)
    assert r.model_dump(by_alias=True) == p.model_dump(by_alias=True)
