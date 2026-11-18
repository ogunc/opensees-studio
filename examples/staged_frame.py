"""Staged construction of a two-storey concrete frame, and the same frame loaded at once.

A 2D frame (X-Z plane), two bays of 6 m, two storeys of 3.5 m, 400 x 400 mm
columns and 300 x 600 mm beams, concrete at 25 kN/m³. The staged case builds it
the way it is built on site:

1. **Storey 1** — the ground-floor columns and the first-floor beams, carrying
   their own weight (pattern "Weight, storey 1").
2. **Storey 2** — the upper columns and the roof beams, built level at their
   design position on top of the shortened storey below, carrying their own
   weight ("Weight, storey 2": a stage weighs only what it builds).
3. **Finishes** — 15 kN/m of superimposed dead load on every beam.

The one-shot static case applies the whole weight and the finishes to the
finished frame. Compare the roof displacements (the staged ones count only the
movement since the roof was built) and the beam moments at the first floor.

Produces ``examples/staged_frame.osmodel``.
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import (
    ConstructionStage,
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    StagedCase,
    StaticCase,
    UniformElementLoad,
)
from opensees_studio.core.groups import Group
from opensees_studio.services import load_project, save_project

BAY, STOREY, BAYS, STOREYS = 6.0, 3.5, 2, 2
E_CONCRETE = 30e9
GAMMA = 25e3


def _section(sid: int, name: str, b: float, h: float) -> ElasticSection:
    area = b * h
    return ElasticSection(
        id=sid,
        name=name,
        E=E_CONCRETE,
        A=area,
        Iz=b * h**3 / 12,
        Iy=h * b**3 / 12,
        G=E_CONCRETE / 2.4,
        J=0.14 * b**3 * h,
        unit_weight=GAMMA,
    )


def build_staged_frame() -> Project:
    nodes: list[Node] = []
    for level in range(STOREYS + 1):
        for line in range(BAYS + 1):
            nodes.append(
                Node(
                    id=level * 10 + line + 1,
                    coords=(line * BAY, 0.0, level * STOREY),
                    restraint=(True,) * 6 if level == 0 else (False,) * 6,
                )
            )
    elements: list[ElasticBeamColumn] = []
    storey_elements: dict[int, list[int]] = {1: [], 2: []}
    beams: list[int] = []
    for level in range(1, STOREYS + 1):
        for line in range(BAYS + 1):
            eid = 100 * level + line + 1
            below, above = (level - 1) * 10 + line + 1, level * 10 + line + 1
            elements.append(ElasticBeamColumn(id=eid, nodes=(below, above), section_id=1))
            storey_elements[level].append(eid)
        for bay in range(BAYS):
            eid = 100 * level + 50 + bay + 1
            left, right = level * 10 + bay + 1, level * 10 + bay + 2
            elements.append(ElasticBeamColumn(id=eid, nodes=(left, right), section_id=2))
            storey_elements[level].append(eid)
            beams.append(eid)
    finishes = [UniformElementLoad(element_id=eid, wy=-15e3) for eid in beams]
    return Project(
        meta=ProjectMeta(name="Staged frame"),
        ndm=2,
        ndf=3,
        nodes=nodes,
        sections=[_section(1, "Column 400x400", 0.4, 0.4), _section(2, "Beam 300x600", 0.3, 0.6)],
        elements=elements,
        groups=[
            Group(id=1, name="Storey 1", element_ids=storey_elements[1]),
            Group(id=2, name="Storey 2", element_ids=storey_elements[2]),
        ],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[
            PlainLoadPattern(id=1, name="Weight, storey 1", time_series_id=1, self_weight=1.0),
            PlainLoadPattern(id=2, name="Weight, storey 2", time_series_id=1, self_weight=1.0),
            PlainLoadPattern(id=3, name="Finishes", time_series_id=1, element_loads=finishes),
            PlainLoadPattern(id=4, name="Weight, all", time_series_id=1, self_weight=1.0),
        ],
        analyses=[
            StagedCase(
                id=1,
                name="Built storey by storey",
                stages=[
                    ConstructionStage(name="Storey 1", add_group_ids=[1], pattern_ids=[1]),
                    ConstructionStage(name="Storey 2", add_group_ids=[2], pattern_ids=[2]),
                    ConstructionStage(name="Finishes", pattern_ids=[3]),
                ],
            ),
            StaticCase(id=2, name="Loaded at once", pattern_ids=[4, 3]),
        ],
    )


def main() -> None:
    project = build_staged_frame()
    project.validate_references()
    print(
        f"Built '{project.meta.name}' - {len(project.nodes)} nodes, "
        f"{len(project.elements)} members, {len(project.analyses)} cases."
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
