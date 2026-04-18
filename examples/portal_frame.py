"""Build a 3D portal frame with Static + Modal + Transient cases.

Run from the repository root:

    python examples/portal_frame.py

Produces ``examples/portal_frame.osmodel`` — open it from the GUI's
File → Open menu, then exercise:

- **Static** case  → Display → Show Deformed Shape, Show Force Diagram
- **Modal** case   → Display → Animate Mode Shape
- **Transient** case → Display → Time-History Plot, Hysteresis Plot

The model is a single-bay portal frame loaded laterally:

       Top-L ──── Beam ──── Top-R           z
        │                    │              │
        │                    │              │
       Col-L                Col-R           └── x
        │                    │
       Base-L              Base-R       (y = 0; planar in x-z)

Mass is lumped at the top nodes so modal/transient solvers have
non-singular mass matrices.
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
    Steel01,
    TransientCase,
    UnitSystem,
)
from opensees_studio.services import load_project, save_project


def _sine_pulse_factors() -> list[float]:
    """One half-cycle sine over the first 0.5s, then zero for the rest of 2s."""
    n_pulse = 50          # 0.5 s @ 100 Hz
    n_total = 200
    return [math.sin(math.pi * i / n_pulse) if i < n_pulse else 0.0
            for i in range(n_total)]


def build_portal_frame() -> Project:
    """A two-column, one-beam steel portal frame with static + dynamic cases."""
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
        time_series=[
            LinearTimeSeries(id=1, name="Ramp"),
            PathTimeSeries(
                id=2, name="SineGust",
                values=_sine_pulse_factors(),
                dt=0.01,
            ),
        ],
        load_patterns=[
            # Pattern 1: 50 kN lateral push at top-left for Static.
            PlainLoadPattern(
                id=1, name="Lateral",
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=3, forces=(50_000.0, 0, 0, 0, 0, 0))],
            ),
            # Pattern 2: 100 kN sine pulse at top-left for Transient.
            PlainLoadPattern(
                id=2, name="SineGustPattern",
                time_series_id=2,
                nodal_loads=[NodalLoad(node_id=3, forces=(100_000.0, 0, 0, 0, 0, 0))],
            ),
        ],
        analyses=[
            StaticCase(id=1, name="Linear-Static", pattern_ids=[1]),
            ModalCase(id=2, name="Modal-3", n_modes=3),
            TransientCase(
                id=3, name="Sine-Gust-2s",
                pattern_ids=[2],
                dt=0.01, n_steps=200,         # 2 seconds @ 100 Hz
            ),
        ],
    )


def main() -> None:
    project = build_portal_frame()
    project.validate_references()
    print(f"Built '{project.meta.name}' — {len(project.nodes)} nodes, "
          f"{len(project.elements)} elements, {len(project.analyses)} cases.")
    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved -> {out_path}")
    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
