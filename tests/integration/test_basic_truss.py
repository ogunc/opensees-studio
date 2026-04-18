"""OpenSees integration test for the Basic Truss example.

Verifies the Example 1 (3-bar truss) model builds, runs, and produces
a physically reasonable tip deflection. This is the first of the
OpenSees Examples Manual regression tests.
"""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402


def test_basic_truss_matches_opensees_tcl_reference() -> None:
    """Crown displacement must match the OpenSees Tcl Example-1 reference.

    The Tcl model (kip-in) reports node 4 disp = (+0.5301, -0.1779) in.
    Our SI model converts to that: 0.5301" = 0.01346 m,
    0.1779" = 0.004518 m. Tolerance is tight because the SI model is
    a linear rescale of the Tcl model — any deviation would flag a
    real solver/translation issue.
    """
    from examples.basic_truss import build_basic_truss, IN_TO_M

    proj = build_basic_truss()
    runner = OpenSeesRunner(proj)
    result = runner.run(proj.analyses[0])

    assert 4 in result.node_disp
    ux, uy = result.node_disp[4][-1]
    ux_in = ux / IN_TO_M
    uy_in = uy / IN_TO_M
    assert ux_in == pytest.approx(+0.5301, abs=1e-3), f"Ux = {ux_in} in"
    assert uy_in == pytest.approx(-0.1779, abs=1e-3), f"Uy = {uy_in} in"

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
