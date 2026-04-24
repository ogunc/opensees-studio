"""OpenSees Example 1a. 2D Elastic Cantilever Column.

OpenSees Wiki:
https://opensees.berkeley.edu/wiki/index.php?title=OpenSees_Example_1a._2D_Elastic_Cantilever_Column

This model keeps the original Example 1a geometry and packages both
lateral-load variants into a single OpenSees Studio project:

- Gravity preload in 10 static LoadControl steps
- Displacement-controlled static pushover
- UniformExcitation ground-motion analysis using ``BM68elc.acc``

Run from the repository root:

    python examples/ex1a_canti2d.py

Produces ``examples/ex1a_canti2d.osmodel``.
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
    UniformExcitationPattern,
    UnitSystem,
)
from opensees_studio.services import load_project, save_project  # noqa: E402
from opensees_studio.services.peer_record import parse_plain_values  # noqa: E402


COLUMN_HEIGHT = 432.0
TOP_WEIGHT = 2000.0
TOP_MASS_X = 5.18
TOP_MASS_Y = 1.0e-9

AREA = 3_600_000_000.0
E_MODULUS = 4227.0
IZ = 1_080_000.0

PUSH_STEP = 0.1
PUSH_TARGET = 100.0

GROUND_DT = 0.01
GROUND_FACTOR = 1.0
ANALYSIS_DT = 0.02
ANALYSIS_STEPS = 1000
DAMPING_RATIO = 0.02

_ROOT = Path(__file__).resolve().parent
GROUND_MOTION_FILE = _ROOT / "data" / "BM68elc.acc"
REFERENCE_PUSH_TCL = _ROOT / "data" / "Ex1a.Canti2D.Push.tcl.txt"
REFERENCE_EQ_TCL = _ROOT / "data" / "Ex1a.Canti2D.EQ.tcl.txt"


def _ground_motion_values() -> list[float]:
    return parse_plain_values(GROUND_MOTION_FILE)


def build_ex1a_canti2d() -> Project:
    values = _ground_motion_values()

    return Project(
        meta=ProjectMeta(
            name="OpenSees Ex 1a - 2D Elastic Cantilever Column",
            author="OpenSees Wiki / Silvia Mazzoni & Frank McKenna",
            description=(
                "Original Ex 1a elastic cantilever column with shared gravity "
                "preload, static pushover, and BM68elc base-excitation cases."
            ),
            units=UnitSystem.US_IN_KIP,
        ),
        ndm=2,
        ndf=3,
        nodes=[
            Node(
                id=1,
                name="Base",
                coords=(0.0, 0.0, 0.0),
                restraint=(True, True, False, False, False, True),
            ),
            Node(
                id=2,
                name="Top",
                coords=(0.0, COLUMN_HEIGHT, 0.0),
                mass=(TOP_MASS_X, TOP_MASS_Y, 0.0, 0.0, 0.0, 0.0),
            ),
        ],
        sections=[
            ElasticSection(
                id=1,
                name="Column-Elastic",
                E=E_MODULUS,
                A=AREA,
                Iz=IZ,
                Iy=IZ,
                G=1.0,
                J=1.0,
            ),
        ],
        elements=[
            ElasticBeamColumn(
                id=1,
                name="Column",
                nodes=(1, 2),
                section_id=1,
                geom_transf="Linear",
            ),
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
                nodal_loads=[
                    NodalLoad(
                        node_id=2,
                        forces=(0.0, -TOP_WEIGHT, 0.0, 0.0, 0.0, 0.0),
                    ),
                ],
            ),
            PlainLoadPattern(
                id=2,
                name="Pushover-X",
                time_series_id=2,
                nodal_loads=[
                    NodalLoad(
                        node_id=2,
                        forces=(TOP_WEIGHT, 0.0, 0.0, 0.0, 0.0, 0.0),
                    ),
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
                control_node=2,
                control_dof=1,
                target_disp=PUSH_TARGET,
                step_size=PUSH_STEP,
                base_nodes=[1],
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
    project = build_ex1a_canti2d()
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
