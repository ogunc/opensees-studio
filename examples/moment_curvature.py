"""Moment-Curvature Example — OpenSees Examples Manual, Example 2.

Reinforced-concrete column cross-section, fibre discretisation, axial
preload + monotonic moment pushover. Mirrors the OpenSees Tcl script
at https://opensees.berkeley.edu/wiki/index.php?title=Moment_Curvature_Example

Model
-----
Two coincident nodes linked by a ``zeroLengthSection`` carrying the
RC fibre section. Node 1 is fully restrained; node 2 is free in Ux
(so axial can shorten) and Rz (the curvature DOF). A constant axial
load P = -180 kip is applied first via LoadControl(0); then a
linear reference moment pattern (Mz = 1 kip·in) is added and
DisplacementControl on DOF 3 ramps the curvature to μ·Ky where
μ = 15 and Ky is the elastic yield curvature estimate.

Units: kip, in, ksi (UnitSystem.US_IN_KIP).

GUI walkthrough: File → Open → moment_curvature.osmodel, Options →
Set Display Units → US (in, kip, kip·s²/in, s, ksi), Analyze → Run →
MK, Display → Show Pushover Curve.
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import (
    Concrete01,
    ConstantTimeSeries,
    CoordinateGridSystem,
    FiberSection,
    GridSystem,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    PushoverCase,
    RectangularPatch,
    Steel01,
    StraightLayer,
    UnitSystem,
    ZeroLengthSectionElement,
    make_grid_lines,
)
from opensees_studio.services import load_project, save_project


# Cross-section parameters (kip-in-ksi, from the Tcl example).
COL_WIDTH = 15.0     # z-direction dimension
COL_DEPTH = 24.0     # y-direction dimension
COVER = 1.5
AS_BAR = 0.60        # area of one #7 rebar

FY = 60.0            # steel yield stress, ksi
E_STEEL = 30000.0    # steel Young's modulus, ksi
HARDENING = 0.01     # strain-hardening ratio

P_AXIAL = -180.0     # kip, compression
MU = 15              # target curvature ductility
NUM_INCR = 100       # DisplacementControl increments


def build_moment_curvature() -> Project:
    """Build the OpenSees Example 2 Moment-Curvature project."""
    y1 = COL_DEPTH / 2.0     # 12
    z1 = COL_WIDTH / 2.0     # 7.5
    d = COL_DEPTH - COVER    # 22.5

    # Yield curvature estimate, assumed elastic + top/bottom steel only.
    eps_y = FY / E_STEEL                # 0.002
    ky = eps_y / (0.7 * d)              # ≈ 1.27e-4
    max_k = ky * MU                     # ≈ 1.905e-3
    d_k = max_k / NUM_INCR              # per-step curvature increment

    return Project(
        meta=ProjectMeta(
            name="Moment-Curvature (OpenSees Ex 2)",
            author="OpenSees Examples Manual",
            description=(
                "RC column fibre section — constant axial P + DisplacementControl "
                "curvature pushover. Kip-in-ksi units throughout."
            ),
            units=UnitSystem.US_IN_KIP,
        ),
        ndm=2, ndf=3,
        coord_systems=[
            # A tiny grid at the section origin so the two coincident
            # nodes have a visual anchor in the canvas.
            CoordinateGridSystem(
                name="Global",
                grid=GridSystem(
                    x_grid_lines=make_grid_lines("X", [0.0]),
                    y_grid_lines=make_grid_lines("Y", [0.0]),
                    z_grid_lines=make_grid_lines("Z", [0.0]),
                ),
            ),
        ],
        nodes=[
            # Node 1 — fully clamped.
            Node(id=1, name="Support",
                 coords=(0.0, 0.0, 0.0),
                 restraint=(True, True, False, False, False, True)),
            # Node 2 — free in Ux and Rz (axial + curvature).
            Node(id=2, name="Crown",
                 coords=(0.0, 0.0, 0.0),
                 restraint=(False, True, False, False, False, False)),
        ],
        materials=[
            # Core concrete — confined (tag 1).
            Concrete01(id=1, name="Core-Conc",
                       fpc=-6.0, epsc0=-0.004,
                       fpcu=-5.0, epsU=-0.014),
            # Cover concrete — unconfined (tag 2).
            Concrete01(id=2, name="Cover-Conc",
                       fpc=-5.0, epsc0=-0.002,
                       fpcu=0.0, epsU=-0.006),
            # Reinforcing steel — bilinear hardening (tag 3).
            Steel01(id=3, name="Steel-60",
                    Fy=FY, E0=E_STEEL, b=HARDENING),
        ],
        sections=[
            FiberSection(
                id=1, name="RC-Column",
                patches=[
                    # Core — confined concrete inside the rebar ring.
                    RectangularPatch(
                        material_id=1, n_fib_y=10, n_fib_z=1,
                        y_i=COVER - y1, z_i=COVER - z1,
                        y_j=y1 - COVER, z_j=z1 - COVER,
                    ),
                    # Top cover (unconfined).
                    RectangularPatch(
                        material_id=2, n_fib_y=10, n_fib_z=1,
                        y_i=-y1, z_i=z1 - COVER,
                        y_j=y1, z_j=z1,
                    ),
                    # Bottom cover.
                    RectangularPatch(
                        material_id=2, n_fib_y=10, n_fib_z=1,
                        y_i=-y1, z_i=-z1,
                        y_j=y1, z_j=COVER - z1,
                    ),
                    # Left cover.
                    RectangularPatch(
                        material_id=2, n_fib_y=2, n_fib_z=1,
                        y_i=-y1, z_i=COVER - z1,
                        y_j=COVER - y1, z_j=z1 - COVER,
                    ),
                    # Right cover.
                    RectangularPatch(
                        material_id=2, n_fib_y=2, n_fib_z=1,
                        y_i=y1 - COVER, z_i=COVER - z1,
                        y_j=y1, z_j=z1 - COVER,
                    ),
                ],
                layers=[
                    # Top rebar (3 × #7).
                    StraightLayer(
                        material_id=3, n_bars=3, bar_area=AS_BAR,
                        y_start=y1 - COVER, z_start=z1 - COVER,
                        y_end=y1 - COVER, z_end=COVER - z1,
                    ),
                    # Middle rebar (2 × #7).
                    StraightLayer(
                        material_id=3, n_bars=2, bar_area=AS_BAR,
                        y_start=0.0, z_start=z1 - COVER,
                        y_end=0.0, z_end=COVER - z1,
                    ),
                    # Bottom rebar (3 × #7).
                    StraightLayer(
                        material_id=3, n_bars=3, bar_area=AS_BAR,
                        y_start=COVER - y1, z_start=z1 - COVER,
                        y_end=COVER - y1, z_end=COVER - z1,
                    ),
                ],
            ),
        ],
        elements=[
            ZeroLengthSectionElement(
                id=1, name="MK-Link",
                nodes=(1, 2), section_id=1,
            ),
        ],
        time_series=[
            ConstantTimeSeries(id=1, name="AxialP"),
            LinearTimeSeries(id=2, name="RefMoment"),
        ],
        load_patterns=[
            # Constant axial preload at node 2 — Fx = P (compression).
            PlainLoadPattern(
                id=1, name="AxialP",
                time_series_id=1,
                nodal_loads=[
                    NodalLoad(node_id=2,
                              forces=(P_AXIAL, 0, 0, 0, 0, 0)),
                ],
            ),
            # Linear reference moment — Mz = 1.0, DisplacementControl
            # scales this as it ramps curvature.
            PlainLoadPattern(
                id=2, name="RefMoment",
                time_series_id=2,
                nodal_loads=[
                    NodalLoad(node_id=2,
                              forces=(0, 0, 0, 0, 0, 1.0)),
                ],
            ),
        ],
        analyses=[
            PushoverCase(
                id=1, name="MK",
                pattern_ids=[1, 2],
                control_node=2, control_dof=3,    # Rz = curvature
                target_disp=max_k,
                step_size=d_k,
                base_nodes=[1],
                test="NormUnbalance",
                tolerance=1e-9, max_iter=25,
            ),
        ],
    )


def main() -> None:
    project = build_moment_curvature()
    project.validate_references()
    y1 = COL_DEPTH / 2.0
    eps_y = FY / E_STEEL
    ky = eps_y / (0.7 * (COL_DEPTH - COVER))
    print(f"Built '{project.meta.name}'")
    print(f"  ndm={project.ndm}, ndf={project.ndf}, units={project.meta.units.value}")
    print(f"  Estimated yield curvature Ky = {ky:.4e} 1/in")
    print(f"  Target (mu * Ky) = {ky * MU:.4e} 1/in   (mu = {MU})")

    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved -> {out_path}")

    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
