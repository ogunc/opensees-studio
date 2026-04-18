"""Portal frame with fiber-section plastic hinges and pushover analysis.

A single-bay portal frame where the column bases use FiberSections
(concrete core + rebar layers) wrapped in a SectionAggregator (for
torsion) and assigned to BeamWithHingesElements. The beam and column
tops remain elastic.

Demonstrates the full Phase 9 pipeline:
1. Define concrete + steel uniaxialMaterials
2. Build a FiberSection with a rectangular concrete patch + rebar layers
3. Wrap in a SectionAggregator that adds elastic torsion
4. Assign BeamWithHingesElements to the columns (hinges at base only)
5. Run a monotonic pushover to 0.15 m lateral displacement
6. View the pushover curve and force diagrams

Run:
    python examples/portal_pushover.py

Produces ``examples/portal_pushover.osmodel``.

GUI walkthrough:
    File → Open → portal_pushover.osmodel
    Analyze → Cases → Run "Push-X"
    Display → Show Pushover Curve   → see yielding + hardening
    Display → Show Force Diagram → M3 at the last pushover step
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import (
    AggregatorDOF,
    BeamWithHingesElement,
    Concrete01,
    ElasticBeamColumn,
    ElasticSection,
    ElasticUniaxial,
    FiberSection,
    LinearTimeSeries,
    ModalCase,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    PushoverCase,
    RectangularPatch,
    SectionAggregator,
    Steel01,
    StraightLayer,
    UnitSystem,
)
from opensees_studio.services import load_project, save_project


def build_portal_pushover() -> Project:
    """Portal frame: 2 columns (hinge at base) + 1 beam (elastic)."""
    H = 3.0     # story height
    L = 6.0     # bay width
    b = 0.30    # column width (y)
    h = 0.40    # column depth (z)
    cover = 0.04

    return Project(
        meta=ProjectMeta(name="Portal Pushover", author="Ozan",
                         units=UnitSystem.SI_M_N),
        ndm=3, ndf=6,
        nodes=[
            Node(id=1, name="Base-L", coords=(0.0, 0.0, 0.0),
                 restraint=(True,) * 6),
            Node(id=2, name="Base-R", coords=(L, 0.0, 0.0),
                 restraint=(True,) * 6),
            Node(id=3, name="Top-L", coords=(0.0, 0.0, H),
                 mass=(10_000.0, 10_000.0, 10_000.0, 0.0, 0.0, 0.0)),
            Node(id=4, name="Top-R", coords=(L, 0.0, H),
                 mass=(10_000.0, 10_000.0, 10_000.0, 0.0, 0.0, 0.0)),
        ],
        materials=[
            # Concrete: unconfined C30 (fpc negative by convention)
            Concrete01(id=1, name="C30",
                       fpc=-30e6, epsc0=-0.002, fpcu=-0.0, epsU=-0.005),
            # Steel rebar: S420 bilinear
            Steel01(id=2, name="S420", Fy=420e6, E0=200e9, b=0.01),
            # Elastic torsion spring
            ElasticUniaxial(id=3, name="GJ-spring", E=80e9 * 3.6e-4),
        ],
        sections=[
            # FiberSection for the column hinge region:
            # - Rectangular concrete patch (core, excluding cover for simplicity)
            # - Bottom rebar layer (3 × Ø20 → A=3×314e-6=942e-6 m²)
            # - Top rebar layer
            FiberSection(
                id=1, name="RC-Column",
                patches=[RectangularPatch(
                    material_id=1,
                    n_fib_y=8, n_fib_z=10,
                    y_i=-b / 2 + cover, z_i=-h / 2 + cover,
                    y_j=b / 2 - cover, z_j=h / 2 - cover,
                )],
                layers=[
                    # Bottom rebar (z = -h/2 + cover)
                    StraightLayer(
                        material_id=2, n_bars=3, bar_area=314e-6,
                        y_start=-b / 2 + cover, z_start=-h / 2 + cover,
                        y_end=b / 2 - cover, z_end=-h / 2 + cover,
                    ),
                    # Top rebar (z = +h/2 - cover)
                    StraightLayer(
                        material_id=2, n_bars=3, bar_area=314e-6,
                        y_start=-b / 2 + cover, z_start=h / 2 - cover,
                        y_end=b / 2 - cover, z_end=h / 2 - cover,
                    ),
                ],
            ),
            # Aggregator: FiberSection + elastic torsion
            SectionAggregator(
                id=2, name="Col-Agg",
                section_id=1,
                pairings=[AggregatorDOF(material_id=3, dof="T")],
            ),
            # Elastic beam section (for the beam and column elastic interior)
            ElasticSection(
                id=3, name="W14x90",
                E=200e9, A=0.017,
                Iz=4.16e-4, Iy=1.29e-4,
                G=80e9, J=2.04e-6,
            ),
        ],
        elements=[
            # Columns: BeamWithHinges at the base (hinge at end-i only;
            # end-j uses the same section but with a tiny Lp so it stays
            # essentially elastic there).
            BeamWithHingesElement(
                id=1, name="Col-L", nodes=(1, 3),
                section_i_id=2, section_j_id=2,
                lp_i=0.40, lp_j=0.01,    # plastic hinge at base only
                E=200e9, A=0.017,
                Iz=4.16e-4, Iy=1.29e-4,
                G=80e9, J=2.04e-6,
            ),
            BeamWithHingesElement(
                id=2, name="Col-R", nodes=(2, 4),
                section_i_id=2, section_j_id=2,
                lp_i=0.40, lp_j=0.01,
                E=200e9, A=0.017,
                Iz=4.16e-4, Iy=1.29e-4,
                G=80e9, J=2.04e-6,
            ),
            # Beam: elastic
            ElasticBeamColumn(id=3, name="Beam", nodes=(3, 4), section_id=3),
        ],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[
            PlainLoadPattern(
                id=1, name="PushRef",
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=3, forces=(1.0, 0, 0, 0, 0, 0))],
            ),
        ],
        analyses=[
            PushoverCase(
                id=1, name="Push-X",
                pattern_ids=[1],
                control_node=3, control_dof=1,
                target_disp=0.15, step_size=0.0005,
                base_nodes=[1, 2],
            ),
            ModalCase(id=2, name="Modal-3", n_modes=3),
        ],
    )


def main() -> None:
    project = build_portal_pushover()
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
