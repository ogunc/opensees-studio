"""RC Frame Pushover Analysis — OpenSees Examples Manual, Example 3.2.

Sources the Example 3 gravity model and extends it with a lateral
reference load pattern + DisplacementControl pushover on the top-left
joint (node 3, DOF 1 = Ux). Target displacement 15 in with dU = 0.1
in per step. Matches the Tcl walkthrough at:
https://opensees.berkeley.edu/wiki/index.php?title=RC_Portal_Frame_Pushover_Analysis

Model (kip-in-ksi):
    - Geometry + section + elements = Example 3 (rc_frame_gravity).
    - Gravity preload = a ``StaticCase`` with 10 × LoadControl(0.1)
      steps under a Linear TS — same recipe the Tcl uses
      (``analyze 10; loadConst -time 0.0``). Referenced by the
      PushoverCase via ``preload_case_ids``.
    - Lateral pattern: H = 10 kip at nodes 3 and 4 in +X, Linear TS,
      scaled by DisplacementControl.

GUI walkthrough: File → Open → rc_frame_pushover.osmodel → Analyze →
Run → Pushover → Display → Show Pushover Curve.
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import (
    LinearTimeSeries,
    NodalLoad,
    PlainLoadPattern,
    PushoverCase,
    StaticCase,
)
from opensees_studio.services import load_project, save_project

# Reuse the Example 3 gravity project as the foundation — identical
# geometry, materials, sections, elements. Only the load patterns and
# analysis case change for the pushover. Works both when importing as
# ``examples.rc_frame_pushover`` (pytest) and when running this file
# directly (``python examples/rc_frame_pushover.py``).
try:
    from examples.rc_frame_gravity import build_rc_frame_gravity, P_LOAD
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from rc_frame_gravity import build_rc_frame_gravity, P_LOAD  # type: ignore

# Pushover parameters from the Tcl reference.
H_LATERAL = 10.0      # kip — reference lateral load
D_STEP = 0.1          # in   — DisplacementControl increment
D_TARGET = 15.0       # in   — total pushover displacement


def build_rc_frame_pushover():  # type: ignore[no-untyped-def]
    """Start from the Ex3 gravity model and re-plumb for pushover.

    Three edits to the gravity project:
    1. Add a ``LinearTimeSeries`` + ``PlainLoadPattern`` for the
       lateral reference load (H = 10 kip at nodes 3 & 4, +X).
    2. Keep the gravity pattern on its own Linear TS — the preload
       runs as a 10-step ``LoadControl(0.1)`` ramp, exactly as the
       Tcl walkthrough does.
    3. Replace the StaticCase with two cases: a preload ``StaticCase``
       (id 100) for gravity, and a ``PushoverCase`` whose
       ``preload_case_ids=[100]`` references it. The pushover's own
       ``pattern_ids`` holds only the lateral reference.
    """
    proj = build_rc_frame_gravity()
    proj.meta.name = "RC Frame Pushover (OpenSees Ex 3.2)"
    proj.meta.description = (
        "Ex 3 gravity preload (StaticCase) + lateral reference load + "
        "DisplacementControl pushover on node 3 (DOF 1) to 15 in, "
        "chained via preload_case_ids."
    )

    proj.time_series = [
        LinearTimeSeries(id=1, name="Gravity"),
        LinearTimeSeries(id=2, name="Lateral"),
    ]
    proj.load_patterns = [
        PlainLoadPattern(
            id=1, name="Gravity",
            time_series_id=1,
            nodal_loads=[
                NodalLoad(node_id=3, forces=(0, -P_LOAD, 0, 0, 0, 0)),
                NodalLoad(node_id=4, forces=(0, -P_LOAD, 0, 0, 0, 0)),
            ],
        ),
        # Lateral reference — scaled by the DisplacementControl factor.
        PlainLoadPattern(
            id=2, name="Lateral",
            time_series_id=2,
            nodal_loads=[
                NodalLoad(node_id=3, forces=(H_LATERAL, 0, 0, 0, 0, 0)),
                NodalLoad(node_id=4, forces=(H_LATERAL, 0, 0, 0, 0, 0)),
            ],
        ),
    ]
    proj.analyses = [
        StaticCase(
            id=100, name="Gravity-Preload",
            pattern_ids=[1],
            n_steps=10, load_factor_increment=0.1,
            system="BandGeneral", constraints="Transformation",
            integrator="LoadControl", algorithm="Newton",
            test="NormDispIncr", tolerance=1e-12, max_iter=10,
        ),
        PushoverCase(
            id=1, name="Pushover",
            preload_case_ids=[100],
            pattern_ids=[2],                 # lateral only
            control_node=3, control_dof=1,   # Ux at top-left joint
            target_disp=D_TARGET,
            step_size=D_STEP,
            base_nodes=[1, 2],
            system="BandGeneral", constraints="Transformation",
            algorithm="Newton",
            test="NormDispIncr", tolerance=1e-12, max_iter=10,
        ),
    ]
    return proj


def main() -> None:
    project = build_rc_frame_pushover()
    project.validate_references()
    print(f"Built '{project.meta.name}'")
    print(f"  H = {H_LATERAL} kip reference, dU = {D_STEP} in, target = {D_TARGET} in")
    print(f"  Steps = {int(D_TARGET / D_STEP)}")
    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved -> {out_path}")
    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
