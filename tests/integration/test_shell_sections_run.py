"""LayeredShell and PlateFiber sections against the elastic plate section they equal."""

from __future__ import annotations

import pytest

from opensees_studio.core import (
    ElasticIsotropic,
    ElasticMembranePlateSection,
    LayeredShellSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    PlasticDamageConcretePlaneStress,
    PlateFiberMaterial,
    PlateFiberSection,
    PlateFromPlaneStress,
    PlateRebar,
    Project,
    ShellLayer,
    ShellMITC4Element,
    StaticCase,
    Steel02,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

pytest.importorskip("openseespy.opensees")

E, NU, H = 3e10, 0.2, 0.2


def _cantilever_plate(section, materials=()) -> float:  # type: ignore[no-untyped-def]
    """A 1 x 1 plate clamped on one edge, pushed down at the other: the tip deflection."""
    corners = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    clamped = (True,) * 6
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=k + 1, coords=(x, y, 0.0), restraint=clamped if x == 0.0 else (False,) * 6)
            for k, (x, y) in enumerate(corners)
        ],
        materials=list(materials),
        sections=[section],
        elements=[ShellMITC4Element(id=1, nodes=(1, 2, 3, 4), section_id=section.id)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=n, forces=(0, 0, -1e3, 0, 0, 0)) for n in (2, 3)],
            )
        ],
        analyses=[StaticCase(id=1, name="s", pattern_ids=[1], algorithm="Newton")],
    )
    return float(OpenSeesRunner(project).run(project.analyses[0]).node_disp[2][-1][2])


ELASTIC = [ElasticIsotropic(id=1, E=E, nu=NU), PlateFiberMaterial(id=2, material_id=1)]


def _reference() -> float:
    return _cantilever_plate(ElasticMembranePlateSection(id=1, E=E, nu=NU, h=H))


def test_a_plate_fiber_section_equals_the_elastic_plate() -> None:
    section = PlateFiberSection(id=1, material_id=2, h=H)
    assert _cantilever_plate(section, ELASTIC) == pytest.approx(_reference(), rel=1e-6)


@pytest.mark.parametrize("n", [3, 20])
def test_elastic_layers_converge_on_the_elastic_plate(n: int) -> None:
    """Each layer is integrated at its mid-plane: n equal layers give 1 - 1/n² of the
    bending stiffness, so a layered shell needs several layers through the thickness."""
    section = LayeredShellSection(id=1, layers=[ShellLayer(material_id=2, thickness=H / n)] * n)
    assert section.h == pytest.approx(H)
    tip = _cantilever_plate(section, ELASTIC)
    assert tip == pytest.approx(_reference() / (1 - 1 / n**2), rel=0.02)


def test_a_reinforced_concrete_layered_shell_runs() -> None:
    materials = [
        PlasticDamageConcretePlaneStress(id=1, E=E, nu=NU, ft=3e6, fc=30e6),
        PlateFromPlaneStress(id=2, material_id=1, G_out=1.25e10),
        Steel02(id=3, Fy=420e6, E0=2e11, b=0.01),
        PlateRebar(id=4, material_id=3, angle=0.0),
        PlateRebar(id=5, material_id=3, angle=90.0),
    ]
    layers = [
        ShellLayer(material_id=2, thickness=0.04),
        ShellLayer(material_id=4, thickness=0.0005),
        ShellLayer(material_id=5, thickness=0.0005),
        ShellLayer(material_id=2, thickness=0.075),
        ShellLayer(material_id=2, thickness=0.08),
    ]
    tip = _cantilever_plate(LayeredShellSection(id=1, layers=layers), materials)
    # Uncracked, five mid-plane layers: within the layering error of the plain plate.
    assert tip == pytest.approx(_reference(), rel=0.25)


def test_two_layers_are_refused() -> None:
    with pytest.raises(ValueError):
        LayeredShellSection(id=1, layers=[ShellLayer(material_id=1, thickness=0.1)] * 2)
