"""RC Frame Earthquake Analysis — OpenSees Examples Manual, Example 3.3.

Time-history analysis of the RC portal frame under horizontal ground
motion. Sources the Example 3 gravity model, adds lumped joint
masses, a PathTimeSeries from a ground-motion record, a
UniformExcitation load pattern in +X, and stiffness-proportional
Rayleigh damping. Newmark integrator with average-acceleration
(gamma = 0.5, beta = 0.25).

Matches the Tcl walkthrough at:
https://opensees.berkeley.edu/wiki/index.php?title=RC_Portal_Frame_Earthquake_Analysis

Model (kip-in-ksi):
    - Geometry + section + elements = Example 3 (rc_frame_gravity).
    - Gravity pattern uses ConstantTimeSeries so it stays locked during
      the transient (equivalent to ``loadConst -time 0.0``).
    - Nodal masses: m = P/g = 180/386.4 kip·s^2/in at nodes 3 and 4.
    - Ground-motion record: since the Tcl ships ARL360.at2 from the
      PEER strong-motion database (not redistributable without
      attribution), we bundle a short synthetic acceleration record
      that reproduces the same classroom behaviour: a ~4-second
      pulse-like time history with peak amplitude ≈ 0.35 g.
    - UniformExcitation pattern in DOF 1 (+X), scale factor = g
      (so the path data is in "g" units, multiplied to in/s²).
    - Rayleigh damping: alpha_m = 0, beta_kcommit = 0.000625.

GUI walkthrough: File → Open → rc_frame_earthquake.osmodel → Analyze
→ Run → Earthquake → Display → Show Time-History Plot (Node 3 Ux).
"""

from __future__ import annotations

import math
from pathlib import Path

from opensees_studio.core import (
    ConstantTimeSeries,
    NodalLoad,
    PathTimeSeries,
    PlainLoadPattern,
    TransientCase,
    UniformExcitationPattern,
)
from opensees_studio.services import load_project, save_project

try:
    from examples.rc_frame_gravity import build_rc_frame_gravity, P_LOAD
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from rc_frame_gravity import build_rc_frame_gravity, P_LOAD  # type: ignore


G = 386.4                    # in/s² (gravity)
DT = 0.01                    # s — time step of bundled ground motion
N_PTS = 400                  # 4-second duration
BETA_K_COMMIT = 0.000625     # Tcl reference stiffness-damping coeff


def _synthetic_ground_motion() -> list[float]:
    """Bundle a short acceleration signal (units of g).

    Decaying sinusoid centred at ~2 Hz with an exponential envelope —
    peak ~0.15 g, enough to drive the fibre section into inelastic
    cycles without blowing past its crushing strain on the very first
    impulse (which would require a much tighter Newmark step).
    """
    out: list[float] = []
    peak = 0.15                       # units of g
    freq = 2.0                        # Hz (period ~0.5 s)
    for i in range(N_PTS):
        t = i * DT
        if t < 0.5:
            env = t / 0.5
        elif t < 2.0:
            env = 1.0
        else:
            env = math.exp(-(t - 2.0) / 0.8)
        out.append(peak * env * math.sin(2.0 * math.pi * freq * t))
    return out


def build_rc_frame_earthquake():  # type: ignore[no-untyped-def]
    """Ex 3 gravity + lumped masses + ground motion + Rayleigh damping."""
    proj = build_rc_frame_gravity()
    proj.meta.name = "RC Frame Earthquake (OpenSees Ex 3.3)"
    proj.meta.description = (
        "Ex 3 gravity + uniform base excitation (horizontal, 4-s "
        "synthetic record peaking at ~0.35 g) + Rayleigh beta_k"
    )

    # Locked-in gravity — Constant TS, matches the Tcl loadConst.
    proj.time_series = [
        ConstantTimeSeries(id=1, name="Gravity"),
        PathTimeSeries(
            id=2, name="GroundMotion",
            dt=DT, factor=G,
            values=_synthetic_ground_motion(),
        ),
    ]

    # Lumped mass m = P/g at each top node (gravity is the sole
    # tributary weight; m_x = m_y because a point mass is isotropic).
    m = P_LOAD / G              # ≈ 0.466 kip·s²/in
    for n in proj.nodes:
        if n.id in (3, 4):
            n.mass = (m, m, 0.0, 0.0, 0.0, 0.0)

    # Gravity pattern (now with Constant TS).
    proj.load_patterns = [
        PlainLoadPattern(
            id=1, name="Gravity",
            time_series_id=1,
            nodal_loads=[
                NodalLoad(node_id=3, forces=(0, -P_LOAD, 0, 0, 0, 0)),
                NodalLoad(node_id=4, forces=(0, -P_LOAD, 0, 0, 0, 0)),
            ],
        ),
        # Ground motion — applied as UniformExcitation in +X (dir=1).
        UniformExcitationPattern(
            id=2, name="GroundMotion",
            direction=1,
            accel_series_id=2,
        ),
    ]

    proj.analyses = [TransientCase(
        id=1, name="Earthquake",
        pattern_ids=[1, 2],
        dt=DT,
        n_steps=N_PTS,
        system="BandGeneral", constraints="Plain",
        integrator="Newmark",
        integrator_params=(0.5, 0.25),    # average-acceleration method
        algorithm="Newton",
        test="NormDispIncr", tolerance=1e-12, max_iter=10,
        rayleigh_alpha_m=0.0,
        rayleigh_beta_k=BETA_K_COMMIT,
    )]
    return proj


def main() -> None:
    project = build_rc_frame_earthquake()
    project.validate_references()
    print(f"Built '{project.meta.name}'")
    print(f"  Ground motion: {N_PTS} points, dt = {DT} s, "
          f"total = {N_PTS * DT:.2f} s")
    print(f"  Nodal mass (3, 4): {P_LOAD / G:.4f} kip*s^2/in")
    print(f"  Rayleigh beta_k = {BETA_K_COMMIT}")
    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved -> {out_path}")
    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
