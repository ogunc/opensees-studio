"""RC Frame Gravity Analysis — OpenSees Examples Manual, Example 3.

Single-bay, single-storey RC portal frame under gravity (two 180-kip
nodal loads on top joints). Columns are nonlinear forceBeamColumn
elements with the fibre section from the Moment-Curvature example;
the beam is an elasticBeamColumn with stiffness (A, E, Iz) =
(360, 4030, 8640) — matching the Tcl reference at:
https://opensees.berkeley.edu/wiki/index.php?title=RC_Portal_Frame

Model (kip-in-ksi):
                 node 3 ─────── elasticBeam 3 ─────── node 4
                   │                                     │
              forceBC 1                              forceBC 2
                   │                                     │
                 node 1                               node 2
                 (fixed)                              (fixed)

Width 360", height 144", columns fibre-section RC (Concrete01 +
Steel01). Load pattern: 180 kip ↓ at each top node, Linear time series,
LoadControl 0.1 × 10 steps = full gravity.

Expected terminal state (nodes 3 & 4): Uy ≈ -0.0203 in, Ux ≈ 0,
column axial force ≈ 180 kip compression.
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import (
    Concrete01,
    CoordinateGridSystem,
    ElasticBeamColumn,
    ElasticSection,
    FiberSection,
    ForceBeamColumn,
    GridSystem,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    RectangularPatch,
    StaticCase,
    Steel01,
    StraightLayer,
    UnitSystem,
    make_grid_lines,
)
from opensees_studio.services import load_project, save_project


# Frame geometry (inches).
WIDTH = 360.0
HEIGHT = 144.0

# Column section parameters (same as Moment-Curvature example).
COL_WIDTH = 15.0
COL_DEPTH = 24.0
COVER = 1.5
AS_BAR = 0.60

# Material properties (kip, in, ksi).
CONC_CORE_FPC = -6.0
CONC_COVER_FPC = -5.0
STEEL_FY = 60.0
STEEL_E = 3000.0     # note: Tcl uses 3000 (not 30000) for this example
STEEL_B = 0.01

# Beam elastic properties.
BEAM_A = 360.0
BEAM_E = 4030.0
BEAM_IZ = 8640.0

# Gravity load.
P_LOAD = 180.0       # kip, pointing -Y (compression on columns)


def build_rc_frame_gravity() -> Project:
    y1 = COL_DEPTH / 2.0      # 12
    z1 = COL_WIDTH / 2.0      # 7.5

    return Project(
        meta=ProjectMeta(
            name="RC Frame Gravity (OpenSees Ex 3)",
            author="OpenSees Examples Manual",
            description=(
                "1-bay 1-storey portal frame, nonlinear fibre columns + "
                "elastic beam, 10-step LoadControl gravity pushdown."
            ),
            units=UnitSystem.US_IN_KIP,
        ),
        ndm=2, ndf=3,
        coord_systems=[
            CoordinateGridSystem(
                name="Global",
                grid=GridSystem(
                    x_grid_lines=make_grid_lines("X", [0.0, WIDTH]),
                    y_grid_lines=make_grid_lines("Y", [0.0, HEIGHT]),
                    z_grid_lines=make_grid_lines("Z", [0.0]),
                ),
            ),
        ],
        nodes=[
            Node(id=1, name="Base-L",
                 coords=(0.0, 0.0, 0.0),
                 restraint=(True, True, False, False, False, True)),
            Node(id=2, name="Base-R",
                 coords=(WIDTH, 0.0, 0.0),
                 restraint=(True, True, False, False, False, True)),
            Node(id=3, name="Top-L", coords=(0.0, HEIGHT, 0.0)),
            Node(id=4, name="Top-R", coords=(WIDTH, HEIGHT, 0.0)),
        ],
        materials=[
            Concrete01(id=1, name="Core-Conc",
                       fpc=CONC_CORE_FPC, epsc0=-0.004,
                       fpcu=-5.0, epsU=-0.014),
            Concrete01(id=2, name="Cover-Conc",
                       fpc=CONC_COVER_FPC, epsc0=-0.002,
                       fpcu=0.0, epsU=-0.006),
            Steel01(id=3, name="Steel-60",
                    Fy=STEEL_FY, E0=STEEL_E, b=STEEL_B),
        ],
        sections=[
            # Fibre section for the columns (MK recipe).
            FiberSection(
                id=1, name="RC-Col",
                patches=[
                    RectangularPatch(
                        material_id=1, n_fib_y=10, n_fib_z=1,
                        y_i=COVER - y1, z_i=COVER - z1,
                        y_j=y1 - COVER, z_j=z1 - COVER,
                    ),
                    RectangularPatch(
                        material_id=2, n_fib_y=10, n_fib_z=1,
                        y_i=-y1, z_i=z1 - COVER,
                        y_j=y1, z_j=z1,
                    ),
                    RectangularPatch(
                        material_id=2, n_fib_y=10, n_fib_z=1,
                        y_i=-y1, z_i=-z1,
                        y_j=y1, z_j=COVER - z1,
                    ),
                    RectangularPatch(
                        material_id=2, n_fib_y=2, n_fib_z=1,
                        y_i=-y1, z_i=COVER - z1,
                        y_j=COVER - y1, z_j=z1 - COVER,
                    ),
                    RectangularPatch(
                        material_id=2, n_fib_y=2, n_fib_z=1,
                        y_i=y1 - COVER, z_i=COVER - z1,
                        y_j=y1, z_j=z1 - COVER,
                    ),
                ],
                layers=[
                    StraightLayer(
                        material_id=3, n_bars=3, bar_area=AS_BAR,
                        y_start=y1 - COVER, z_start=z1 - COVER,
                        y_end=y1 - COVER, z_end=COVER - z1,
                    ),
                    StraightLayer(
                        material_id=3, n_bars=2, bar_area=AS_BAR,
                        y_start=0.0, z_start=z1 - COVER,
                        y_end=0.0, z_end=COVER - z1,
                    ),
                    StraightLayer(
                        material_id=3, n_bars=3, bar_area=AS_BAR,
                        y_start=COVER - y1, z_start=z1 - COVER,
                        y_end=COVER - y1, z_end=COVER - z1,
                    ),
                ],
            ),
            # Elastic section for the beam.
            ElasticSection(
                id=2, name="Beam",
                E=BEAM_E, A=BEAM_A, Iz=BEAM_IZ,
                Iy=BEAM_IZ, G=1500.0, J=1.0,   # placeholders for 3D round-trip
            ),
        ],
        elements=[
            # Columns — fibre-section forceBeamColumn.
            ForceBeamColumn(id=1, name="Col-L",
                            nodes=(1, 3), section_id=1,
                            integration_points=5, geom_transf="Linear"),
            ForceBeamColumn(id=2, name="Col-R",
                            nodes=(2, 4), section_id=1,
                            integration_points=5, geom_transf="Linear"),
            # Beam — elastic.
            ElasticBeamColumn(id=3, name="Beam",
                              nodes=(3, 4), section_id=2,
                              geom_transf="Linear"),
        ],
        time_series=[LinearTimeSeries(id=1, name="Gravity")],
        load_patterns=[PlainLoadPattern(
            id=1, name="Gravity", time_series_id=1,
            nodal_loads=[
                NodalLoad(node_id=3, forces=(0, -P_LOAD, 0, 0, 0, 0)),
                NodalLoad(node_id=4, forces=(0, -P_LOAD, 0, 0, 0, 0)),
            ],
        )],
        analyses=[StaticCase(
            id=1, name="Gravity",
            pattern_ids=[1],
            n_steps=10, load_factor_increment=0.1,
            system="BandGeneral", constraints="Transformation",
            integrator="LoadControl", algorithm="Newton",
            test="NormDispIncr", tolerance=1e-12, max_iter=10,
        )],
    )


def main() -> None:
    project = build_rc_frame_gravity()
    project.validate_references()
    print(f"Built '{project.meta.name}'")
    print(f"  ndm={project.ndm}, ndf={project.ndf}, units={project.meta.units.value}")
    print(f"  Frame: {WIDTH}in x {HEIGHT}in, P = -{P_LOAD} kip at each top node")
    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved -> {out_path}")
    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
