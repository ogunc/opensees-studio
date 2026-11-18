"""Three-storey, 2 x 2 bay 3D concrete frame with rigid floor diaphragms.

Plan (every floor), bays 6 m in X and 5 m in Y, storeys 3.5 m:

    y
    10 ┼─────┼─────┼        ┼ column line
       │     │     │        ● retained node of the floor diaphragm,
     5 ┼─────●─────┼          at the centre of mass (6, 5)
       │     │     │
     0 ┼─────┼─────┼── x
       0     6     12

What it shows:

- **Storeys** taken from the Z grid lines (Story1..Story3 at 3.5, 7, 10.5 m).
- **Rigid diaphragms**: one per floor, constraining every joint of the storey
  to a retained node at the centre of mass. That node touches no element, so
  the runner fixes its out-of-plane DOFs, and the cases (left at the
  ``Plain`` handler) run with ``Transformation``, which a diaphragm needs.
- **Mass source**: DEAD (beam load plus self weight) + 0.3 LIVE, turned into
  mass and lumped at each diaphragm's retained node with the floor's
  rotational inertia.
- **Storey table**: the EQX static case and the response spectrum case list
  storey displacement, drift ratio and storey shear in the Results panel.

Run from the repository root:

    python examples/building_3storey_diaphragm.py

Produces ``examples/building_3storey_diaphragm.osmodel``.
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import (
    CoordinateGridSystem,
    ElasticBeamColumn,
    ElasticSection,
    GridSystem,
    LinearTimeSeries,
    MassSource,
    MassSourcePattern,
    ModalCase,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    ResponseSpectrum,
    ResponseSpectrumCase,
    RigidDiaphragm,
    StaticCase,
    UniformElementLoad,
    UnitSystem,
    make_grid_lines,
)
from opensees_studio.core.storeys import storeys_from_grid
from opensees_studio.services import load_project, save_project

X_LINES = (0.0, 6.0, 12.0)
Y_LINES = (0.0, 5.0, 10.0)
Z_LINES = (0.0, 3.5, 7.0, 10.5)

COLUMN, BEAM = 1, 2
DEAD, LIVE, EQX = 1, 2, 3

SUPERIMPOSED_DEAD = 15_000.0  # N/m on every beam (slab, finishes)
LIVE_LOAD = 10_000.0  # N/m on every beam
EQX_FORCES = (100_000.0, 200_000.0, 300_000.0)  # N at the floors, inverted triangle


def build_building() -> Project:
    nodes: list[Node] = []
    joint: dict[tuple[int, int, int], int] = {}
    nid = 1
    for k, z in enumerate(Z_LINES):
        for j, y in enumerate(Y_LINES):
            for i, x in enumerate(X_LINES):
                nodes.append(
                    Node(
                        id=nid, coords=(x, y, z), restraint=(True,) * 6 if k == 0 else (False,) * 6
                    )
                )
                joint[(i, j, k)] = nid
                nid += 1
    # One retained node per floor at the centre of mass, touched by no element.
    centre_x, centre_y = X_LINES[1], Y_LINES[1]
    retained: list[int] = []
    for k, z in enumerate(Z_LINES[1:], start=1):
        nodes.append(Node(id=nid, name=f"CM{k}", coords=(centre_x, centre_y, z)))
        retained.append(nid)
        nid += 1

    elements: list[ElasticBeamColumn] = []
    eid = 1

    def add(ni: int, nj: int, section: int, name: str) -> None:
        nonlocal eid
        elements.append(ElasticBeamColumn(id=eid, name=name, nodes=(ni, nj), section_id=section))
        eid += 1

    nx, ny = len(X_LINES), len(Y_LINES)
    for k in range(1, len(Z_LINES)):
        for j in range(ny):
            for i in range(nx):
                add(joint[(i, j, k - 1)], joint[(i, j, k)], COLUMN, f"C{k}-{i}{j}")
        for j in range(ny):
            for i in range(nx - 1):
                add(joint[(i, j, k)], joint[(i + 1, j, k)], BEAM, f"BX{k}-{i}{j}")
        for i in range(nx):
            for j in range(ny - 1):
                add(joint[(i, j, k)], joint[(i, j + 1, k)], BEAM, f"BY{k}-{i}{j}")
    beams = [el.id for el in elements if el.name.startswith("B")]

    grid = CoordinateGridSystem(
        name="Global",
        grid=GridSystem(
            x_grid_lines=make_grid_lines("X", list(X_LINES)),
            y_grid_lines=make_grid_lines("Y", list(Y_LINES)),
            z_grid_lines=make_grid_lines("Z", list(Z_LINES)),
        ),
    )
    storeys = storeys_from_grid(grid)

    return Project(
        meta=ProjectMeta(name="3-storey diaphragm building", units=UnitSystem.SI_M_N),
        ndm=3,
        ndf=6,
        coord_systems=[grid],
        storeys=storeys,
        nodes=nodes,
        sections=[
            # 500 x 500 mm column and 300 x 600 mm beam, C30 concrete (25 kN/m3).
            ElasticSection(
                id=COLUMN,
                name="Col 500x500",
                E=30e9,
                G=12.5e9,
                A=0.25,
                Iz=0.005208333333333333,
                Iy=0.005208333333333333,
                J=0.0088,
                unit_weight=25_000.0,
            ),
            ElasticSection(
                id=BEAM,
                name="Beam 300x600",
                E=30e9,
                G=12.5e9,
                A=0.18,
                Iz=0.0054,
                Iy=0.00135,
                J=0.0037,
                unit_weight=25_000.0,
            ),
        ],
        elements=elements,
        diaphragms=[
            RigidDiaphragm(id=s.id, name=f"D{s.id}", retained_node=r, storey_id=s.id)
            for s, r in zip(storeys, retained, strict=True)
        ],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[
            # Horizontal beams have local z up, so gravity is wz < 0.
            PlainLoadPattern(
                id=DEAD,
                name="DEAD",
                time_series_id=1,
                self_weight=1.0,
                element_loads=[
                    UniformElementLoad(element_id=e, wz=-SUPERIMPOSED_DEAD) for e in beams
                ],
            ),
            PlainLoadPattern(
                id=LIVE,
                name="LIVE",
                time_series_id=1,
                element_loads=[UniformElementLoad(element_id=e, wz=-LIVE_LOAD) for e in beams],
            ),
            PlainLoadPattern(
                id=EQX,
                name="EQX",
                time_series_id=1,
                nodal_loads=[
                    NodalLoad(node_id=r, forces=(f, 0.0, 0.0, 0.0, 0.0, 0.0))
                    for r, f in zip(retained, EQX_FORCES, strict=True)
                ],
            ),
        ],
        # DEAD already carries the self weight, so the element self mass stays off.
        mass_source=MassSource(
            element_self_mass=False,
            patterns=[
                MassSourcePattern(pattern_id=DEAD, factor=1.0),
                MassSourcePattern(pattern_id=LIVE, factor=0.3),
            ],
        ),
        spectra=[
            # Approximated EC8 Type-1 elastic spectrum, soil B, ag = 0.30 g (m/s2).
            ResponseSpectrum(
                id=1,
                name="EC8 Type-1 / Soil B",
                periods=[0.01, 0.15, 0.50, 1.0, 2.0, 4.0],
                accelerations=[3.53, 8.83, 8.83, 4.42, 2.21, 1.10],
                damping_ratio=0.05,
            ),
        ],
        analyses=[
            StaticCase(id=1, name="DEAD", pattern_ids=[DEAD]),
            StaticCase(id=2, name="EQX", pattern_ids=[EQX]),
            ModalCase(id=3, name="Modal", n_modes=9),
            ResponseSpectrumCase(
                id=4,
                name="RSX-CQC",
                modal_case_id=3,
                spectrum_id=1,
                direction=1,
                combination="CQC",
            ),
        ],
    )


def main() -> None:
    project = build_building()
    project.validate_references()
    print(
        f"Built '{project.meta.name}' — {len(project.nodes)} nodes, "
        f"{len(project.elements)} elements, {len(project.diaphragms)} diaphragms, "
        f"{len(project.analyses)} cases."
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
