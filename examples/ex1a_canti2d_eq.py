"""Time History Analysis of a 2D Elastic Cantilever Column.

OpenSees Wiki tutorial / examples-manual variant:
https://opensees.berkeley.edu/wiki/index.php?title=Time_History_Analysis_of_a_2D_Elastic_Cantilever_Column

This example mirrors ``Ex1a.Canti2D.EQ.modif.tcl`` but expresses it in
OpenSees Studio's declarative project model:

- 2D frame (ndm=2, ndf=3), kip-in-sec units
- One elastic cantilever column, fixed at the base
- Gravity preload applied in 10 static LoadControl steps
- Loma Prieta horizontal record ``A10000`` imported from a plain-text list
- UniformExcitation in DOF 1 (+X)
- Newmark average-acceleration transient with 2% mode-1 stiffness damping

Run from the repository root:

    python examples/ex1a_canti2d_eq.py

Produces ``examples/ex1a_canti2d_eq.osmodel``.
"""

from __future__ import annotations

from pathlib import Path
import sys

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PathTimeSeries,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    StaticCase,
    TransientCase,
    UniformExcitationPattern,
    UnitSystem,
)
from opensees_studio.services import load_project, save_project
from opensees_studio.services.peer_record import parse_plain_values


G = 386.0
COLUMN_HEIGHT = 432.0
TOP_WEIGHT = 2000.0
TOP_MASS_X = 5.18

AREA = 3600.0
E_MODULUS = 3225.0
IZ = 1_080_000.0

GROUND_DT = 0.005
ANALYSIS_DT = 0.01
DAMPING_RATIO = 0.02

_ROOT = Path(__file__).resolve().parent
GROUND_MOTION_FILE = _ROOT / "data" / "A10000.txt"
REFERENCE_TCL = _ROOT / "data" / "Ex1a.Canti2D.EQ.modif.tcl.txt"


def _ground_motion_values() -> list[float]:
    return parse_plain_values(GROUND_MOTION_FILE)


def build_ex1a_canti2d_eq() -> Project:
    values = _ground_motion_values()
    n_steps = len(values) // 2

    return Project(
        meta=ProjectMeta(
            name="2D Elastic Cantilever EQ (OpenSees Ex 1a)",
            author="OpenSees Wiki / Examples Manual",
            description=(
                "Elastic 2D cantilever with gravity preload + horizontal "
                "UniformExcitation time history from the A10000 record."
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
                mass=(TOP_MASS_X, 0.0, 0.0, 0.0, 0.0, 0.0),
            ),
        ],
        sections=[
            ElasticSection(
                id=1,
                name="RC-Elastic",
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
            PathTimeSeries(
                id=2,
                name="A10000",
                dt=GROUND_DT,
                factor=G,
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
            UniformExcitationPattern(
                id=2,
                name="GroundMotion-X",
                direction=1,
                accel_series_id=2,
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
                algorithm="Linear",
                test="NormDispIncr",
                tolerance=1e-12,
                max_iter=10,
            ),
            TransientCase(
                id=2,
                name="Earthquake",
                preload_case_ids=[1],
                pattern_ids=[2],
                dt=ANALYSIS_DT,
                n_steps=n_steps,
                system="BandGeneral",
                constraints="Plain",
                integrator="Newmark",
                integrator_params=(0.5, 0.25),
                algorithm="Linear",
                test="NormDispIncr",
                tolerance=1e-12,
                max_iter=10,
                rayleigh_mode1_damping=DAMPING_RATIO,
            ),
        ],
    )


def main() -> None:
    project = build_ex1a_canti2d_eq()
    project.validate_references()
    gm = next(ts for ts in project.time_series if ts.id == 2)
    print(f"Built '{project.meta.name}'")
    print(f"  Ground motion file: {GROUND_MOTION_FILE.name}")
    print(f"  Reference Tcl: {REFERENCE_TCL.name}")
    print(f"  Points: {len(gm.values)}, dt = {GROUND_DT}s, factor = g = {G}")
    print(
        f"  Transient: {project.analyses[1].n_steps} steps at "
        f"{ANALYSIS_DT}s (every second record point)"
    )
    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved -> {out_path}")
    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
