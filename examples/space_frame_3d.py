"""Two-story 3D space frame — exercises full 3D rendering and dynamics.

Floor plan (each story):

       N3 ──── N4               z (up)
        │       │               │
        │       │               │
       N1 ──── N2               └──── x          y → into page

Two stories @ 3 m, two-bay @ 5 m. 12 nodes, 20 elements
(8 columns + 8 floor beams + 4 stiffening braces in the bottom story).

Run from the repository root:

    python examples/space_frame_3d.py

Produces ``examples/space_frame_3d.osmodel``.
Open in the GUI, run the cases, then exercise:

  Display → Show Force Diagram → N (axial)   → braces in tension/compression
  Display → Show Force Diagram → M3          → moment distribution at columns
  Display → Animate Mode Shape               → 1st = sway, 2nd = perpendicular sway
  Display → Time-History Plot                → roof-corner displacement vs time
"""

from __future__ import annotations

import math
from pathlib import Path

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    ModalCase,
    NodalLoad,
    Node,
    PathTimeSeries,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    StaticCase,
    TransientCase,
    UnitSystem,
)
from opensees_studio.services import load_project, save_project


def _earthquake_pulse(n_steps: int, dt: float) -> list[float]:
    """4-cycle damped sinusoid (toy 'ground motion')."""
    f0 = 2.0     # Hz — close to the building's first period
    zeta = 0.05
    out = []
    for i in range(n_steps):
        t = i * dt
        amp = math.exp(-2.0 * math.pi * f0 * zeta * t)
        out.append(amp * math.sin(2.0 * math.pi * f0 * t))
    return out


def build_space_frame() -> Project:
    # ── geometry ──
    bay_x, bay_y, story_z = 5.0, 5.0, 3.0
    nodes = []
    nid = 1
    # 4 base nodes (z=0) — fully fixed.
    for x in (0.0, bay_x):
        for y in (0.0, bay_y):
            nodes.append(Node(id=nid, name=f"Base{nid}",
                              coords=(x, y, 0.0), restraint=(True,) * 6))
            nid += 1
    # 4 first-floor + 4 roof nodes — free, with mass.
    for story in (1, 2):
        for x in (0.0, bay_x):
            for y in (0.0, bay_y):
                nodes.append(Node(
                    id=nid, name=f"L{story}N{nid}",
                    coords=(x, y, story * story_z),
                    mass=(2_500.0, 2_500.0, 2_500.0, 0.0, 0.0, 0.0),
                ))
                nid += 1

    # ── elements ──
    elements: list[ElasticBeamColumn] = []
    eid = 1

    def add_el(ni: int, nj: int, sec: int, name: str) -> None:
        nonlocal eid
        elements.append(ElasticBeamColumn(id=eid, name=name,
                                          nodes=(ni, nj), section_id=sec))
        eid += 1

    # Columns: bases (1-4) → 1st floor (5-8); 1st floor → roof (9-12).
    for i in range(4):
        add_el(i + 1, i + 5, sec=1, name=f"Col-G{i+1}")
        add_el(i + 5, i + 9, sec=1, name=f"Col-1{i+1}")

    # Floor beams at each story (5-8 and 9-12). Connect 4 nodes around perimeter.
    for story_base in (5, 9):
        a, b, c, d = story_base, story_base + 1, story_base + 2, story_base + 3
        add_el(a, b, sec=2, name=f"Beam-{story_base}-X1")
        add_el(c, d, sec=2, name=f"Beam-{story_base}-X2")
        add_el(a, c, sec=2, name=f"Beam-{story_base}-Y1")
        add_el(b, d, sec=2, name=f"Beam-{story_base}-Y2")

    return Project(
        meta=ProjectMeta(name="Space Frame 3D", author="Ozan", units=UnitSystem.SI_M_N),
        ndm=3, ndf=6,
        nodes=nodes,
        sections=[
            ElasticSection(id=1, name="HSS-Column",
                           E=200e9, A=0.012, Iz=2.5e-4, Iy=2.5e-4,
                           G=80e9, J=4.0e-4),
            ElasticSection(id=2, name="W-Beam",
                           E=200e9, A=0.009, Iz=3.0e-4, Iy=8.0e-5,
                           G=80e9, J=1.0e-6),
        ],
        elements=elements,
        time_series=[
            LinearTimeSeries(id=1, name="Ramp"),
            PathTimeSeries(id=2, name="EQGround",
                           values=_earthquake_pulse(400, 0.01),
                           dt=0.01),
        ],
        load_patterns=[
            # Lateral push at the 4 roof nodes (X direction) for Static.
            PlainLoadPattern(
                id=1, name="StaticPush",
                time_series_id=1,
                nodal_loads=[
                    NodalLoad(node_id=9, forces=(25_000.0, 0, 0, 0, 0, 0)),
                    NodalLoad(node_id=10, forces=(25_000.0, 0, 0, 0, 0, 0)),
                    NodalLoad(node_id=11, forces=(25_000.0, 0, 0, 0, 0, 0)),
                    NodalLoad(node_id=12, forces=(25_000.0, 0, 0, 0, 0, 0)),
                ],
            ),
            # Earthquake-style horizontal load on roof corner for Transient.
            PlainLoadPattern(
                id=2, name="EQRoofLoad",
                time_series_id=2,
                nodal_loads=[
                    NodalLoad(node_id=12, forces=(50_000.0, 0, 0, 0, 0, 0)),
                ],
            ),
        ],
        analyses=[
            StaticCase(id=1, name="Lateral-Push", pattern_ids=[1]),
            ModalCase(id=2, name="Modal-6", n_modes=6),
            TransientCase(id=3, name="EQ-4s", pattern_ids=[2],
                          dt=0.01, n_steps=400),
        ],
    )


def main() -> None:
    project = build_space_frame()
    project.validate_references()
    print(f"Built '{project.meta.name}' — {len(project.nodes)} nodes, "
          f"{len(project.elements)} elements, {len(project.analyses)} cases.")
    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved → {out_path}")
    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
