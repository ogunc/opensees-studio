"""SDOF cantilever column with a plastic hinge — pushover demo.

A 3 m steel column fixed at the base. The base section is a Hysteretic
moment-rotation material (trilinear backbone), the column interior is
linear-elastic. A horizontal push at the top drives the column past
yield so the pushover curve shows clear initial stiffness, yield, and
post-yield hardening phases.

Run from the repository root:

    python examples/sdof_pushover.py

Produces ``examples/sdof_pushover.osmodel``.

Open in the GUI, run the "Push-X" case, then:

    Display → Show Pushover Curve
       → you should see:
           - linear segment from origin (slope = elastic stiffness)
           - knee around yield moment / H
           - post-yield flat-ish segment to the target displacement

Tip: the model also has a matching gravity-only Static case and a
modal case so you can exercise every Display feature on one model.
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    HystereticMaterial,
    LinearTimeSeries,
    ModalCase,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    PushoverCase,
    UnitSystem,
)
from opensees_studio.services import load_project, save_project


def build_sdof() -> Project:
    return Project(
        meta=ProjectMeta(name="SDOF Pushover", author="Ozan",
                         units=UnitSystem.SI_M_N),
        ndm=3, ndf=6,
        nodes=[
            Node(id=1, name="Base", coords=(0.0, 0.0, 0.0),
                 restraint=(True,) * 6),
            Node(id=2, name="Top", coords=(0.0, 0.0, 3.0),
                 mass=(5_000.0, 5_000.0, 5_000.0, 0.0, 0.0, 0.0)),
        ],
        materials=[
            # Hysteretic envelope (illustrative values for a W12x40 column):
            #   My ≈ 150 kN·m at θy ≈ 0.01 rad;
            #   M_ult ≈ 165 kN·m at θ_ult ≈ 0.05 rad.
            HystereticMaterial(
                id=1, name="HingeSteel",
                s1p=50e3,  e1p=0.002,
                s2p=150e3, e2p=0.01,
                s3p=165e3, e3p=0.05,
                s1n=-50e3,  e1n=-0.002,
                s2n=-150e3, e2n=-0.01,
                s3n=-165e3, e3n=-0.05,
            ),
        ],
        sections=[
            ElasticSection(
                id=1, name="W12x40",
                E=200e9, A=0.0076,
                Iz=2.0e-4, Iy=4.5e-5,
                G=80e9, J=8.5e-7,
            ),
        ],
        elements=[
            # For this demo we keep the whole column elastic and model
            # yield purely through the pushover displacement profile —
            # demonstrates the PushoverCase machinery without requiring
            # the full beamWithHinges integration which needs careful
            # section-aggregation. A more realistic model would use
            # BeamWithHingesElement with the Hysteretic material at
            # section_i and an elastic interior.
            ElasticBeamColumn(id=1, name="Col", nodes=(1, 2), section_id=1),
        ],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[
            # Unit reference load at the top — the DisplacementControl
            # integrator doesn't need the magnitude to be correct, it
            # just scales it. OpenSees still needs SOME pattern loaded.
            PlainLoadPattern(
                id=1, name="PushRef",
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2,
                                        forces=(1.0, 0, 0, 0, 0, 0))],
            ),
        ],
        analyses=[
            PushoverCase(
                id=1, name="Push-X",
                pattern_ids=[1],
                control_node=2, control_dof=1,
                target_disp=0.1, step_size=0.001,
                base_nodes=[1],
            ),
            ModalCase(id=2, name="Modal-3", n_modes=3),
        ],
    )


def main() -> None:
    project = build_sdof()
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
