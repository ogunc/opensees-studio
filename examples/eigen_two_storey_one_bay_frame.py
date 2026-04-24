"""Eigen analysis of a two-storey one-bay frame.

OpenSees Wiki tutorial:
https://opensees.berkeley.edu/wiki/index.php?title=Eigen_analysis_of_a_two-storey_one-bay_frame

Two-storey one-bay elastic frame from Chopra Example 10.5:
- 2D frame, ndm=2 / ndf=3
- elastic columns + elastic beams
- lumped masses only in Ux
- modal analysis for the first two modes

Run from the repository root:

    python examples/eigen_two_storey_one_bay_frame.py

Produces ``examples/eigen_two_storey_one_bay_frame.osmodel``.
"""

from __future__ import annotations

from pathlib import Path
import sys

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opensees_studio.core import (  # noqa: E402
    ElasticBeamColumn,
    ElasticSection,
    ModalCase,
    Node,
    Project,
    ProjectMeta,
    UnitSystem,
)
from opensees_studio.services import load_project, save_project  # noqa: E402


M = 100.0 / 386.0
NUM_MODES = 2

A = 63.41
I = 320.0
E = 29000.0
L = 240.0
H = 120.0

REFERENCE_TCL = Path(__file__).resolve().parent / "data" / "EigenAnal_twoStoreyFrame1.tcl.txt"


def build_eigen_two_storey_one_bay_frame() -> Project:
    return Project(
        meta=ProjectMeta(
            name="Eigen - Two-Storey One-Bay Frame",
            author="OpenSees Wiki / Chopra Example 10.5",
            description=(
                "Two-storey one-bay elastic frame with two-mode eigenvalue analysis."
            ),
            units=UnitSystem.US_IN_KIP,
        ),
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, name="N1", coords=(0.0, 0.0, 0.0), restraint=(True, True, False, False, False, True)),
            Node(id=2, name="N2", coords=(L, 0.0, 0.0), restraint=(True, True, False, False, False, True)),
            Node(id=3, name="N3", coords=(0.0, H, 0.0), mass=(M, 0.0, 0.0, 0.0, 0.0, 0.0)),
            Node(id=4, name="N4", coords=(L, H, 0.0), mass=(M, 0.0, 0.0, 0.0, 0.0, 0.0)),
            Node(id=5, name="N5", coords=(0.0, 2.0 * H, 0.0), mass=(M / 2.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
            Node(id=6, name="N6", coords=(L, 2.0 * H, 0.0), mass=(M / 2.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
        ],
        sections=[
            ElasticSection(id=1, name="Column-L1", E=E, A=A, Iz=2.0 * I),
            ElasticSection(id=2, name="Frame-L2", E=E, A=A, Iz=I),
        ],
        elements=[
            ElasticBeamColumn(id=1, name="C1", nodes=(1, 3), section_id=1, geom_transf="Linear"),
            ElasticBeamColumn(id=2, name="C2", nodes=(3, 5), section_id=2, geom_transf="Linear"),
            ElasticBeamColumn(id=3, name="C3", nodes=(2, 4), section_id=1, geom_transf="Linear"),
            ElasticBeamColumn(id=4, name="C4", nodes=(4, 6), section_id=2, geom_transf="Linear"),
            ElasticBeamColumn(id=5, name="B1", nodes=(3, 4), section_id=1, geom_transf="Linear"),
            ElasticBeamColumn(id=6, name="B2", nodes=(5, 6), section_id=2, geom_transf="Linear"),
        ],
        analyses=[
            ModalCase(id=1, name="Modal-2", n_modes=NUM_MODES),
        ],
    )


def main() -> None:
    project = build_eigen_two_storey_one_bay_frame()
    project.validate_references()
    print(f"Built '{project.meta.name}'")
    print(f"  Reference Tcl: {REFERENCE_TCL.name}")
    print(f"  Nodes: {len(project.nodes)}, elements: {len(project.elements)}")
    print(f"  Modes: {NUM_MODES}")
    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved -> {out_path}")
    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
