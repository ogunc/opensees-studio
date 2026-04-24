"""Eigen analysis of a two-storey shear frame.

OpenSees Wiki tutorial:
https://opensees.berkeley.edu/wiki/index.php?title=Eigen_analysis_of_a_two-story_shear_frame

Idealized two-storey shear frame from Chopra Example 10.4:
- 2D frame, ndm=2 / ndf=3
- beams modeled as flexurally rigid (very large Iz)
- floor nodes tied with equalDOF in Uy and Rz
- lumped masses only in Ux
- modal analysis for the first two modes

Run from the repository root:

    python examples/eigen_two_storey_shear_frame.py

Produces ``examples/eigen_two_storey_shear_frame.osmodel``.
"""

from __future__ import annotations

from pathlib import Path
import sys

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opensees_studio.core import (  # noqa: E402
    ElasticBeamColumn,
    ElasticSection,
    EqualDOFConstraint,
    ModalCase,
    Node,
    Project,
    ProjectMeta,
    UnitSystem,
)
from opensees_studio.services import load_project, save_project  # noqa: E402


M = 100.0 / 386.0
NUM_MODES = 2

AC = 63.41
IC = 320.0
E = 30000.0
IB = 10e12
AB = 63.41

L = 288.0
H = 144.0

REFERENCE_TCL = Path(__file__).resolve().parent / "data" / "EigenAnal_twoStoreyShearFrame7.tcl.txt"


def build_eigen_two_storey_shear_frame() -> Project:
    return Project(
        meta=ProjectMeta(
            name="Eigen - Two-Storey Shear Frame",
            author="OpenSees Wiki / Chopra Example 10.4",
            description=(
                "Two-storey shear frame with equalDOF floor constraints and "
                "two-mode eigenvalue analysis."
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
        mp_constraints=[
            EqualDOFConstraint(retained_node=3, constrained_node=4, dofs=(2, 3)),
            EqualDOFConstraint(retained_node=5, constrained_node=6, dofs=(2, 3)),
        ],
        sections=[
            ElasticSection(id=1, name="Column-L1", E=E, A=AC, Iz=2.0 * IC),
            ElasticSection(id=2, name="Column-L2", E=E, A=AC, Iz=IC),
            ElasticSection(id=3, name="Beam-Rigid", E=E, A=AB, Iz=IB),
        ],
        elements=[
            ElasticBeamColumn(id=1, name="C1", nodes=(1, 3), section_id=1, geom_transf="Linear"),
            ElasticBeamColumn(id=2, name="C2", nodes=(3, 5), section_id=2, geom_transf="Linear"),
            ElasticBeamColumn(id=3, name="C3", nodes=(2, 4), section_id=1, geom_transf="Linear"),
            ElasticBeamColumn(id=4, name="C4", nodes=(4, 6), section_id=2, geom_transf="Linear"),
            ElasticBeamColumn(id=5, name="B1", nodes=(3, 4), section_id=3, geom_transf="Linear"),
            ElasticBeamColumn(id=6, name="B2", nodes=(5, 6), section_id=3, geom_transf="Linear"),
        ],
        analyses=[
            ModalCase(id=1, name="Modal-2", n_modes=NUM_MODES),
        ],
    )


def main() -> None:
    project = build_eigen_two_storey_shear_frame()
    project.validate_references()
    print(f"Built '{project.meta.name}'")
    print(f"  Reference Tcl: {REFERENCE_TCL.name}")
    print(f"  Nodes: {len(project.nodes)}, elements: {len(project.elements)}")
    print(f"  MP constraints: {len(project.mp_constraints)}, modes: {NUM_MODES}")
    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved -> {out_path}")
    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
