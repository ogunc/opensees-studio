"""RC Frame Pushover Analysis — OpenSees Examples Manual, Example 3.2.

Sources the Example 3 gravity model and extends it with a lateral
reference load pattern + DisplacementControl pushover on the top-left
joint (node 3, DOF 1 = Ux). Target displacement 15 in with dU = 0.1
in per step. Matches the Tcl walkthrough at:
https://opensees.berkeley.edu/wiki/index.php?title=RC_Portal_Frame_Pushover_Analysis

Model (kip-in-ksi):
    - Geometry + section + elements = Example 3 (rc_frame_gravity).
    - Gravity pattern uses a ``ConstantTimeSeries`` so the 180 kip/top
      stays locked during the lateral push (the Tcl equivalent of
      ``loadConst -time 0.0`` after a Linear-TS gravity analysis).
    - Lateral pattern: H = 10 kip at nodes 3 and 4 in +X, Linear TS,
      scaled by DisplacementControl.

GUI walkthrough: File → Open → rc_frame_pushover.osmodel → Analyze →
Run → Pushover → Display → Show Pushover Curve.
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import (
    ConstantTimeSeries,
    LinearTimeSeries,
    NodalLoad,
    PlainLoadPattern,
    PushoverCase,
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

    Two surgical edits:
    1. The gravity pattern switches from Linear → Constant TimeSeries
       so the two-stage pushover runner applies it as a locked preload
       (equivalent to ``loadConst -time 0.0`` after a Linear analysis).
    2. Add a lateral reference pattern (Linear TS, H kip at nodes 3+4)
       and replace the StaticCase with a PushoverCase referencing both
       patterns.
    """
    proj = build_rc_frame_gravity()
    proj.meta.name = "RC Frame Pushover (OpenSees Ex 3.2)"
    proj.meta.description = (
        "Ex 3 gravity model + lateral reference load + "
        "DisplacementControl pushover on node 3 (DOF 1) to 15 in."
    )

    # Swap the gravity TimeSeries: Linear (id 1) → Constant so the
    # runner's two-stage preload stage locks gravity before the push.
    proj.time_series = [
        ConstantTimeSeries(id=1, name="Gravity"),
        LinearTimeSeries(id=2, name="Lateral"),
    ]
    # Gravity pattern keeps the same Fy=-P loads at 3 & 4.
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
    proj.analyses = [PushoverCase(
        id=1, name="Pushover",
        pattern_ids=[1, 2],
        control_node=3, control_dof=1,       # Ux at top-left joint
        target_disp=D_TARGET,
        step_size=D_STEP,
        base_nodes=[1, 2],
        system="BandGeneral", constraints="Transformation",
        algorithm="Newton",
        test="NormDispIncr", tolerance=1e-12, max_iter=10,
    )]
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
