"""OpenSees Example 2c. Nonlinear Cantilever Column: Inelastic Fiber Section.

OpenSees Wiki:
https://opensees.berkeley.edu/wiki/index.php?title=OpenSees_Example_2c._Nonlinear_Cantilever_Column:_Inelastic_Uniaxial_Materials_in_Fiber_Section

This example replaces the aggregated uniaxial section of Ex2b with a
fiber section built from inelastic uniaxial materials. The fiber section
couples axial and flexural behavior naturally through the section
integration.

Run from the repository root:

    python examples/ex2c_canti2d_inelastic_fiber_section.py

Produces ``examples/ex2c_canti2d_inelastic_fiber_section.osmodel``.
"""

from __future__ import annotations

from pathlib import Path
import math
import sys

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opensees_studio.core import (  # noqa: E402
    Concrete02,
    FiberSection,
    ForceBeamColumn,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PathTimeSeries,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    PushoverCase,
    RectangularPatch,
    Steel02,
    StraightLayer,
    TransientCase,
    StaticCase,
    UniformExcitationPattern,
    UnitSystem,
)
from opensees_studio.services import load_project, save_project  # noqa: E402
from opensees_studio.services.peer_record import parse_plain_values  # noqa: E402


L_COL = 432.0
WEIGHT = 2000.0
H_COL = 60.0
B_COL = 60.0
G_ACCEL = 386.4

P_COL = WEIGHT
MASS = P_COL / G_ACCEL
A_COL = B_COL * H_COL
IZ_COL = (1.0 / 12.0) * B_COL * H_COL**3

COVER_COL = 5.0
NUM_BARS_COL = 5
BAR_AREA_COL = 2.25

FC = -4.0
EC = 57.0 * math.sqrt(-FC * 1000.0)
FC1U = FC
EPS1U = -0.003
FC2U = 0.2 * FC1U
EPS2U = -0.01
LAMBDA = 0.1
FTU = -0.14 * FC1U
ETS = FTU / 0.002

FY = 66.8
ES = 29000.0
BS = 0.01
R0 = 18.0
CR1 = 0.925
CR2 = 0.15

NUM_INT_PTS = 5

N_GRAVITY = 10
GRAVITY_STEP = 1.0 / N_GRAVITY

PUSH_TARGET = 0.01 * L_COL
PUSH_STEP = 0.001 * L_COL
H_LOAD = WEIGHT

GROUND_DT = 0.01
GROUND_FACTOR = 1.0
ANALYSIS_DT = 0.01
ANALYSIS_STEPS = 1000
DAMPING_RATIO = 0.02

_ROOT = Path(__file__).resolve().parent
GROUND_MOTION_FILE = _ROOT / "data" / "BM68elc.acc"
REFERENCE_PUSH_TCL = _ROOT / "data" / "Ex2c.Canti2D.InelasticFiberSection.Push.tcl.txt"
REFERENCE_EQ_TCL = _ROOT / "data" / "Ex2c.Canti2D.InelasticFiberSection.EQ.tcl.txt"


def _ground_motion_values() -> list[float]:
    return parse_plain_values(GROUND_MOTION_FILE)


def build_ex2c_canti2d_inelastic_fiber_section() -> Project:
    values = _ground_motion_values()
    cover_y = H_COL / 2.0
    cover_z = B_COL / 2.0
    core_y = cover_y - COVER_COL
    core_z = cover_z - COVER_COL

    return Project(
        meta=ProjectMeta(
            name="OpenSees Ex 2c - Inelastic Fiber-Section Cantilever",
            author="OpenSees Wiki / Silvia Mazzoni & Frank McKenna",
            description=(
                "Nonlinear cantilever with a fiber section built from "
                "Concrete02 and Steel02 uniaxial materials."
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
                coords=(0.0, L_COL, 0.0),
                mass=(MASS, 1.0e-9, 0.0, 0.0, 0.0, 0.0),
            ),
        ],
        materials=[
            Concrete02(
                id=1,
                name="Cover-Concrete",
                fpc=FC1U,
                epsc0=EPS1U,
                fpcu=FC2U,
                epsU=EPS2U,
                lambda_=LAMBDA,
                ft=FTU,
                Ets=ETS,
            ),
            Steel02(
                id=2,
                name="Rebar-Steel",
                Fy=FY,
                E0=ES,
                b=BS,
                R0=R0,
                cR1=CR1,
                cR2=CR2,
            ),
        ],
        sections=[
            FiberSection(
                id=1,
                name="RC-Fiber-Section",
                patches=[
                    RectangularPatch(
                        material_id=1,
                        n_fib_y=16,
                        n_fib_z=4,
                        y_i=-cover_y,
                        z_i=-cover_z,
                        y_j=cover_y,
                        z_j=cover_z,
                    ),
                ],
                layers=[
                    StraightLayer(
                        material_id=2,
                        n_bars=NUM_BARS_COL,
                        bar_area=BAR_AREA_COL,
                        y_start=-core_y,
                        z_start=core_z,
                        y_end=-core_y,
                        z_end=-core_z,
                    ),
                    StraightLayer(
                        material_id=2,
                        n_bars=NUM_BARS_COL,
                        bar_area=BAR_AREA_COL,
                        y_start=core_y,
                        z_start=core_z,
                        y_end=core_y,
                        z_end=-core_z,
                    ),
                ],
            ),
        ],
        elements=[
            ForceBeamColumn(
                id=1,
                name="Column",
                nodes=(1, 2),
                section_id=1,
                integration_points=NUM_INT_PTS,
                geom_transf="Linear",
            ),
        ],
        time_series=[
            LinearTimeSeries(id=1, name="Gravity"),
            LinearTimeSeries(id=200, name="Lateral"),
            PathTimeSeries(
                id=400,
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
                    NodalLoad(node_id=2, forces=(0.0, -P_COL, 0.0, 0.0, 0.0, 0.0)),
                ],
            ),
            PlainLoadPattern(
                id=200,
                name="Pushover-X",
                time_series_id=200,
                nodal_loads=[
                    NodalLoad(node_id=2, forces=(H_LOAD, 0.0, 0.0, 0.0, 0.0, 0.0)),
                ],
            ),
            UniformExcitationPattern(
                id=400,
                name="GroundMotion-X",
                direction=1,
                accel_series_id=400,
            ),
        ],
        analyses=[
            StaticCase(
                id=1,
                name="Gravity",
                pattern_ids=[1],
                n_steps=N_GRAVITY,
                load_factor_increment=GRAVITY_STEP,
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
                pattern_ids=[200],
                control_node=2,
                control_dof=1,
                target_disp=PUSH_TARGET,
                step_size=PUSH_STEP,
                base_nodes=[1],
                system="BandGeneral",
                constraints="Plain",
                algorithm="Newton",
                test="EnergyIncr",
                tolerance=1e-8,
                max_iter=6,
            ),
            TransientCase(
                id=3,
                name="Earthquake",
                preload_case_ids=[1],
                pattern_ids=[400],
                dt=ANALYSIS_DT,
                n_steps=ANALYSIS_STEPS,
                system="SparseGeneral",
                constraints="Transformation",
                integrator="Newmark",
                integrator_params=(0.5, 0.25),
                algorithm="ModifiedNewton",
                test="EnergyIncr",
                tolerance=1e-8,
                max_iter=10,
                rayleigh_mode1_damping=DAMPING_RATIO,
            ),
        ],
    )


def main() -> None:
    project = build_ex2c_canti2d_inelastic_fiber_section()
    project.validate_references()
    gm = next(ts for ts in project.time_series if ts.id == 400)
    print(f"Built '{project.meta.name}'")
    print(
        f"  LCol={L_COL}, ACol={A_COL:.1f}, Iz={IZ_COL:.1f}, "
        f"bars/layer={NUM_BARS_COL}, bar area={BAR_AREA_COL}"
    )
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
