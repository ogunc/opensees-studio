"""Cantilever beam example — ideal for showing force diagrams.

A 5 m horizontal cantilever fixed at the left end, with a point load
at the tip and a distributed-equivalent set of nodal loads along the
span. Pure bending response makes for instantly recognisable N/V/M
diagrams.

Run from the repository root:

    python examples/cantilever.py

Produces ``examples/cantilever.osmodel``.
Open in the GUI, run "Tip-Load" Static case, then:

  Display → Show Force Diagram → V2 (shear)   → constant within each segment
  Display → Show Force Diagram → M3 (moment)  → linear, max at the fixed end
  Display → Show Deformed Shape               → classic cantilever curve
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    ModalCase,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    StaticCase,
    UnitSystem,
)
from opensees_studio.services import load_project, save_project


def build_cantilever() -> Project:
    """5 m cantilever discretised into 5 elements (1 m each)."""
    n_segments = 5
    seg_len = 1.0
    nodes = []
    for i in range(n_segments + 1):
        x = i * seg_len
        restraint = (True,) * 6 if i == 0 else (False,) * 6
        # Lump some mass at every free node so modal works too.
        mass = (1000.0, 1000.0, 1000.0, 0.0, 0.0, 0.0) if i > 0 else (0.0,) * 6
        nodes.append(Node(id=i + 1, name=f"N{i+1}",
                          coords=(x, 0.0, 0.0), restraint=restraint, mass=mass))

    elements = [
        ElasticBeamColumn(id=i + 1, name=f"E{i+1}",
                          nodes=(i + 1, i + 2), section_id=1)
        for i in range(n_segments)
    ]

    return Project(
        meta=ProjectMeta(name="Cantilever", author="Ozan", units=UnitSystem.SI_M_N),
        ndm=3, ndf=6,
        nodes=nodes,
        sections=[
            ElasticSection(
                id=1, name="W12x40",
                E=200e9, A=0.0076,
                Iz=2.0e-4, Iy=4.5e-5,
                G=80e9, J=8.5e-7,
            ),
        ],
        elements=elements,
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[
            # Tip vertical load (z) of 10 kN downward.
            PlainLoadPattern(
                id=1, name="TipLoad",
                time_series_id=1,
                nodal_loads=[
                    NodalLoad(node_id=n_segments + 1,
                              forces=(0.0, 0.0, -10_000.0, 0, 0, 0)),
                ],
            ),
        ],
        analyses=[
            StaticCase(id=1, name="Tip-Load", pattern_ids=[1]),
            ModalCase(id=2, name="Modal-3", n_modes=3),
        ],
    )


def main() -> None:
    project = build_cantilever()
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
