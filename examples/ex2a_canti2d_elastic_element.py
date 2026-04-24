"""OpenSees Example 2a. Elastic Cantilever Column with variables.

OpenSees Wiki:
https://opensees.berkeley.edu/wiki/index.php?title=OpenSees_Example_2a._Elastic_Cantilever_Column_with_variables

This example mirrors the Tcl tutorial's teaching goal: the model is
defined from a small set of named parameters, then derived quantities
such as mass, section area, and stiffness are computed from them.

The resulting OpenSees Studio project contains:

- gravity preload
- static pushover
- earthquake base excitation with ``BM68elc.acc``

Run from the repository root:

    python examples/ex2a_canti2d_elastic_element.py

Produces ``examples/ex2a_canti2d_elastic_element.osmodel``.
"""

from __future__ import annotations

from pathlib import Path
import math
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


# Geometry and loading variables from the Tcl tutorial.
L_COL = 432.0
WEIGHT = 2000.0
H_COL = 60.0
B_COL = 60.0
G_ACCEL = 386.4
FC = -4.0

# Derived properties.
P_COL = WEIGHT
MASS = P_COL / G_ACCEL
A_COL = B_COL * H_COL * 1000.0
IZ_COL = (1.0 / 12.0) * B_COL * H_COL**3
E_C = 57.0 * math.sqrt(-FC * 1000.0)

# Analysis variables.
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
REFERENCE_PUSH_TCL = _ROOT / "data" / "Ex2a.Canti2D.ElasticElement.Push.tcl.txt"
REFERENCE_EQ_TCL = _ROOT / "data" / "Ex2a.Canti2D.ElasticElement.EQ.tcl.txt"


def _ground_motion_values() -> list[float]:
    return parse_plain_values(GROUND_MOTION_FILE)


def build_ex2a_canti2d_elastic_element() -> Project:
    values = _ground_motion_values()

    return Project(
        meta=ProjectMeta(
            name="OpenSees Ex 2a - Elastic Cantilever Column with Variables",
            author="OpenSees Wiki / Silvia Mazzoni & Frank McKenna",
            description=(
                "Variable-driven elastic cantilever model with derived mass, "
                "section, pushover, and earthquake analysis parameters."
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
        sections=[
            ElasticSection(
                id=1,
                name="Elastic-Column",
                E=E_C,
                A=A_COL,
                Iz=IZ_COL,
                Iy=IZ_COL,
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
                    NodalLoad(node_id=2, forces=(0.0, -P_COL, 0.0, 0.0, 0.0, 0.0)),
                ],
            ),
            PlainLoadPattern(
                id=200,
                name="Pushover-X",
                time_series_id=2,
                nodal_loads=[
                    NodalLoad(node_id=2, forces=(H_LOAD, 0.0, 0.0, 0.0, 0.0, 0.0)),
                ],
            ),
            UniformExcitationPattern(
                id=400,
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
    project = build_ex2a_canti2d_elastic_element()
    project.validate_references()
    gm = next(ts for ts in project.time_series if ts.id == 3)
    print(f"Built '{project.meta.name}'")
    print(f"  LCol={L_COL}, Weight={WEIGHT}, ACol={A_COL:.1f}, Ec={E_C:.3f}")
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
