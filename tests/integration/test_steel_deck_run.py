"""The steel deck wizard's layered shell bends and stretches as its targets say."""

from __future__ import annotations

import pytest

from opensees_studio.core import (
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ShellMITC4Element,
    StaticCase,
    UnitSystem,
)
from opensees_studio.core.steel_deck import DeckInput, build_deck_model
from opensees_studio.services.opensees_runner import OpenSeesRunner

pytest.importorskip("openseespy.opensees")

EC = 57000 * 4000**0.5 * 6894.757
DECK = DeckInput(
    rib_height=0.0508,
    pitch=0.3048,
    rib_bottom=0.1143,
    rib_top=0.1778,
    sheet_thickness=0.00091,
    topping=0.065,
    Ec=EC,
    nu=0.2,
    rho_c=2402.8,
    Es=203e9,
    rho_s=7849.0,
)
LENGTH, WIDTH, NX, NY = 6.0, 1.0, 24, 2


def _strip(along: str, ribs_along: str, force: tuple[float, float, float]) -> tuple[float, object]:
    """A 6 m x 1 m strip clamped at one end, ``force`` per unit width at the other.

    The strip runs along global ``along`` ("x" or "y"); returns the mean tip
    displacement in the direction of the force and the deck properties.
    """
    model = build_deck_model(
        DECK.__class__(**{**DECK.__dict__, "ribs_along": ribs_along}),
        name="Deck",
        first_material_id=1,
        section_id=1,
        units=UnitSystem.SI_M_N,
    )
    nodes, elements = [], []

    def nid(i: int, j: int) -> int:
        return i * (NY + 1) + j + 1

    for i in range(NX + 1):
        for j in range(NY + 1):
            s, t = LENGTH * i / NX, WIDTH * j / NY
            xy = (s, t) if along == "x" else (-t, s)
            nodes.append(Node(id=nid(i, j), coords=(*xy, 0.0), restraint=(i == 0,) * 6))
    for i in range(NX):
        for j in range(NY):
            elements.append(
                ShellMITC4Element(
                    id=len(elements) + 1,
                    nodes=(nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)),
                    section_id=1,
                )
            )
    tip = [nid(NX, j) for j in range(NY + 1)]
    share = [0.5 if j in (0, NY) else 1.0 for j in range(NY + 1)]
    per_node = WIDTH / NY
    loads = []
    for node, w in zip(tip, share, strict=True):
        f = tuple(c * w * per_node for c in force)
        loads.append(NodalLoad(node_id=node, forces=(*f, 0.0, 0.0, 0.0)))
    project = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        materials=model.materials,
        sections=[model.section],
        elements=elements,
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[PlainLoadPattern(id=1, time_series_id=1, nodal_loads=loads)],
        analyses=[StaticCase(id=1, name="s", pattern_ids=[1])],
    )
    disp = OpenSeesRunner(project).run(project.analyses[0]).node_disp
    axis = max(range(3), key=lambda k: abs(force[k]))
    if along == "y" and axis == 0:  # the strip's own axis is global y there
        axis = 1
    mean = sum(float(disp[n][-1][axis]) for n in tip) / len(tip)
    return mean, model.properties


@pytest.mark.parametrize("along", ["x", "y"])
def test_bending_along_the_ribs_is_the_composite_section(along: str) -> None:
    # Along global y too: the ribs follow the shells' local x (first edge), not X.
    tip, props = _strip(along, "x", (0.0, 0.0, -1e3))
    expected = 1e3 * LENGTH**3 / (3 * props.EI_strong)
    assert -tip == pytest.approx(expected, rel=0.02)


def test_bending_across_the_ribs_is_the_topping_alone() -> None:
    tip, props = _strip("x", "y", (0.0, 0.0, -1e3))
    expected = 1e3 * LENGTH**3 / (3 * props.EI_weak)
    assert -tip == pytest.approx(expected, rel=0.02)


@pytest.mark.parametrize(("ribs", "target"), [("x", "EA_strong"), ("y", "EA_weak")])
def test_axial_stiffness_follows_the_ribs(ribs: str, target: str) -> None:
    tip, props = _strip("x", ribs, (1e5, 0.0, 0.0))

    expected = 1e5 * LENGTH / getattr(props, target)
    assert tip == pytest.approx(expected, rel=0.05)


def test_the_weight_is_the_real_slab() -> None:
    model = build_deck_model(
        DECK, name="Deck", first_material_id=1, section_id=1, units=UnitSystem.SI_M_N
    )
    weight = model.section.unit_weight * model.section.h
    assert weight == pytest.approx(model.properties.mass_per_area * 9.80665)
