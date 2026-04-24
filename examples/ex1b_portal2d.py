"""OpenSees Example 1b. Elastic Portal Frame.

OpenSees Wiki:
https://opensees.berkeley.edu/wiki/index.php?title=OpenSees_Example_1b._Elastic_Portal_Frame

This packages the original Example 1b portal frame into one OpenSees
Studio project with shared gravity preload and both lateral-load cases:

- static pushover
- base-excitation earthquake analysis with ``BM68elc.acc``

Run from the repository root:

    python examples/ex1b_portal2d.py

Produces ``examples/ex1b_portal2d.osmodel``.
"""

from __future__ import annotations

from pathlib import Path
import sys

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opensees_studio.core import (  # noqa: E402
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PathTimeSeries,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    PushoverCase,
    StaticCase,
    TransientCase,
    UniformElementLoad,
    UniformExcitationPattern,
    UnitSystem,
)
from opensees_studio.services import load_project, save_project  # noqa: E402
from opensees_studio.services.peer_record import parse_plain_values  # noqa: E402


L_BEAM = 504.0
L_COL = 432.0
TOP_MASS = 5.18

A_COL = 3_600_000_000.0
IZ_COL = 1_080_000.0
A_BEAM = 5_760_000_000.0
IZ_BEAM = 4_423_680.0
E_MODULUS = 4227.0

GRAVITY_W = -7.94
LATERAL_NODE_LOAD = 2000.0

PUSH_STEP = 0.1
PUSH_TARGET = 10.0

GROUND_DT = 0.01
GROUND_FACTOR = 1.0
ANALYSIS_DT = 0.02
ANALYSIS_STEPS = 1000
DAMPING_RATIO = 0.02

_ROOT = Path(__file__).resolve().parent
GROUND_MOTION_FILE = _ROOT / "data" / "BM68elc.acc"
REFERENCE_PUSH_TCL = _ROOT / "data" / "Ex1b.Portal2D.Push.tcl.txt"
REFERENCE_EQ_TCL = _ROOT / "data" / "Ex1b.Portal2D.EQ.tcl.txt"


def _ground_motion_values() -> list[float]:
    return parse_plain_values(GROUND_MOTION_FILE)


def build_ex1b_portal2d() -> Project:
    values = _ground_motion_values()

    return Project(
        meta=ProjectMeta(
            name="OpenSees Ex 1b - Elastic Portal Frame",
            author="OpenSees Wiki / Silvia Mazzoni & Frank McKenna",
            description=(
                "Original Ex 1b elastic portal frame with shared gravity "
                "preload, static pushover, and BM68elc earthquake cases."
            ),
            units=UnitSystem.US_IN_KIP,
        ),
        ndm=2,
        ndf=3,
        nodes=[
            Node(
                id=1,
                name="Base-L",
                coords=(0.0, 0.0, 0.0),
                restraint=(True, True, False, False, False, True),
            ),
            Node(
                id=2,
                name="Base-R",
                coords=(L_BEAM, 0.0, 0.0),
                restraint=(True, True, False, False, False, True),
            ),
            Node(id=3, name="Top-L", coords=(0.0, L_COL, 0.0), mass=(TOP_MASS, 0.0, 0.0, 0.0, 0.0, 0.0)),
            Node(id=4, name="Top-R", coords=(L_BEAM, L_COL, 0.0), mass=(TOP_MASS, 0.0, 0.0, 0.0, 0.0, 0.0)),
        ],
        sections=[
            ElasticSection(id=1, name="Column", E=E_MODULUS, A=A_COL, Iz=IZ_COL, Iy=IZ_COL, G=1.0, J=1.0),
            ElasticSection(id=2, name="Beam", E=E_MODULUS, A=A_BEAM, Iz=IZ_BEAM, Iy=IZ_BEAM, G=1.0, J=1.0),
        ],
        elements=[
            ElasticBeamColumn(id=1, name="Col-L", nodes=(1, 3), section_id=1, geom_transf="Linear"),
            ElasticBeamColumn(id=2, name="Col-R", nodes=(2, 4), section_id=1, geom_transf="Linear"),
            ElasticBeamColumn(id=3, name="Beam", nodes=(3, 4), section_id=2, geom_transf="Linear"),
        ],
        time_series=[
            LinearTimeSeries(id=1, name="Gravity"),
            LinearTimeSeries(id=2, name="Lateral"),
            PathTimeSeries(
                id=3,
                name="BM68elc",
                dt=GROUND_DT,
                factor=GROUND_FACTOR,
                values=values,
                file_path=str(GROUND_MOTION_FILE.name),
            ),
        ],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="Gravity",
                time_series_id=1,
                element_loads=[UniformElementLoad(element_id=3, wy=GRAVITY_W)],
            ),
            PlainLoadPattern(
                id=2,
                name="Pushover-X",
                time_series_id=2,
                nodal_loads=[
                    NodalLoad(node_id=3, forces=(LATERAL_NODE_LOAD, 0.0, 0.0, 0.0, 0.0, 0.0)),
                    NodalLoad(node_id=4, forces=(LATERAL_NODE_LOAD, 0.0, 0.0, 0.0, 0.0, 0.0)),
                ],
            ),
            UniformExcitationPattern(
                id=3,
                name="GroundMotion-X",
                direction=1,
                accel_series_id=3,
            ),
        ],
        analyses=[
            StaticCase(
                id=1,
                name="Gravity",
                pattern_ids=[1],
                n_steps=10,
                load_factor_increment=0.1,
                system="BandGeneral",
                constraints="Plain",
                integrator="LoadControl",
                algorithm="Newton",
                test="NormDispIncr",
                tolerance=1e-8,
                max_iter=6,
            ),
            PushoverCase(
                id=2,
                name="Push",
                preload_case_ids=[1],
                pattern_ids=[2],
                control_node=3,
                control_dof=1,
                target_disp=PUSH_TARGET,
                step_size=PUSH_STEP,
                base_nodes=[1, 2],
                system="BandGeneral",
                constraints="Plain",
                algorithm="Newton",
                test="NormDispIncr",
                tolerance=1e-8,
                max_iter=6,
            ),
            TransientCase(
                id=3,
                name="Earthquake",
                preload_case_ids=[1],
                pattern_ids=[3],
                dt=ANALYSIS_DT,
                n_steps=ANALYSIS_STEPS,
                system="BandGeneral",
                constraints="Plain",
                integrator="Newmark",
                integrator_params=(0.5, 0.25),
                algorithm="Newton",
                test="NormDispIncr",
                tolerance=1e-8,
                max_iter=10,
                rayleigh_mode1_damping=DAMPING_RATIO,
            ),
        ],
    )


def main() -> None:
    project = build_ex1b_portal2d()
    project.validate_references()
    gm = next(ts for ts in project.time_series if ts.id == 3)
    print(f"Built '{project.meta.name}'")
    print(f"  Gravity + pushover + earthquake cases: {len(project.analyses)}")
    print(f"  Ground motion file: {GROUND_MOTION_FILE.name}")
    print(f"  Reference Tcls: {REFERENCE_PUSH_TCL.name}, {REFERENCE_EQ_TCL.name}")
    print(f"  Record points: {len(gm.values)}, dt = {GROUND_DT}s, factor = {GROUND_FACTOR}")
    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved -> {out_path}")
    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
