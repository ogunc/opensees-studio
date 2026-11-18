"""MVLEM walls solved by OpenSees through the application's model.

An elastic cantilever wall of stacked segments under a tip load deflects by
flexure ``P H³ / (3 E I)`` (``I`` of the fibres) plus shear ``P H / (G A)``: with
the shear springs created per segment height (``G L t / h``) the two parts add
up to the beam result as the segments get shorter. A wall of Steel02 bars and
Concrete02 concrete yields under a lateral push, so the fibres carry the
nonlinearity.
"""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (
    Concrete02,
    ElasticBeamColumn,
    ElasticSection,
    ElasticUniaxial,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    Steel02,
)
from opensees_studio.core.geometry.walls import WallSpec, walls_from_members
from opensees_studio.services.opensees_runner import OpenSeesRunner

H, L, T, E, G, P = 3.0, 1.0, 0.2, 30e9, 12.5e9, 1000.0


def _cantilever(segments: int, materials: list, load: float, steps: int = 1) -> Project:  # type: ignore[type-arg]
    nodes = [
        Node(
            id=k + 1,
            coords=(0.0, 0.0, H * k / segments),
            restraint=(True,) * 6 if k == 0 else (False,) * 6,
        )
        for k in range(segments + 1)
    ]
    frames = [
        ElasticBeamColumn(id=k + 1, nodes=(k + 1, k + 2), section_id=1) for k in range(segments)
    ]
    return Project(
        ndm=2,
        ndf=3,
        nodes=nodes,
        materials=materials,
        sections=[ElasticSection(id=1, E=E, A=L * T, Iz=T * L**3 / 12)],
        elements=frames,
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=segments + 1, forces=(load, 0, 0, 0, 0, 0))],
            )
        ],
        analyses=[
            StaticCase(
                id=1, name="push", pattern_ids=[1], n_steps=steps, load_factor_increment=1.0 / steps
            )
        ],
    )


def _as_wall(project: Project, spec: WallSpec) -> Project:
    ids = {e.id for e in project.elements}
    out = walls_from_members(project, ids, spec, first_material_id=project.next_material_id())
    project.materials.extend(out.materials)  # type: ignore[arg-type]
    project.elements[:] = out.elements
    project.sections.clear()
    project.validate_references()
    return project


def test_elastic_wall_converges_to_flexure_plus_shear() -> None:
    fibres = 10
    spec = WallSpec(
        length=L,
        thickness=T,
        fibres=fibres,
        concrete_material_id=1,
        steel_material_id=2,
        web_ratio=0.0,
        shear_modulus=G,
    )
    i_fibres = sum(T * (L / fibres) * (-L / 2 + (k + 0.5) * L / fibres) ** 2 for k in range(fibres))
    expected = P * H**3 / (3 * E * i_fibres) + P * H / (G * L * T)
    project = _as_wall(
        _cantilever(40, [ElasticUniaxial(id=1, E=E), ElasticUniaxial(id=2, E=200e9)], P), spec
    )
    results = OpenSeesRunner(project).run(project.analyses[0])
    assert results.node_disp[41][-1][0] == pytest.approx(expected, rel=0.01)


def test_reinforced_wall_softens_once_the_boundary_steel_yields() -> None:
    """Cracking and then yielding of the tension boundary cut the secant stiffness.

    The boundary steel ``As = 0.03 · 0.15 · 0.2 m²`` at ``fy = 420 MPa`` with a
    lever arm of about ``0.85 m`` yields near ``P = As fy z / H ≈ 107 kN``; at
    150 kN the tip has moved several times more per kN than at 10 kN.
    """
    concrete = Concrete02(
        id=1, fpc=-30e6, epsc0=-0.002, fpcu=-6e6, epsU=-0.01, ft=2e6, Ets=1e9, **{"lambda": 0.1}
    )
    steel = Steel02(id=2, Fy=420e6, E0=200e9, b=0.01)
    spec = WallSpec(
        length=L,
        thickness=T,
        fibres=8,
        concrete_material_id=1,
        steel_material_id=2,
        web_ratio=0.003,
        boundary_length=0.15,
        boundary_ratio=0.03,
        shear_modulus=G,
    )

    def tip(load: float) -> float:
        project = _as_wall(_cantilever(6, [concrete, steel], load, steps=30), spec)
        results = OpenSeesRunner(project).run(project.analyses[0])
        return float(results.node_disp[7][-1][0])

    small, large = tip(10e3), tip(150e3)
    assert small > 0.0
    assert large / 150e3 > 3.0 * small / 10e3
