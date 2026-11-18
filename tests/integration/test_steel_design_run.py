"""The steel frame check over real OpenSees results, against hand calculations.

A simply supported W18X50 under a uniform load: the major-axis moment wL²/8 and
Cb = 1.136 (F1-1) come out of the diagrams, so the ratio can be written down by
hand. Combinations, the axial sign, the 3D orientation and the reasons a member
is not designed are pinned on top of it.
"""

from __future__ import annotations

import math

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
    # The four elements are one physical member, braced only at its supports: the
    # middle two carry the peak moment, with Lb the whole span and Cb of the span.
    middle = next(m for m in report.members if m.element_id == 2)
    assert middle.status == "OK"
    assert middle.load_set == "Combination 1.2D+1.6L"
    assert middle.member_id == 1
    assert middle.unbraced == pytest.approx((SPAN, SPAN, SPAN))
    w = 1.2 * W_DEAD + 1.6 * W_LIVE
    assert middle.ratios["Major flexure"] == pytest.approx(
        _hand_ratio(w, SPAN, span_cb()), rel=1e-6
    )
    assert middle.station == pytest.approx(1.0, abs=0.02)
    assert any(m.ratios.get("Major shear", 0.0) > 0.0 for m in report.members)
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

    with_net = DesignSettings(
        fu=65.0,
        members=[SteelMemberDesign(element_id=1, net_area=20.0)],
    )
    rupture = steel_frame_check(pulled, _results(pulled), with_net).members[0]
    assert rupture.equation == "D2-2 rupture"
    assert rupture.ratios["Tension"] == pytest.approx(100.0 / (0.75 * 65.0 * 20.0))


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
            Steel(50.0, E, G), "LRFD", unbraced=SPAN, cb=span_cb()
        )
        assert middle.ratios["Major flexure"] == pytest.approx(
            moment / strength.available, rel=2e-2
        )


def span_cb() -> float:
    """Cb of a uniformly loaded simple span braced only at its ends (F1-1: 1.136)."""
    from opensees_studio.core.design.aisc360 import cb_from_moments

    def m(x: float) -> float:
        return x * (SPAN - x) / 2

    return cb_from_moments(m(SPAN / 2), m(SPAN / 4), m(SPAN / 2), m(3 * SPAN / 4))


def test_a_brace_at_midspan_halves_the_unbraced_length() -> None:
    """A member framing in at midspan, across the beam, holds it laterally there."""
    project = _beam(3)
    project.nodes.append(Node(id=99, coords=(SPAN / 2, 120.0, 0.0), restraint=(True,) * 6))
    project.elements.append(project.elements[0].model_copy(update={"id": 99, "nodes": (3, 99)}))
    report = steel_frame_check(project, _results(project), DesignSettings())
    middle = next(m for m in report.members if m.element_id == 2)
    lx, ly, lb = middle.unbraced
    assert lb == pytest.approx(SPAN / 2)
    assert ly == pytest.approx(SPAN / 2)
    # Nothing holds the beam vertically at midspan: major-axis buckling spans it all.
    assert lx == pytest.approx(SPAN)


def test_unequal_angle_is_reported_not_designed() -> None:
    project = _beam(2, section_name="L4X3X1_2", shape="L4X3X1_2")
    report = steel_frame_check(project, _results(project), DesignSettings())
    member = report.members[0]
    assert member.status == "not designed"
    assert "unequal legs" in member.notes[0]


def test_p_delta_lifts_the_ratio_of_a_beam_column() -> None:
    section = shape_to_elastic_section(
        get_shape("W14X90"), elastic_modulus=E, shear_modulus=G, units=KIP_IN, ndm=2
    )
    project = Project(
        meta=ProjectMeta(units=KIP_IN),
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(0.0, 0.0, 144.0)),
        ],
        sections=[section],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(20.0, 0.0, -200.0, 0.0, 0.0, 0.0))],
            )
        ],
        analyses=[StaticCase(id=1, name="P", pattern_ids=[1])],
    )
    results = _results(project)
    plain = steel_frame_check(project, results).members[0]
    amplified = steel_frame_check(project, results, DesignSettings(p_delta=True)).members[0]
    assert any("B1" in note for note in amplified.notes)
    assert amplified.ratio > plain.ratio


def test_the_seismic_system_adds_the_aisc_341_checks() -> None:
    project = _beam()
    results = _results(project)
    plain = steel_frame_check(project, results).members[0]
    assert not any(key.startswith("AISC 341") for key in plain.ratios)

    seismic = steel_frame_check(
        project, results, DesignSettings(seismic_system="SMF", ry=1.1)
    ).members[0]
    # A horizontal beam: flange case 7 and moment-frame web case 11.
    assert seismic.ratios["AISC 341 Flange (case 7)"] > 0.0
    assert "AISC 341 Web (case 11)" in seismic.ratios


def _portal() -> Project:
    """A one-bay, one-storey steel portal frame in the X-Z plane."""
    column = shape_to_elastic_section(
        get_shape("W14X99"),
        elastic_modulus=E,
        shear_modulus=G,
        units=KIP_IN,
        ndm=2,
        section_id=1,
    )
    beam = shape_to_elastic_section(
        get_shape("W18X50"),
        elastic_modulus=E,
        shear_modulus=G,
        units=KIP_IN,
        ndm=2,
        section_id=2,
    )
    return Project(
        meta=ProjectMeta(units=KIP_IN),
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(0.0, 0.0, 144.0)),
            Node(id=3, coords=(240.0, 0.0, 144.0)),
            Node(id=4, coords=(240.0, 0.0, 0.0), restraint=(True,) * 6),
        ],
        sections=[column, beam],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(2, 3), section_id=2),
            ElasticBeamColumn(id=3, nodes=(4, 3), section_id=1),
        ],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[
                    NodalLoad(node_id=2, forces=(20.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
                    NodalLoad(node_id=3, forces=(0.0, 0.0, -100.0, 0.0, 0.0, 0.0)),
                ],
            )
        ],
        analyses=[StaticCase(id=1, name="P", pattern_ids=[1])],
    )


def test_smf_joints_get_the_strong_column_weak_beam_ratio() -> None:
    project = _portal()
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="SMF"))
    assert {joint.node_id for joint in report.joints} == {2, 3}
    assert all(joint.ratio > 0.0 for joint in report.joints)
    assert all(joint.panel_ratio > 0.0 for joint in report.joints)
    assert all(joint.panel_status in ("OK", "NG") for joint in report.joints)
    assert all(joint.status in ("OK", "NG") for joint in report.joints)
    assert "joint(s) checked" in report.summary()


def test_the_member_result_carries_the_limit_state_records() -> None:
    project = _beam()
    member = steel_frame_check(project, _results(project)).members[0]
    assert member.checks
    names = {check.name for check in member.checks}
    assert "Major flexure" in names and "P-M interaction" in names
    assert all(check.capacity >= 0.0 for check in member.checks)


def test_the_seismic_checks_reach_the_member_records() -> None:
    project = _beam()
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="SMF"))
    assert any(check.name.startswith("AISC 341") for check in report.members[0].checks)


def test_smf_joints_report_continuity_plates() -> None:
    project = _portal()
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="SMF"))
    for joint in report.joints:
        assert joint.continuity_tlim > 0.0
        assert joint.continuity_tcf > 0.0
        assert joint.continuity_status in ("required", "check E3.6f.1(a)")


def test_the_rbs_connection_reaches_the_report() -> None:
    from opensees_studio.core.design.connections import RbsConnection

    project = _portal()
    project.connections = [
        RbsConnection(id=1, beam_element_id=2, column_element_id=1, a=4.5, b=13.0, c=1.0)
    ]
    report = steel_frame_check(project, _results(project))
    assert len(report.connections) == 1
    connection = report.connections[0]
    assert connection.status == "checked"
    assert connection.sh == pytest.approx(4.5 + 13.0 / 2.0)
    assert connection.z_rbs > 0.0 and connection.mpr > 0.0
    assert connection.protected_to == pytest.approx(4.5 + 13.0)


def test_an_invalid_rbs_connection_is_reported() -> None:
    from opensees_studio.core.design.connections import RbsConnection

    project = _portal()
    project.connections = [
        RbsConnection(id=1, beam_element_id=2, column_element_id=1, a=4.5, b=13.0, c=3.0)
    ]
    report = steel_frame_check(project, _results(project))
    assert report.connections[0].status == "invalid"
    assert "RBS c" in report.connections[0].notes[0]


def test_the_rbs_protected_zone_flags_a_node_inside() -> None:
    from opensees_studio.core.design.connections import RbsConnection

    project = _portal()
    project.connections = [
        RbsConnection(id=1, beam_element_id=2, column_element_id=1, a=4.5, b=13.0, c=1.0)
    ]
    report = steel_frame_check(project, _results(project))
    assert report.connections[0].zone_clear

    project.nodes.append(Node(id=99, coords=(10.0, 0.0, 144.0), restraint=(True,) * 6))
    report = steel_frame_check(project, _results(project))
    assert not report.connections[0].zone_clear
    assert any("protected zone" in note for note in report.connections[0].notes)


def test_the_rbs_flexure_check_uses_the_face_moment() -> None:
    from opensees_studio.core.design.connections import RbsConnection

    project = _portal()
    project.connections = [
        RbsConnection(id=1, beam_element_id=2, column_element_id=1, a=4.5, b=13.0, c=1.0)
    ]
    report = steel_frame_check(project, _results(project))
    connection = report.connections[0]
    assert connection.mpe > 0.0
    assert connection.mf > connection.mpr
    assert connection.flexure_status in ("OK", "NG")


def test_scbf_braces_check_their_slenderness() -> None:
    project = _portal()
    project.elements.append(ElasticBeamColumn(id=5, nodes=(1, 3), section_id=2))
    settings = DesignSettings(
        seismic_system="SCBF",
        members=[SteelMemberDesign(element_id=5, net_area=14.0, shear_lag=1.0)],
    )
    report = steel_frame_check(project, _results(project), settings)
    brace = next(member for member in report.members if member.element_id == 5)
    assert "SCBF brace slenderness (F2.5b)" in brace.ratios
    assert any(check.name.startswith("SCBF brace") for check in brace.checks)
    assert brace.ratios["SCBF brace net area (F2.5b(c))"] == pytest.approx(14.7 / 14.0)
    assert any("Ry Fy Ag" in note for note in brace.notes)


def test_scbf_brace_protected_zone_flags_a_node_inside() -> None:
    project = _portal()
    project.elements.append(ElasticBeamColumn(id=5, nodes=(1, 3), section_id=2))
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="SCBF"))
    zone = next(item for item in report.protected_zones if item.element_id == 5)
    assert zone.zone_clear

    project.nodes.append(Node(id=98, coords=(120.0, 0.0, 72.0), restraint=(True,) * 6))
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="SCBF"))
    zone = next(item for item in report.protected_zones if item.element_id == 5)
    assert not zone.zone_clear
    assert any("protected zone" in note for note in zone.notes)


def test_a_gusset_is_checked_against_the_expected_brace_force() -> None:
    from opensees_studio.core.design.gusset_model import Gusset

    project = _portal()
    project.elements.append(ElasticBeamColumn(id=5, nodes=(1, 3), section_id=2))
    project.gussets = [Gusset(id=1, brace_element_id=5, t=0.5, b=12.0, lw=10.0, free_length=10.0)]
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="SCBF"))
    gusset = report.gussets[0]
    assert gusset.shape == "W18X50"
    assert gusset.demand == pytest.approx(1.1 * 50.0 * 14.7)
    assert [check.name for check in gusset.checks] == [
        "Gusset Whitmore width",
        "Gusset yielding",
        "Gusset buckling",
    ]
    assert gusset.status in ("OK", "NG")


def test_scbf_capacity_design_scales_the_seismic_terms() -> None:
    project = _portal()
    project.elements.append(ElasticBeamColumn(id=5, nodes=(1, 3), section_id=2))
    project.analyses[0].name = "EQ"
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="SCBF"))
    assert len(report.capacity_design) == 1
    record = report.capacity_design[0]
    assert record.brace_element_id == 5
    assert record.state == "tension"
    assert record.analysis_force < 0.0
    assert record.expected_force == pytest.approx(1.1 * 50.0 * 14.7)
    assert record.factor == pytest.approx(record.expected_force / abs(record.analysis_force))
    beam = next(member for member in report.members if member.element_id == 2)
    assert beam.capacity_ratio > 0.0
    capacity_ratios = {
        key: value for key, value in beam.ratios.items() if key.startswith("SCBF capacity ")
    }
    assert capacity_ratios
    assert beam.capacity_ratio == pytest.approx(max(capacity_ratios.values()))

    plain = steel_frame_check(project, _results(project), DesignSettings())
    assert plain.capacity_design == []


def test_a_gusset_weld_is_checked_against_f2_6c_4() -> None:
    from opensees_studio.core.design.gusset_model import Gusset

    project = _portal()
    project.elements.append(ElasticBeamColumn(id=5, nodes=(1, 3), section_id=2))
    project.gussets = [
        Gusset(
            id=1,
            brace_element_id=5,
            t=0.5,
            b=12.0,
            lw=10.0,
            free_length=10.0,
            weld_leg=0.5,
        )
    ]
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="SCBF"))
    gusset = report.gussets[0]
    assert gusset.tension_demand == pytest.approx(1.1 * 50.0 * 14.7)
    assert gusset.compression_demand > 0.0
    assert gusset.flexure_demand > 0.0
    assert gusset.weld_leg == pytest.approx(0.5)
    capacity = 0.75 * 2.0 * 0.60 * 70.0 * math.sqrt(0.5) * 0.5
    assert gusset.weld_ratio == pytest.approx((0.60 * 1.1 * 50.0 * 0.5) / capacity)
    assert gusset.checks[-1].name == "Gusset-to-flange weld (F2.6c.4)"
    assert gusset.weld_status in ("OK", "NG")


def test_scbf_beam_column_joint_reports_f2_6b() -> None:
    from opensees_studio.core.design.connections import RbsConnection

    project = _portal()
    project.elements.append(ElasticBeamColumn(id=5, nodes=(1, 3), section_id=2))
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="SCBF"))
    joint = next(item for item in report.scbf_joints if item.node_id == 3)
    assert joint.beam_element_id == 2
    assert 3 in joint.column_element_ids
    assert joint.brace_element_id == 5
    assert joint.status == "simple / not checked"
    beam = ishape_in_units("W18X50", project.meta.units)
    column = ishape_in_units("W14X99", project.meta.units)
    expected = min(
        1.1 * 1.1 * 50.0 * beam.Zx,
        1.1 * 1.1 * 50.0 * column.Zx,
    )
    assert joint.required_moment == pytest.approx(expected)
    assert joint.notes

    project.connections = [
        RbsConnection(
            id=1,
            beam_element_id=2,
            column_element_id=3,
            a=4.5,
            b=13.0,
            c=1.0,
        )
    ]
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="SCBF"))
    joint = next(item for item in report.scbf_joints if item.node_id == 3)
    assert joint.available_moment > 0.0
    assert joint.ratio == pytest.approx(joint.required_moment / joint.available_moment)
    assert joint.status in ("OK", "NG")


def test_a_column_splice_reports_f2_6d() -> None:
    from opensees_studio.core.design.column_splice_model import ColumnSplice

    project = _portal()
    project.nodes.append(Node(id=5, coords=(0.0, 0.0, 288.0)))
    project.elements.append(ElasticBeamColumn(id=6, nodes=(2, 5), section_id=1))
    project.column_splices = [
        ColumnSplice(
            id=1,
            node_id=2,
            top_element_id=6,
            bottom_element_id=1,
            clear_height=144.0,
        )
    ]
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="SCBF"))
    splice = report.column_splices[0]
    column = ishape_in_units("W14X99", project.meta.units)
    assert splice.moment == pytest.approx(0.5 * 50.0 * column.Zx)
    assert splice.shear == pytest.approx(2.0 * 50.0 * column.Zx / 144.0)
    assert splice.status == "checked"


def test_ocbf_brace_slenderness_uses_f1_1() -> None:
    project = _portal()
    project.elements.append(ElasticBeamColumn(id=5, nodes=(1, 3), section_id=2))
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="OCBF"))
    brace = next(member for member in report.members if member.element_id == 5)
    limit = 4.0 * math.sqrt(29000.0 / 50.0)
    brace_shape = ishape_in_units("W18X50", project.meta.units)
    brace_length = math.sqrt(240.0**2 + 144.0**2)
    assert brace.ratios["OCBF brace slenderness (F1.5b)"] == pytest.approx(
        (brace_length / min(brace_shape.rx, brace_shape.ry)) / limit
    )
    assert any("F1.6a" in note for note in brace.notes)
    beam = next(member for member in report.members if member.element_id == 2)
    assert any("F1.5c" in note for note in beam.notes)
    assert any("F1.5b" in note for note in report.notes)
    assert any("F1.4b" in note for note in report.notes)
    assert any("F1.4c" in note for note in report.notes)
    assert any("F1.5a" in note for note in report.notes)


def test_ocbf_beam_reports_the_overstrength_combinations() -> None:
    project = _portal()
    project.elements.append(ElasticBeamColumn(id=5, nodes=(1, 3), section_id=2))
    project.combinations = [
        LoadCombination(
            id=1,
            name="O0: 1.2D+2.5E",
            terms=[CombinationTerm(ref_id=1, factor=2.5)],
        )
    ]
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="OCBF"))
    beam = next(member for member in report.members if member.element_id == 2)
    assert any("included in the envelope" in note for note in beam.notes)
    assert any("O0 overstrength combinations are included" in note for note in report.notes)


def test_ocbf_flags_a_brace_intersecting_a_beam() -> None:
    project = _portal()
    project.nodes.append(Node(id=5, coords=(120.0, 0.0, 144.0)))
    project.elements[1] = ElasticBeamColumn(id=2, nodes=(2, 5), section_id=2)
    project.elements.append(ElasticBeamColumn(id=6, nodes=(5, 3), section_id=2))
    project.elements.append(ElasticBeamColumn(id=7, nodes=(1, 5), section_id=2))
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="OCBF"))
    beam = next(member for member in report.members if member.element_id == 2)
    assert any("F1.4a" in note for note in beam.notes)
    assert any("node(s) [5]" in note for note in beam.notes)


def test_ocbf_gusset_connection_reports_f1_6a() -> None:
    from opensees_studio.core.design.gusset_model import Gusset

    project = _portal()
    project.elements.append(ElasticBeamColumn(id=5, nodes=(1, 3), section_id=2))
    project.gussets = [Gusset(id=1, brace_element_id=5, t=0.5, b=12.0, lw=10.0, free_length=10.0)]
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="OCBF"))
    gusset = report.gussets[0]
    assert any("F1.6a" in note for note in gusset.notes)


def test_the_rbs_beam_shear_and_span_are_checked() -> None:
    from opensees_studio.core.design.connections import RbsConnection

    project = _portal()
    project.connections = [
        RbsConnection(id=1, beam_element_id=2, column_element_id=1, a=4.5, b=13.0, c=1.0)
    ]
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="SMF"))
    connection = report.connections[0]
    assert connection.shear_demand == pytest.approx(connection.vh)
    assert connection.shear_capacity > 0.0
    assert connection.shear_ratio == pytest.approx(
        connection.shear_demand / connection.shear_capacity
    )
    assert connection.shear_status in ("OK", "NG")
    assert connection.span_limit == pytest.approx(7.0)
    assert connection.span_ratio > 0.0
    assert connection.span_status in ("OK", "NG")
    assert any("5.5" in note for note in connection.notes)
    assert any("5.3(7)" in note for note in connection.notes)

    plain = steel_frame_check(project, _results(project), DesignSettings())
    assert any("SMF and IMF" in note for note in plain.connections[0].notes)


def test_the_rbs_web_connection_checks_5_5() -> None:
    from opensees_studio.core.design.connections import RbsConnection

    project = _portal()
    connection = RbsConnection(
        id=1,
        beam_element_id=2,
        column_element_id=1,
        a=4.5,
        b=13.0,
        c=1.0,
        web_connection_type="bolted",
        web_plate_thickness=0.5,
        web_plate_height=12.0,
        web_bolt_count=4,
        web_bolt_diameter=0.75,
        web_weld_leg=0.375,
    )
    project.connections = [connection]
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="SMF"))
    result = report.connections[0]
    assert result.web_checks
    assert result.web_ratio > 0.0
    assert result.web_status in ("OK", "NG")
    assert any("5.5" in check.name for check in result.web_checks)
    assert any("bearing" in note for note in result.notes)

    connection.web_connection_type = "cjp"
    report = steel_frame_check(project, _results(project), DesignSettings(seismic_system="SMF"))
    result = report.connections[0]
    assert [check.name for check in result.web_checks] == ["Web plate thickness (5.5)"]
    assert any("CJP" in note for note in result.notes)


def test_chapter_j_checks_are_reported() -> None:
    from opensees_studio.core.design.chapter_j_model import ChapterJCheck

    project = _portal()
    project.chapter_j_checks = [
        ChapterJCheck(
            id=1,
            name="Fillet weld",
            check_type="fillet_weld",
            demand=40.0,
            fexx=70.0,
            weld_leg=0.25,
            weld_length=10.0,
            weld_both_sides=False,
        ),
        ChapterJCheck(
            id=2,
            name="Bolts",
            check_type="bolt_shear",
            demand=50.0,
            fn=54.0,
            bolt_diameter=0.75,
            bolt_count=4,
        ),
    ]
    report = steel_frame_check(project, _results(project), DesignSettings())
    assert len(report.chapter_j) == 2
    weld = report.chapter_j[0]
    assert weld.nominal == pytest.approx(74.247, rel=2e-3)
    assert weld.status in ("OK", "NG")
    bolts = report.chapter_j[1]
    assert bolts.nominal == pytest.approx(95.426, rel=2e-3)


def test_a_chapter_j_check_with_missing_data_is_invalid() -> None:
    from opensees_studio.core.design.chapter_j_model import ChapterJCheck

    project = _portal()
    project.chapter_j_checks = [ChapterJCheck(id=1, check_type="fillet_weld", demand=10.0)]
    report = steel_frame_check(project, _results(project), DesignSettings())
    assert report.chapter_j[0].status == "invalid"
    assert any("Missing fexx" in note for note in report.chapter_j[0].notes)


def test_chapter_j_j5_to_j8_checks_are_reported() -> None:
    from opensees_studio.core.design.chapter_j_model import ChapterJCheck

    project = _portal()
    project.chapter_j_checks = [
        ChapterJCheck(id=1, check_type="bearing_strength", demand=100.0, fy=50.0, apb=2.0),
        ChapterJCheck(id=2, check_type="concrete_bearing", demand=200.0, fc=4.0, a1=100.0),
        ChapterJCheck(id=3, check_type="splice", demand=800.0, splice_nominal=1000.0),
        ChapterJCheck(
            id=4,
            check_type="bolt_shear",
            demand=50.0,
            fn=54.0,
            bolt_diameter=0.75,
            bolt_count=4,
            filler_thickness=0.5,
        ),
    ]
    report = steel_frame_check(project, _results(project), DesignSettings())
    assert [item.status for item in report.chapter_j] == ["OK", "OK", "OK", "OK"]
    assert report.chapter_j[0].nominal == pytest.approx(180.0)
    assert report.chapter_j[1].nominal == pytest.approx(340.0)
    assert report.chapter_j[2].nominal == pytest.approx(1000.0)
    assert report.chapter_j[3].nominal == pytest.approx(95.426 * 0.9, rel=2e-3)
    assert any("J5.2" in note for note in report.chapter_j[3].notes)


def test_chapter_j_j10_concentrated_force_checks_are_reported() -> None:
    from opensees_studio.core.design.chapter_j_model import ChapterJCheck
    from opensees_studio.services.calc_memory import build_member_memory

    project = _portal()
    project.chapter_j_checks = [
        ChapterJCheck(
            id=1,
            name="Flange bending",
            check_type="flange_local_bending",
            demand=50.0,
            fy=50.0,
            flange_thickness=0.5,
            flange_width=6.0,
            bearing_length=2.0,
            distance_to_end=20.0,
        ),
        ChapterJCheck(
            id=2,
            name="Web yielding",
            check_type="web_local_yielding",
            demand=80.0,
            fy=50.0,
            web_thickness=0.3,
            fillet_k=1.0,
            bearing_length=2.0,
            member_depth=14.0,
            distance_to_end=20.0,
        ),
        ChapterJCheck(
            id=3,
            name="Web crippling",
            check_type="web_local_crippling",
            demand=100.0,
            fy=50.0,
            elastic_modulus=29000.0,
            web_thickness=0.3,
            flange_thickness=0.5,
            member_depth=14.0,
            bearing_length=2.0,
            distance_to_end=10.0,
        ),
        ChapterJCheck(
            id=4,
            name="Web sidesway",
            check_type="web_sidesway_buckling",
            demand=4000.0,
            fy=50.0,
            section_modulus=100.0,
            required_moment=1000.0,
            web_thickness=1.0,
            flange_thickness=0.5,
            clear_web_height=10.0,
            flange_width=8.0,
            bearing_length=100.0,
        ),
        ChapterJCheck(
            id=5,
            name="Web compression",
            check_type="web_compression_buckling",
            demand=200.0,
            fy=50.0,
            elastic_modulus=29000.0,
            web_thickness=0.5,
            clear_web_height=12.0,
            distance_to_end=10.0,
            member_depth=14.0,
        ),
    ]
    report = steel_frame_check(project, _results(project), DesignSettings())
    assert [item.status for item in report.chapter_j] == ["OK"] * 5
    assert report.chapter_j[0].nominal == pytest.approx(78.125)
    assert report.chapter_j[1].nominal == pytest.approx(105.0)
    assert report.chapter_j[2].nominal == pytest.approx(134.2227, rel=1e-5)
    assert report.chapter_j[3].nominal == pytest.approx(5783.04, rel=1e-6)
    assert report.chapter_j[4].nominal == pytest.approx(301.0399, rel=1e-5)
    page = build_member_memory(project, report, language="en", fmt="html")
    assert "Connection checks (AISC 360 Chapter J)" in page
    assert "flange_local_bending" in page
    assert "6.25 Fyf tf^2" in page
    assert "24 tw^3 sqrt(E Fyw)/h Qf" in page


def test_chapter_j_j10_not_required_cases_are_reported() -> None:
    from opensees_studio.core.design.chapter_j_model import ChapterJCheck

    project = _portal()
    project.chapter_j_checks = [
        ChapterJCheck(
            id=1,
            check_type="flange_local_bending",
            demand=10.0,
            fy=50.0,
            flange_thickness=0.5,
            flange_width=6.0,
            bearing_length=0.5,
            distance_to_end=20.0,
        ),
        ChapterJCheck(
            id=2,
            check_type="web_sidesway_buckling",
            demand=10.0,
            fy=50.0,
            section_modulus=100.0,
            required_moment=1000.0,
            web_thickness=0.3,
            flange_thickness=0.5,
            clear_web_height=12.0,
            flange_width=6.0,
            bearing_length=100.0,
        ),
    ]
    report = steel_frame_check(project, _results(project), DesignSettings())
    assert [item.status for item in report.chapter_j] == ["not required", "not required"]
    assert report.chapter_j[0].nominal == pytest.approx(0.0)
    assert report.chapter_j[1].nominal == pytest.approx(0.0)
    assert any("0.15 bf" in note for note in report.chapter_j[0].notes)
    assert any("does not apply" in note for note in report.chapter_j[1].notes)
