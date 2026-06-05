"""Concrete04 (Popovics) fiber-section cantilever.

A single reinforced-concrete column cantilever using Concrete04 as the
fiber material, mirroring the ex2c_canti2d_inelastic_fiber_section example
but with Popovics concrete in place of Kent-Scott-Park (Concrete02).

Run from the repository root:

    python examples/concrete04_cantilever.py

Produces ``examples/concrete04_cantilever.osmodel``.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opensees_studio.core import (  # noqa: E402
    Concrete04,
    FiberSection,
    ForceBeamColumn,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    PushoverCase,
    RectangularPatch,
    StaticCase,
    Steel02,
    StraightLayer,
    UnitSystem,
)
from opensees_studio.services import load_project, save_project  # noqa: E402

# ── Section geometry (SI units: m, N, Pa) ─────────────────────────────────────
L_COL = 3.0          # column height [m]
B_COL = 0.30         # section width  [m]
H_COL = 0.30         # section depth  [m]
COVER = 0.03         # clear cover    [m]

# ── Material parameters (SI) ───────────────────────────────────────────────────
FC = -30e6           # peak compressive strength [Pa]  (negative)
EPSC0 = -0.002       # strain at peak
EPSCU = -0.005       # ultimate compressive strain
# Initial tangent: Ec = 4700 * sqrt(|fc| / 1e6) MPa  (ACI 318 formula, SI)
EC = 4700.0 * math.sqrt(abs(FC) / 1e6) * 1e6   # ≈ 25.74 GPa

FCT = 2.2e6          # tensile strength [Pa]
ET = 1e-4            # ultimate tensile strain

FY = 420e6           # rebar yield stress [Pa]
ES = 200e9           # rebar elastic modulus [Pa]
BS = 0.01            # strain-hardening ratio

NUM_INT_PTS = 5
N_BARS = 4
BAR_AREA = 314e-6    # m² (≈ 20 mm diameter rebar)

P_GRAVITY = -300e3   # gravity axial load [N]  (negative = compressive)
H_LOAD = 50e3        # lateral load at tip [N]

N_GRAVITY = 10
GRAVITY_STEP = 1.0 / N_GRAVITY

PUSH_TARGET = 0.05 * L_COL    # [m]
PUSH_STEP = 0.001 * L_COL     # [m]


def build_concrete04_cantilever() -> Project:
    core_y = H_COL / 2.0 - COVER
    core_z = B_COL / 2.0 - COVER

    return Project(
        meta=ProjectMeta(
            name="Concrete04 Cantilever",
            description=(
                "Single RC column cantilever using Concrete04 (Popovics) "
                "fiber section. Demonstrates the Concrete04 material "
                "end-to-end: schema → model → runner → results."
            ),
            units=UnitSystem.SI_M_N,
        ),
        ndm=2,
        ndf=3,
        nodes=[
            Node(
                id=1, name="Base",
                coords=(0.0, 0.0, 0.0),
                restraint=(True, True, True, False, False, False),
            ),
            Node(id=2, name="Top", coords=(0.0, L_COL, 0.0)),
        ],
        materials=[
            Concrete04(
                id=1, name="C30-Popovics",
                fpc=FC, epsc0=EPSC0, epscu=EPSCU, Ec=EC,
                fct=FCT, et=ET,
            ),
            Steel02(
                id=2, name="Rebar-B500",
                Fy=FY, E0=ES, b=BS,
            ),
        ],
        sections=[
            FiberSection(
                id=1, name="RC-Fiber-C04",
                patches=[
                    RectangularPatch(
                        material_id=1,
                        n_fib_y=8, n_fib_z=4,
                        y_i=-H_COL / 2, z_i=-B_COL / 2,
                        y_j= H_COL / 2, z_j= B_COL / 2,
                    ),
                ],
                layers=[
                    StraightLayer(
                        material_id=2,
                        n_bars=N_BARS, bar_area=BAR_AREA,
                        y_start=-core_y, z_start= core_z,
                        y_end  =-core_y, z_end  =-core_z,
                    ),
                    StraightLayer(
                        material_id=2,
                        n_bars=N_BARS, bar_area=BAR_AREA,
                        y_start= core_y, z_start= core_z,
                        y_end  = core_y, z_end  =-core_z,
                    ),
                ],
            ),
        ],
        elements=[
            ForceBeamColumn(
                id=1, name="Column",
                nodes=(1, 2),
                section_id=1,
                integration_points=NUM_INT_PTS,
                geom_transf="Linear",
            ),
        ],
        time_series=[
            LinearTimeSeries(id=1, name="Gravity"),
            LinearTimeSeries(id=2, name="Lateral"),
        ],
        load_patterns=[
            PlainLoadPattern(
                id=1, name="Gravity", time_series_id=1,
                nodal_loads=[
                    NodalLoad(node_id=2, forces=(0.0, P_GRAVITY, 0.0, 0.0, 0.0, 0.0)),
                ],
            ),
            PlainLoadPattern(
                id=2, name="Pushover-X", time_series_id=2,
                nodal_loads=[
                    NodalLoad(node_id=2, forces=(H_LOAD, 0.0, 0.0, 0.0, 0.0, 0.0)),
                ],
            ),
        ],
        analyses=[
            StaticCase(
                id=1, name="Gravity",
                pattern_ids=[1],
                n_steps=N_GRAVITY,
                load_factor_increment=GRAVITY_STEP,
                system="BandGeneral",
                constraints="Plain",
                integrator="LoadControl",
                algorithm="Newton",
                test="NormDispIncr",
                tolerance=1e-8,
                max_iter=10,
            ),
            PushoverCase(
                id=2, name="Push-X",
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
                test="EnergyIncr",
                tolerance=1e-8,
                max_iter=10,
            ),
        ],
    )


def main() -> None:
    project = build_concrete04_cantilever()
    project.validate_references()
    print(f"Built '{project.meta.name}'")
    print(f"  L={L_COL} m, BxH={B_COL}x{H_COL} m, Ec={EC/1e9:.2f} GPa")
    print(f"  Gravity + pushover cases: {len(project.analyses)}")
    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved -> {out_path}")
    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
