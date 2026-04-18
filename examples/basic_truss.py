"""Basic Truss Example — OpenSees Examples Manual, Example 1 (exact geometry).

Three-bar pin-jointed truss in 2D under a nodal load at the crown.

Geometry as in the OpenSees Tcl script (units: kip, in)::

    node 1   0.0  0.0       node 4  72.0 96.0
    node 2 144.0  0.0         (crown — loaded here)
    node 3 168.0  0.0
                                           ─── Note the asymmetry:
    Base nodes:                                 node 2 at x=144"
    (0, 0) ───────── (144, 0) ── (168, 0)      node 3 at x=168"
                        ↑            ↑         (only 24" apart!)

This is an asymmetric three-bar truss reaching to a single crown
joint (node 4) at the top. The three bars have different lengths
and two different areas (bar 1 = 10 in², bars 2 and 3 = 5 in²).

Loads (at node 4): Fx = +100 kip, Fy = -50 kip.
Material:          Elastic, E = 3000 ksi.

Analytical solution in kip-in units (verified by OpenSees Tcl run):
    u_x(node 4) ≈ +0.530 in
    u_y(node 4) ≈ -0.178 in

In OpenSees Studio we always work in SI internally (m, N), so we
convert inches → metres (×0.0254), kips → newtons (×4448.22) and
ksi → pascals (×6.895e6). The converted model gives the same
dimensionless solution when you multiply back by the inverse
conversion.

Produces ``examples/basic_truss.osmodel``.
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import (
    CoordinateGridSystem,
    ElasticUniaxial,
    GridSystem,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    StaticCase,
    TrussElement,
    UnitSystem,
    make_grid_lines,
)
from opensees_studio.services import load_project, save_project


# Unit conversions (imperial → SI).
IN_TO_M = 0.0254
KIP_TO_N = 4448.2216
KSI_TO_PA = 6.895e6


def build_basic_truss() -> Project:
    """Three-bar planar truss — Example 1 of the OpenSees user manual.

    Geometry in inches → metres; material E in ksi → Pa; areas in
    in² → m²; loads in kips → N. The SI model is a dimensionless
    scale of the original kip-in model, so the OpenSees solve gives
    the same shape / ratio of displacements.
    """
    # Node coordinates in inches (from Tcl) — converted to metres.
    x1, y1 =   0.0,  0.0
    x2, y2 = 144.0,  0.0
    x3, y3 = 168.0,  0.0
    x4, y4 =  72.0, 96.0

    # Areas in in² — converted to m².
    a1 = 10.0 * IN_TO_M ** 2
    a2 =  5.0 * IN_TO_M ** 2
    a3 =  5.0 * IN_TO_M ** 2

    # Loads in kips — converted to N.
    fx =  100.0 * KIP_TO_N
    fy =  -50.0 * KIP_TO_N

    # Material E in ksi → Pa.
    e = 3000.0 * KSI_TO_PA

    # Grid that covers all four nodes (for the canvas overlay).
    x_ords = [x1 * IN_TO_M, x4 * IN_TO_M, x2 * IN_TO_M, x3 * IN_TO_M]
    y_ords = [y1 * IN_TO_M, y4 * IN_TO_M]

    return Project(
        meta=ProjectMeta(
            name="Basic Truss",
            author="OpenSees Examples Manual - Example 1",
            description="3-bar asymmetric planar truss, linear static analysis.",
            units=UnitSystem.SI_M_N,
        ),
        ndm=2, ndf=2,
        coord_systems=[
            CoordinateGridSystem(
                name="Global",
                grid=GridSystem(
                    x_grid_lines=make_grid_lines("X", x_ords),
                    y_grid_lines=make_grid_lines("Y", y_ords),
                    z_grid_lines=make_grid_lines("Z", [0.0]),
                ),
            ),
        ],
        nodes=[
            Node(id=1, name="Base-L", coords=(x1 * IN_TO_M, y1 * IN_TO_M, 0.0),
                 restraint=(True, True, False, False, False, False)),
            Node(id=2, name="Base-M", coords=(x2 * IN_TO_M, y2 * IN_TO_M, 0.0),
                 restraint=(True, True, False, False, False, False)),
            Node(id=3, name="Base-R", coords=(x3 * IN_TO_M, y3 * IN_TO_M, 0.0),
                 restraint=(True, True, False, False, False, False)),
            Node(id=4, name="Crown",  coords=(x4 * IN_TO_M, y4 * IN_TO_M, 0.0)),
        ],
        materials=[
            ElasticUniaxial(id=1, name="Steel-3000ksi", E=e),
        ],
        sections=[],
        elements=[
            TrussElement(id=1, name="Bar-1-4", nodes=(1, 4),
                         area=a1, material_id=1),
            TrussElement(id=2, name="Bar-2-4", nodes=(2, 4),
                         area=a2, material_id=1),
            TrussElement(id=3, name="Bar-3-4", nodes=(3, 4),
                         area=a3, material_id=1),
        ],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[
            PlainLoadPattern(
                id=1, name="Tip Load",
                time_series_id=1,
                nodal_loads=[
                    NodalLoad(node_id=4, forces=(fx, fy, 0, 0, 0, 0)),
                ],
            ),
        ],
        analyses=[
            StaticCase(id=1, name="Static", pattern_ids=[1], n_steps=1),
        ],
    )


def main() -> None:
    project = build_basic_truss()
    project.validate_references()
    print(f"Built '{project.meta.name}' - {len(project.nodes)} nodes, "
          f"{len(project.elements)} truss bars, {len(project.analyses)} case.")
    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved -> {out_path}")
    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
