"""Build a 3D portal frame programmatically, validate, save, reload.

Run from the repository root:

    python examples/portal_frame.py

This script touches only the ``core`` and ``services`` layers — no Qt,
no OpenSeesPy. It demonstrates the entire Phase 1 API surface.
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    StaticCase,
    Steel01,
    UnitSystem,
)
from opensees_studio.services import load_project, save_project


def build_portal_frame() -> Project:
    """A two-column, one-beam steel portal frame with a lateral load."""
    return Project(
        meta=ProjectMeta(name="Portal Frame", author="Ozan", units=UnitSystem.SI_M_N),
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, name="Base-L", coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, name="Base-R", coords=(6.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=3, name="Top-L", coords=(0.0, 0.0, 3.0),
                 mass=(5000.0, 5000.0, 5000.0, 0.0, 0.0, 0.0)),
            Node(id=4, name="Top-R", coords=(6.0, 0.0, 3.0),
                 mass=(5000.0, 5000.0, 5000.0, 0.0, 0.0, 0.0)),
        ],
        materials=[
            Steel01(id=1, name="S420", Fy=420e6, E0=200e9, b=0.01),
        ],
        sections=[
            ElasticSection(
                id=1, name="W14x90",
                E=200e9, A=0.017,
                Iz=4.16e-4, Iy=1.29e-4,
                G=80e9, J=2.04e-6,
            ),
        ],
        elements=[
            ElasticBeamColumn(id=1, name="Col-L", nodes=(1, 3), section_id=1),
            ElasticBeamColumn(id=2, name="Col-R", nodes=(2, 4), section_id=1),
            ElasticBeamColumn(id=3, name="Beam",  nodes=(3, 4), section_id=1),
        ],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[
            PlainLoadPattern(
                id=1, name="Lateral",
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=3, forces=(50_000.0, 0, 0, 0, 0, 0))],
            ),
        ],
        analyses=[
            StaticCase(id=1, name="Linear-Static", pattern_ids=[1]),
        ],
    )


def main() -> None:
    project = build_portal_frame()
    project.validate_references()
    print(f"Built project '{project.meta.name}' — {len(project.nodes)} nodes, "
          f"{len(project.elements)} elements.")

    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved → {out_path}")

    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
