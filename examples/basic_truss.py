"""Basic Truss Example — OpenSees Examples Manual, Example 1.

Three-bar pin-jointed truss in 2D under a nodal load at the crown.

Geometry (units: inches, kips)::

    Node 1 ── inclined ─── Node 4 ───── horizontal ───── Node 3
      \\                     |                            /
       \\                  inclined                      /
        \\                   |                          /
         Node 2 at origin (pinned).

Wait — this is the canonical example layout::

        Node 4 (top)                   ← load here (Px=100, Py=-50)
       /  |  \\
      /   |   \\
     /    |    \\
    1 ────2────3                        ← pinned supports
       L=72" each
    H=96"

- 4 nodes (3 pinned + 1 free)
- 3 truss bars meeting at node 4
- Steel E = 3000 ksi, A = 10 in² (members 1, 2), A = 5 in² (member 3)
- Load at node 4: (100, -50) kips
- Static analysis, linear solve

Expected: node 4 displacement ≈ (+21 mm, -4.6 mm) in SI → (+0.82 in, -0.18 in).
The OpenSees runner reproduces this when the model is run through
Analyze → Cases → Run "Static".

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


def build_basic_truss() -> Project:
    """Three-bar planar truss — Example 1 of the OpenSees user manual."""
    return Project(
        meta=ProjectMeta(
            name="Basic Truss",
            author="OpenSees Examples Manual - Example 1",
            description="3-bar planar truss, linear static analysis.",
            units=UnitSystem.SI_M_N,       # We use SI for internal consistency
        ),
        ndm=2, ndf=2,
        coord_systems=[
            CoordinateGridSystem(
                name="Global",
                grid=GridSystem(
                    x_grid_lines=make_grid_lines("X", [0.0, 72.0 * 0.0254, 144.0 * 0.0254]),
                    y_grid_lines=make_grid_lines("Y", [0.0, 96.0 * 0.0254]),
                    z_grid_lines=make_grid_lines("Z", [0.0]),
                ),
            ),
        ],
        nodes=[
            # Base nodes — pinned (fully restrained in 2D → both DOFs)
            Node(id=1, name="Base-L", coords=(0.0,           0.0, 0.0),
                 restraint=(True, True, False, False, False, False)),
            Node(id=2, name="Base-M", coords=(72.0 * 0.0254, 0.0, 0.0),
                 restraint=(True, True, False, False, False, False)),
            Node(id=3, name="Base-R", coords=(144.0 * 0.0254, 0.0, 0.0),
                 restraint=(True, True, False, False, False, False)),
            # Crown node — free, will receive the load.
            Node(id=4, name="Crown",  coords=(72.0 * 0.0254, 96.0 * 0.0254, 0.0)),
        ],
        materials=[
            # 3000 ksi ≈ 20.68 GPa
            ElasticUniaxial(id=1, name="Steel-3000ksi", E=20.68e9),
        ],
        sections=[],   # truss elements carry area directly, no section needed
        elements=[
            # Areas: 10 in² ≈ 6.452e-3 m²; 5 in² ≈ 3.226e-3 m²
            TrussElement(id=1, name="Bar-1", nodes=(1, 4),
                         area=6.452e-3, material_id=1),
            TrussElement(id=2, name="Bar-2", nodes=(2, 4),
                         area=6.452e-3, material_id=1),
            TrussElement(id=3, name="Bar-3", nodes=(3, 4),
                         area=3.226e-3, material_id=1),
        ],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[
            PlainLoadPattern(
                id=1, name="Tip Load",
                time_series_id=1,
                # 100 kip ≈ 444.8 kN horizontal; 50 kip ≈ 222.4 kN downward.
                nodal_loads=[
                    NodalLoad(node_id=4, forces=(444.8e3, -222.4e3, 0, 0, 0, 0)),
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
