"""The steel frame check over real OpenSees results, against hand calculations.

A simply supported W18X50 under a uniform load: the major-axis moment wL²/8 and
Cb = 1.136 (F1-1) come out of the diagrams, so the ratio can be written down by
hand. Combinations, the axial sign, the 3D orientation and the reasons a member
is not designed are pinned on top of it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (
    ElasticBeamColumn,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    StaticCase,
    UniformElementLoad,
    UnitSystem,
)
from opensees_studio.core.aisc import get_shape, shape_to_elastic_section
from opensees_studio.core.combinations import CombinationTerm, LoadCombination
from opensees_studio.core.design.aisc360 import Steel, flexure_major
from opensees_studio.core.design.settings import DesignSettings, SteelMemberDesign
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.steel_design import (
    ishape_in_units,
    steel_frame_check,
    storey_drift_check,
)

KIP_IN = UnitSystem.US_IN_KIP
E, G = 29000.0, 11200.0
SPAN = 20 * 12.0  # in
W_DEAD, W_LIVE = 0.05, 0.10  # kip/in


def _beam(ndm: int = 2, section_name: str = "W18X50", shape: str = "W18X50") -> Project:
    section = shape_to_elastic_section(
        get_shape(shape), elastic_modulus=E, shear_modulus=G, units=KIP_IN, ndm=ndm
    ).model_copy(update={"name": section_name})
    pin = (
        (True, True, True, False, False, False)
        if ndm == 3
        else (True, False, True, False, False, False)
    )
    roller = (
        (False, True, True, False, False, False)
        if ndm == 3
        else (False, False, True, False, False, False)
    )
    n = 4
    nodes = [
        Node(
            id=k + 1,
            coords=(SPAN * k / n, 0.0, 0.0),
            restraint=pin if k == 0 else roller if k == n else (False,) * 6,
        )
        for k in range(n + 1)
    ]
    if ndm == 3:  # hold the torsion and the lateral sway the pins leave free
        nodes[0] = nodes[0].model_copy(update={"restraint": (True, True, True, True, False, False)})
    elements = [ElasticBeamColumn(id=k + 1, nodes=(k + 1, k + 2), section_id=1) for k in range(n)]
    down = "wz" if ndm == 3 else "wy"
    return Project(
        meta=ProjectMeta(units=KIP_IN),
        ndm=ndm,
        ndf=6 if ndm == 3 else 3,
        nodes=nodes,
        sections=[section],
        elements=elements,
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="D",
                time_series_id=1,
                element_loads=[
                    UniformElementLoad(element_id=e.id, **{down: -W_DEAD}) for e in elements
                ],
            ),
            PlainLoadPattern(
                id=2,
                name="L",
                time_series_id=1,
                element_loads=[
                    UniformElementLoad(element_id=e.id, **{down: -W_LIVE}) for e in elements
                ],
            ),
        ],
        analyses=[
            StaticCase(id=1, name="DEAD", pattern_ids=[1]),
            StaticCase(id=2, name="LIVE", pattern_ids=[2]),
        ],
        combinations=[
            LoadCombination(
                id=1,
                name="1.2D+1.6L",
                terms=[
                    CombinationTerm(ref_id=1, factor=1.2),
                    CombinationTerm(ref_id=2, factor=1.6),
                ],
            ),
            LoadCombination(id=2, name="1.4D", terms=[CombinationTerm(ref_id=1, factor=1.4)]),
        ],
    )


def _results(project: Project) -> dict[int, object]:
    return {case.id: OpenSeesRunner(project).run(case) for case in project.analyses}


def _hand_ratio(w: float, lb: float, cb: float) -> float:
    shape = ishape_in_units("W18X50", KIP_IN)
    capacity = flexure_major(shape, Steel(50.0, E, G), "LRFD", unbraced=lb, cb=cb).available
    return w * SPAN**2 / 8 / capacity


@pytest.mark.parametrize("ndm", [2, 3])
def test_a_beam_ratio_matches_the_hand_calculation(ndm: int) -> None:
    project = _beam(ndm)
    report = steel_frame_check(project, _results(project), DesignSettings())
    # Each quarter of the span is one member: the middle two carry the peak moment.
    middle = next(m for m in report.members if m.element_id == 2)
    assert middle.status == "OK"
    assert middle.load_set == "Combination 1.2D+1.6L"
    # Member 2 runs from L/4 to L/2: its own diagram gives its Cb.
    w = 1.2 * W_DEAD + 1.6 * W_LIVE
    from opensees_studio.core.design.aisc360 import cb_from_moments

    def moment(x: float) -> float:
        return w * x * (SPAN - x) / 2

    a, b = SPAN / 4, SPAN / 2
    cb = cb_from_moments(moment(b), *(moment(a + f * (b - a)) for f in (0.25, 0.5, 0.75)))
    assert middle.ratios["Major flexure"] == pytest.approx(_hand_ratio(w, SPAN / 4, cb), rel=1e-6)
    assert middle.ratios["Major shear"] > 0
    assert middle.ratios["Minor flexure"] == pytest.approx(0.0, abs=1e-9)


def test_overrides_change_the_unbraced_length_and_cb() -> None:
    project = _beam()
    settings = DesignSettings(members=[SteelMemberDesign(element_id=2, length_ltb=SPAN, cb=1.136)])
    report = steel_frame_check(project, _results(project), settings)
    middle = next(m for m in report.members if m.element_id == 2)
    w = 1.2 * W_DEAD + 1.6 * W_LIVE
    assert middle.ratios["Major flexure"] == pytest.approx(_hand_ratio(w, SPAN, 1.136), rel=1e-6)


def test_missing_results_and_unknown_shapes_are_reported() -> None:
    project = _beam(section_name="My girder")
    results = _results(project)
    report = steel_frame_check(project, {1: results[1]}, DesignSettings())
    assert any("run Case LIVE first" in note for note in report.notes)
    assert all(m.status == "not designed" for m in report.members)
    assert "not an AISC v16 shape" in report.members[0].notes[0]
    # Naming the shape on the member brings it back.
    named = DesignSettings(members=[SteelMemberDesign(element_id=1, shape="W18X50")])
    again = steel_frame_check(project, results, named)
    assert next(m for m in again.members if m.element_id == 1).status == "OK"


def test_axial_sign_tension_and_compression() -> None:
    def column(force: float) -> Project:
        section = shape_to_elastic_section(
            get_shape("W14X90"), elastic_modulus=E, shear_modulus=G, units=KIP_IN, ndm=2
        )
        return Project(
            meta=ProjectMeta(units=KIP_IN),
            ndm=2,
            ndf=3,
            nodes=[
                Node(id=1, coords=(0, 0, 0), restraint=(True, False, True, False, True, False)),
                Node(
                    id=2, coords=(0, 0, 144.0), restraint=(True, False, False, False, False, False)
                ),
            ],
            sections=[section],
            elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
            time_series=[LinearTimeSeries(id=1)],
            load_patterns=[
                PlainLoadPattern(
                    id=1,
                    time_series_id=1,
                    nodal_loads=[NodalLoad(node_id=2, forces=(0, 0, force, 0, 0, 0))],
                )
            ],
            analyses=[StaticCase(id=1, name="P", pattern_ids=[1])],
        )

    pulled = column(100.0)
    pushed = column(-100.0)
    tension = steel_frame_check(pulled, _results(pulled)).members[0]
    compression = steel_frame_check(pushed, _results(pushed)).members[0]
    assert "Tension" in tension.ratios and "Compression" in compression.ratios
    assert tension.ratios["Tension"] == pytest.approx(100.0 / (0.9 * 50.0 * 26.5), rel=1e-9)
    assert compression.ratios["Compression"] > tension.ratios["Tension"]


def test_drift_check_needs_storeys() -> None:
    project = _beam()
    results = _results(project)
    assert storey_drift_check(project, results[1]) is None


def test_drift_check_of_the_diaphragm_building() -> None:
    from examples.building_3storey_diaphragm import build_building

    project = build_building()
    case = next(c for c in project.analyses if c.name == "EQX")
    results = OpenSeesRunner(project).run(case)
    report = storey_drift_check(
        project, results, DesignSettings(drift_limit=0.002, drift_amplification=2.0)
    )
    assert report is not None
    assert len(report.rows) == 3
    first = report.rows[0]
    # Storey 1: drift ratio = u(3.5 m) / 3.5, amplified twice, over 0.002.
    assert first.ratio == pytest.approx(max(first.drift) / 0.002)
    assert first.drift[0] > 0


@pytest.mark.parametrize("ndm", [2, 3])
@pytest.mark.parametrize(
    ("shape", "zx"),
    [("HSS12X6X1_2", 57.4), ("Pipe10STD", 36.9), ("C12X20_7", None), ("WT9X17_5", None)],
)
def test_other_families_are_checked_end_to_end(ndm: int, shape: str, zx: float | None) -> None:
    """A beam of an HSS, a pipe, a channel or a tee: the ratio uses its own family's strength."""
    project = _beam(ndm, section_name=shape, shape=shape)
    report = steel_frame_check(project, _results(project), DesignSettings())
    middle = next(m for m in report.members if m.element_id == 2)
    assert middle.status in ("OK", "NG")
    assert middle.shape == shape
    moment = (1.2 * W_DEAD + 1.6 * W_LIVE) * SPAN**2 / 8
    if zx is not None:  # compact and unbraced length below Lp: φMn = 0.9 Fy Zx
        assert middle.ratios["Major flexure"] == pytest.approx(moment / (0.9 * 50 * zx), rel=1e-3)
    else:
        from opensees_studio.services.steel_design import shape_in_units

        strength = shape_in_units(shape, KIP_IN).flexure_major(
            Steel(50.0, E, G), "LRFD", unbraced=SPAN / 4, cb=middle_cb(project)
        )
        assert middle.ratios["Major flexure"] == pytest.approx(
            moment / strength.available, rel=2e-2
        )


def middle_cb(project: Project) -> float:
    """Cb of member 2 (L/4 to L/2 of a uniformly loaded span), from F1-1."""
    from opensees_studio.core.design.aisc360 import cb_from_moments

    def m(x: float) -> float:
        return x * (SPAN - x) / 2

    q = SPAN / 4
    return cb_from_moments(m(2 * q), m(q + q / 4), m(q + q / 2), m(q + 3 * q / 4))


def test_unequal_angle_is_reported_not_designed() -> None:
    project = _beam(2, section_name="L4X3X1_2", shape="L4X3X1_2")
    report = steel_frame_check(project, _results(project), DesignSettings())
    member = report.members[0]
    assert member.status == "not designed"
    assert "unequal legs" in member.notes[0]
