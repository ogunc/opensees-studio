"""Two-bay, two-storey steel moment frame, ready for Design → Steel Frame Check.

Elevation (X-Z plane, a 2D frame), bays 6 m, storeys 4 m:

    z
    8 ┼──── W16X31 ────┼──── W16X31 ────┼
      │                │                │
      W10X49        W10X49           W10X49
    4 ┼──── W16X31 ────┼──── W16X31 ────┼
      │                │                │
    0 ┼ fixed          ┼ fixed          ┼ fixed ── x
      0                6               12

What it shows:

- **AISC sections by name.** Every section is built from the AISC v16 table
  (``core.aisc``) and keeps the shape's name, which is how the steel check
  knows which shape to design with.
- **Loads and combinations.** DEAD (self weight + 25 kN/m on the beams), LIVE
  (20 kN/m on the beams) and WIND (lateral forces at the floors), combined as
  1.4D, 1.2D + 1.6L and 1.2D + 1.0W + L.
- **Design settings saved with the project.** LRFD, Fy = 345 MPa, the beams
  braced at thirds of their span (Lb = 2 m), the ASCE 7 drift limit 0.020 h.
- **Storeys** from the Z grid, for the storey drift check.

Run from the repository root:

    python examples/steel_frame_design.py

Produces ``examples/steel_frame_design.osmodel``. Then: Analyze → Run All
Cases, Design → Steel Frame Check (see ``docs/tutorials/01-steel-frame-design.md``).
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import (
    CoordinateGridSystem,
    ElasticBeamColumn,
    GridSystem,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    StaticCase,
    UniformElementLoad,
    UnitSystem,
    make_grid_lines,
)
from opensees_studio.core.aisc import get_shape, shape_to_elastic_section
from opensees_studio.core.combinations import CombinationTerm, LoadCombination
from opensees_studio.core.design.settings import DesignSettings, SteelMemberDesign
from opensees_studio.core.storeys import storeys_from_grid
from opensees_studio.services import load_project, save_project

X_LINES = (0.0, 6.0, 12.0)
Z_LINES = (0.0, 4.0, 8.0)
E, G = 200e9, 77e9  # Pa
STEEL_WEIGHT = 77_000.0  # N/m³

COLUMN, BEAM = 1, 2
DEAD, LIVE, WIND = 1, 2, 3

SUPERIMPOSED_DEAD = 25_000.0  # N/m on the beams
LIVE_LOAD = 20_000.0  # N/m on the beams
WIND_FORCES = (60_000.0, 40_000.0)  # N at the first and second floor


def build_steel_frame() -> Project:
    nodes: list[Node] = []
    joint: dict[tuple[int, int], int] = {}
    nid = 1
    for k, z in enumerate(Z_LINES):
        for i, x in enumerate(X_LINES):
            fixed = k == 0
            nodes.append(
                Node(
                    id=nid,
                    coords=(x, 0.0, z),
                    restraint=(fixed, False, fixed, False, fixed, False),
                )
            )
            joint[(i, k)] = nid
            nid += 1

    elements: list[ElasticBeamColumn] = []
    columns: list[int] = []
    beams: list[int] = []
    for k in range(1, len(Z_LINES)):
        for i in range(len(X_LINES)):
            eid = len(elements) + 1
            elements.append(
                ElasticBeamColumn(
                    id=eid,
                    name=f"C{k}-{i + 1}",
                    nodes=(joint[(i, k - 1)], joint[(i, k)]),
                    section_id=COLUMN,
                )
            )
            columns.append(eid)
        for i in range(len(X_LINES) - 1):
            eid = len(elements) + 1
            elements.append(
                ElasticBeamColumn(
                    id=eid,
                    name=f"B{k}-{i + 1}",
                    nodes=(joint[(i, k)], joint[(i + 1, k)]),
                    section_id=BEAM,
                )
            )
            beams.append(eid)

    def section(sid: int, name: str):  # type: ignore[no-untyped-def]
        built = shape_to_elastic_section(
            get_shape(name), elastic_modulus=E, shear_modulus=G, section_id=sid, ndm=2
        )
        return built.model_copy(update={"unit_weight": STEEL_WEIGHT})

    grid = CoordinateGridSystem(
        name="Global",
        grid=GridSystem(
            x_grid_lines=make_grid_lines("X", list(X_LINES)),
            z_grid_lines=make_grid_lines("Z", list(Z_LINES)),
        ),
    )
    floors = [joint[(0, k)] for k in range(1, len(Z_LINES))]
    return Project(
        meta=ProjectMeta(name="Steel frame design", units=UnitSystem.SI_M_N),
        ndm=2,
        ndf=3,
        coord_systems=[grid],
        storeys=storeys_from_grid(grid),
        nodes=nodes,
        sections=[section(COLUMN, "W10X49"), section(BEAM, "W16X31")],
        elements=elements,
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[
            PlainLoadPattern(
                id=DEAD,
                name="DEAD",
                time_series_id=1,
                self_weight=1.0,
                element_loads=[
                    UniformElementLoad(element_id=e, wy=-SUPERIMPOSED_DEAD) for e in beams
                ],
            ),
            PlainLoadPattern(
                id=LIVE,
                name="LIVE",
                time_series_id=1,
                element_loads=[UniformElementLoad(element_id=e, wy=-LIVE_LOAD) for e in beams],
            ),
            PlainLoadPattern(
                id=WIND,
                name="WIND",
                time_series_id=1,
                nodal_loads=[
                    NodalLoad(node_id=n, forces=(f, 0.0, 0.0, 0.0, 0.0, 0.0))
                    for n, f in zip(floors, WIND_FORCES, strict=True)
                ],
            ),
        ],
        analyses=[
            StaticCase(id=DEAD, name="DEAD", pattern_ids=[DEAD]),
            StaticCase(id=LIVE, name="LIVE", pattern_ids=[LIVE]),
            StaticCase(id=WIND, name="WIND", pattern_ids=[WIND]),
        ],
        combinations=[
            LoadCombination(id=1, name="1.4D", terms=[CombinationTerm(ref_id=DEAD, factor=1.4)]),
            LoadCombination(
                id=2,
                name="1.2D+1.6L",
                terms=[
                    CombinationTerm(ref_id=DEAD, factor=1.2),
                    CombinationTerm(ref_id=LIVE, factor=1.6),
                ],
            ),
            LoadCombination(
                id=3,
                name="1.2D+1.0W+L",
                terms=[
                    CombinationTerm(ref_id=DEAD, factor=1.2),
                    CombinationTerm(ref_id=WIND, factor=1.0),
                    CombinationTerm(ref_id=LIVE, factor=1.0),
                ],
            ),
        ],
        design=DesignSettings(
            fy=345e6,
            # Beams braced at thirds of the span by the floor joists.
            members=[SteelMemberDesign(element_id=e, length_ltb=2.0) for e in beams],
        ),
    )


def main() -> None:
    project = build_steel_frame()
    project.validate_references()
    print(
        f"Built '{project.meta.name}' — {len(project.nodes)} nodes, "
        f"{len(project.elements)} elements, {len(project.analyses)} cases, "
        f"{len(project.combinations)} combinations."
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
