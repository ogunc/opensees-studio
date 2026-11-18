"""Three-span continuous girder with an influence-line case and the HL-93 design truck.

Elevation (2D, X-Z plane), spans 20 m + 25 m + 20 m on pins and rollers:

    ▲────────────────▲────────────────────▲────────────────▲
    0               20                   45               65 m

What it shows:

- **Influence-line case** (Analyze → Cases… → InfluenceLine): a unit load
  walked along the eight girder members (two per side span, four in the
  middle one), ten stops each, one linear solve per stop.
- **A vehicle**: the AASHTO LRFD HL-93 design truck, 35 kN + 145 kN + 145 kN
  with axles 4.3 m apart, stored on the case as ``load@offset`` axles in the
  project's force unit (N).
- Display → Influence Line plots any reaction, displacement or member end force
  against the truck's position and moves the truck across both ways.

Run from the repository root:

    python examples/bridge_influence_line.py

Produces ``examples/bridge_influence_line.osmodel``.
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    InfluenceLineCase,
    Node,
    Project,
    ProjectMeta,
    UnitSystem,
)
from opensees_studio.core.analysis import Axle
from opensees_studio.services import load_project, save_project

SPANS = (20.0, 25.0, 20.0)
#: Members per span: two in the side spans, four in the middle one.
DIVISIONS = (2, 4, 2)
PIN = (True, False, True, False, False, False)
ROLLER = (False, False, True, False, False, False)

#: AASHTO LRFD HL-93 design truck in the project's units (N; m behind the front
#: axle), with the minimum axle spacing.
HL93_TRUCK = (
    Axle(load=35_000.0),
    Axle(load=145_000.0, offset=4.3),
    Axle(load=145_000.0, offset=8.6),
)


def build_bridge() -> Project:
    xs = [0.0]
    supports = {0}
    for span, n in zip(SPANS, DIVISIONS, strict=True):
        start = xs[-1]
        xs += [start + span * k / n for k in range(1, n + 1)]
        supports.add(len(xs) - 1)
    nodes = [
        Node(
            id=k + 1,
            coords=(x, 0.0, 0.0),
            restraint=PIN if k == 0 else ROLLER if k in supports else (False,) * 6,
        )
        for k, x in enumerate(xs)
    ]
    elements = [
        ElasticBeamColumn(id=k + 1, nodes=(k + 1, k + 2), section_id=1) for k in range(len(xs) - 1)
    ]
    return Project(
        meta=ProjectMeta(name="Three-span girder", units=UnitSystem.SI_M_N),
        ndm=2,
        ndf=3,
        nodes=nodes,
        # A steel plate girder, about 1.6 m deep.
        sections=[ElasticSection(id=1, name="Girder", E=200e9, A=0.06, Iz=0.025)],
        elements=elements,
        analyses=[
            InfluenceLineCase(
                id=1,
                name="HL-93 truck",
                path=[e.id for e in elements],
                stations=10,
                load=-1.0,
                axles=list(HL93_TRUCK),
            )
        ],
    )


def main() -> None:
    project = build_bridge()
    project.validate_references()
    print(
        f"Built '{project.meta.name}' — {len(project.nodes)} nodes, "
        f"{len(project.elements)} elements, {len(project.analyses)} case."
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
