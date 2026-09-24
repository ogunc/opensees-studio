"""Synthetic 3D grid frames for eigen tests above the dense solver threshold."""

from __future__ import annotations

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    ModalCase,
    Node,
    Project,
    ProjectMeta,
    UnitSystem,
)


def grid_frame(nx: int, ny: int, nz: int, n_modes: int = 6) -> Project:
    """A (nx x ny) bay, nz storey elastic space frame with lumped floor masses.

    Free DOF: 6 per node above the base, so ``6 * (nx + 1) * (ny + 1) * nz``
    (900 for a 4 x 4 x 6 grid). Two identical modal cases (ids 1 and 2)
    make in-process and multi-case runs comparable.
    """
    bay, storey = 5.0, 3.0
    nodes: list[Node] = []
    nid: dict[tuple[int, int, int], int] = {}
    k = 1
    for iz in range(nz + 1):
        for ix in range(nx + 1):
            for iy in range(ny + 1):
                nid[(ix, iy, iz)] = k
                if iz == 0:
                    nodes.append(
                        Node(id=k, coords=(ix * bay, iy * bay, 0.0), restraint=(True,) * 6)
                    )
                else:
                    nodes.append(
                        Node(
                            id=k,
                            coords=(ix * bay, iy * bay, iz * storey),
                            mass=(2500.0, 2500.0, 2500.0, 0.0, 0.0, 0.0),
                        )
                    )
                k += 1
    elements: list[ElasticBeamColumn] = []
    eid = 1
    for iz in range(1, nz + 1):
        for ix in range(nx + 1):
            for iy in range(ny + 1):
                here = nid[(ix, iy, iz)]
                elements.append(
                    ElasticBeamColumn(id=eid, nodes=(nid[(ix, iy, iz - 1)], here), section_id=1)
                )
                eid += 1
                if ix < nx:
                    elements.append(
                        ElasticBeamColumn(id=eid, nodes=(here, nid[(ix + 1, iy, iz)]), section_id=2)
                    )
                    eid += 1
                if iy < ny:
                    elements.append(
                        ElasticBeamColumn(id=eid, nodes=(here, nid[(ix, iy + 1, iz)]), section_id=2)
                    )
                    eid += 1
    return Project(
        meta=ProjectMeta(name=f"grid {nx}x{ny}x{nz}", units=UnitSystem.SI_M_N),
        ndm=3,
        ndf=6,
        nodes=nodes,
        elements=elements,
        sections=[
            ElasticSection(
                id=1, name="col", E=200e9, A=0.012, Iz=2.5e-4, Iy=2.5e-4, G=80e9, J=4.0e-4
            ),
            ElasticSection(
                id=2, name="beam", E=200e9, A=0.009, Iz=3.0e-4, Iy=8.0e-5, G=80e9, J=1.0e-6
            ),
        ],
        analyses=[
            ModalCase(id=1, name="Modal-A", n_modes=n_modes),
            ModalCase(id=2, name="Modal-B", n_modes=n_modes),
        ],
    )
