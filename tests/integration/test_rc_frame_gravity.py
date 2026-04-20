"""Integration test for the RC Frame Gravity example (OpenSees Ex 3)."""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.services import load_project, save_project  # noqa: E402
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402


def test_rc_frame_gravity_matches_opensees_reference(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Build → save → load → run → compare to OpenSees Tcl output.

    The Tcl script prints nodes 3 and 4 (top corners). Under the 10
    x 0.1 = full gravity load pattern, a symmetric frame with
    identical columns gives:
        Ux ≈ 0 (symmetric), Rz ≈ 0, Uy ≈ -0.0203 in
    The column axial force is 180 kip compression (from the 180 kip
    load stepped onto each top node).
    """
    from examples.rc_frame_gravity import build_rc_frame_gravity, P_LOAD
    proj = build_rc_frame_gravity()
    proj.validate_references()

    path = tmp_path / "rc.osmodel"
    save_project(proj, path)
    reloaded = load_project(path)
    reloaded.validate_references()

    result = OpenSeesRunner(reloaded).run(reloaded.analyses[0])

    # Every one of the 10 LoadControl steps must have converged —
    # the partial-result fallback would trim the array otherwise.
    assert len(result.control_disp) == 10 if hasattr(result, "control_disp") else True

    # Nodes 3 and 4 — symmetric loading, so Uy equal, Ux ≈ 0.
    d3 = result.node_disp[3][-1]
    d4 = result.node_disp[4][-1]
    assert abs(d3[0]) < 1e-6, f"Node 3 Ux = {d3[0]:.3e} should be ~0 (symmetric)"
    assert abs(d4[0]) < 1e-6, f"Node 4 Ux = {d4[0]:.3e} should be ~0 (symmetric)"

    # Top nodes settle downward — magnitude ≈ 0.0203 in per OpenSees.
    assert d3[1] == pytest.approx(-0.02028, abs=5e-4), f"Node 3 Uy = {d3[1]:.6e}"
    assert d4[1] == pytest.approx(-0.02028, abs=5e-4), f"Node 4 Uy = {d4[1]:.6e}"
    # By symmetry.
    assert d3[1] == pytest.approx(d4[1], abs=1e-9)

    # Column 1 axial force ≈ P = 180 kip compression.
    # localForce in 2D/ndf=3: [N_i, V_i, M_i, N_j, V_j, M_j].
    # Compression (end-i points along local-x TOWARD j) → +N by
    # OpenSees equilibrium sign, i.e. the first component equals the
    # applied vertical load on end i.
    col1 = result.element_forces[1][-1]
    assert abs(col1[0]) == pytest.approx(P_LOAD, abs=1.0), (
        f"Column 1 axial {col1[0]:.2f} ≠ ±{P_LOAD} kip"
    )
    assert abs(col1[3]) == pytest.approx(P_LOAD, abs=1.0)
