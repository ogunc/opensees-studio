"""The same model in SI and in the kgf / tonf / kN / lb systems solves to the same physics."""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    ModalCase,
    Node,
    PlainLoadPattern,
    PointElementLoad,
    Project,
    StaticCase,
    UnitSystem,
)
from opensees_studio.core.units import (
    force_scale,
    length_scale,
    mass_scale,
    stress_scale,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

SPAN = 6.0  # m
GAMMA = 77_000.0  # N/m³, steel's weight


def _beam(units: UnitSystem) -> Project:
    """A 2D cantilever with a lumped tip mass, self weight and a point load, in ``units``."""
    length = length_scale(UnitSystem.SI_M_N, units)
    force = force_scale(UnitSystem.SI_M_N, units)
    stress = stress_scale(UnitSystem.SI_M_N, units)
    mass = mass_scale(UnitSystem.SI_M_N, units)
    project = Project(ndm=2, ndf=3)
    project.meta.units = units
    project.nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, False, True, False, True, False)),
        Node(
            id=2,
            coords=(SPAN * length, 0.0, 0.0),
            mass=(2_000.0 * mass, 0.0, 2_000.0 * mass, 0.0, 0.0, 0.0),
        ),
    ]
    project.sections = [
        ElasticSection(
            id=1,
            E=200e9 * stress,
            A=0.01 * length**2,
            Iz=2e-4 * length**4,
            unit_weight=GAMMA * force / length**3,
        )
    ]
    project.elements = [ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)]
    project.time_series = [LinearTimeSeries(id=1)]
    project.load_patterns = [
        PlainLoadPattern(
            id=1,
            time_series_id=1,
            self_weight=1.0,
            point_loads=[PointElementLoad(element_id=1, py=-10_000.0 * force, x=0.5)],
        )
    ]
    project.analyses = [
        StaticCase(id=1, name="DEAD", pattern_ids=[1]),
        ModalCase(id=2, name="Modal", n_modes=1),
    ]
    return project


@pytest.mark.parametrize(
    "units",
    [
        UnitSystem.MKS_M_KGF,
        UnitSystem.MKS_CM_KGF,
        UnitSystem.MKS_M_TONF,
        UnitSystem.SI_M_KN,
        UnitSystem.SI_MM_KN,
        UnitSystem.US_IN_LB,
        UnitSystem.US_FT_LB,
    ],
)
def test_reactions_deflection_and_frequency_match_si(units: UnitSystem) -> None:
    si = _beam(UnitSystem.SI_M_N)
    other = _beam(units)
    si_static = OpenSeesRunner(si).run(si.analyses[0])
    other_static = OpenSeesRunner(other).run(other.analyses[0])
    force = force_scale(UnitSystem.SI_M_N, units)
    length = length_scale(UnitSystem.SI_M_N, units)

    # Root reaction: self weight γ A L plus the point load, converted.
    expected = GAMMA * 0.01 * SPAN + 10_000.0
    assert si_static.node_reaction[1][-1][1] == pytest.approx(expected, rel=1e-9)
    assert other_static.node_reaction[1][-1][1] == pytest.approx(expected * force, rel=1e-9)
    assert other_static.node_disp[2][-1][1] == pytest.approx(
        si_static.node_disp[2][-1][1] * length, rel=1e-9
    )

    si_modal = OpenSeesRunner(si).run(si.analyses[1])
    other_modal = OpenSeesRunner(other).run(other.analyses[1])
    assert other_modal.frequencies[0] == pytest.approx(si_modal.frequencies[0], rel=1e-9)
