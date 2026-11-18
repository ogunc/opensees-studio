"""Design → Connections by Joint over real OpenSees results, against hand calculations.

The one-bay portal of ``tests/unit/test_direct_analysis.py``: its member ends
are classified (column bases, beam to column flange), a moment beam end gets
the RBS of an SMF, and a beam released at both ends under a uniform load gets a
shear tab checked with the end shear w L / 2. The shear tab's limit states are
pinned by hand on top of it, and the topologies of a 3D girder, a splice and a
brace.
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    UniformElementLoad,
)
from opensees_studio.core.design.joints import (
    BASE,
    GUSSET,
    RBS,
    SHEAR_TAB,
    SPLICE,
    joint_connections,
)
from opensees_studio.core.design.settings import DesignSettings
from opensees_studio.core.design.shear_tab import ShearTabDesign, check_shear_tab
from opensees_studio.core.geometry.frame_options import EndRelease, FrameReleases
from opensees_studio.services.joint_connections import connection_report
from opensees_studio.services.opensees_runner import OpenSeesRunner
from tests.unit.test_direct_analysis import _portal

SPAN = 240.0
W = 0.2  # kip/in on the beam


def _simple_beam_portal() -> Project:
    project = _portal()
    project.elements[2].releases = FrameReleases(
        i=EndRelease(released=("M3",)), j=EndRelease(released=("M3",))
    )
    project.load_patterns.append(
        PlainLoadPattern(
            id=4,
            name="BEAM",
            time_series_id=1,
            element_loads=[UniformElementLoad(element_id=3, wy=-W)],
        )
    )
    project.analyses = [StaticCase(id=1, name="BEAM", pattern_ids=[4])]
    return project


def test_the_portal_s_member_ends_are_classified() -> None:
    project = _portal()
    found = {
        (c.node_id, c.element_id, c.end): (c.topology, c.suggested)
        for c in joint_connections(project, DesignSettings(seismic_system="SMF"))
    }
    assert found == {
        (1, 1, "i"): ("column base", BASE),
        (2, 2, "i"): ("column base", BASE),
        (3, 3, "i"): ("beam to column flange", RBS),
        (4, 3, "j"): ("beam to column flange", RBS),
    }


def test_a_released_beam_end_gets_a_shear_tab_checked_with_its_end_shear() -> None:
    project = _simple_beam_portal()
    results = {1: OpenSeesRunner(project).run(project.analyses[0])}
    report = connection_report(project, results, DesignSettings())
    tabs = [r for r in report if r.connection.suggested == SHEAR_TAB]
    assert len(tabs) == 2
    for tab in tabs:
        assert tab.beam_shape == "W24X68"
        assert tab.vu == pytest.approx(W * SPAN / 2.0, rel=1e-6)
        assert tab.status == "OK"
        assert tab.load_set == "Case BEAM"


def test_shear_tab_limit_states_by_hand() -> None:
    tab = ShearTabDesign(
        element_id=1,
        end="i",
        bolts=4,
        bolt_diameter=0.75,
        spacing=3.0,
        edge_vertical=1.25,
        edge_horizontal=1.5,
        weld_to_bolts=3.0,
        tp=0.375,
        weld_leg=0.25,
        fexx=70.0,
    )
    vu = 40.0
    result = check_shear_tab(
        tab,
        vu=vu,
        fnv=54.0,
        plate_fy=36.0,
        plate_fu=58.0,
        web_thickness=0.415,
        web_fu=65.0,
        hole_extra=1 / 16,
        inch=1.0,
    )
    checks = {c.name: c.ratio for c in result.checks}
    length = 3 * 3.0 + 2 * 1.25  # 11.5 in
    assert checks["Plate shear yielding"] == pytest.approx(vu / (1.0 * 0.6 * 36 * length * 0.375))
    anv = (length - 4 * (0.8125 + 0.0625)) * 0.375
    assert checks["Plate shear rupture"] == pytest.approx(vu / (0.75 * 0.6 * 58 * anv))
    weld = 0.75 * 0.6 * 70 * 0.707 * 0.25 * length * 2
    assert checks["Fillet welds to the support"] == pytest.approx(vu / weld, rel=1e-3)
    # Most loaded bolt, e = 3 in, four bolts at 3 in: V/4 down plus M c / sum r^2.
    ip = 2 * (1.5**2 + 4.5**2)
    most = math.hypot(vu / 4, vu * 3.0 * 4.5 / ip)
    one_bolt = 0.75 * 54 * math.pi * 0.75**2 / 4
    assert checks["Bolt shear (most loaded bolt, e = a)"] == pytest.approx(most / one_bolt)
    assert checks["Weld detailing w >= 5/8 tp"] == pytest.approx(0.625 * 0.375 / 0.25)
    assert checks["Ductility tp <= d/2 + 1/16 in"] == pytest.approx(0.375 / (0.375 + 0.0625))


def _frame3d() -> Project:
    """Column 1-2 (W14X90) spliced at 2 to column 2-3 (W14X61), a girder along X
    through 4-5-6 at the top with a beam along Y framing into its middle, and a brace."""
    fix = (True,) * 6
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=fix),
        Node(id=2, coords=(0.0, 0.0, 144.0)),
        Node(id=3, coords=(0.0, 0.0, 288.0)),
        Node(id=4, coords=(-120.0, 0.0, 288.0)),
        Node(id=5, coords=(120.0, 0.0, 288.0)),
        Node(id=6, coords=(0.0, 240.0, 288.0)),
        Node(id=7, coords=(240.0, 0.0, 0.0), restraint=fix),
    ]

    def section(sid: int) -> ElasticSection:
        return ElasticSection(id=sid, E=29000.0, A=20.0, Iz=900.0, Iy=300.0, G=11200.0, J=3.0)

    return Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[section(1), section(2), section(3), section(4), section(5)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(2, 3), section_id=2),
            ElasticBeamColumn(id=3, nodes=(4, 3), section_id=3),
            ElasticBeamColumn(id=4, nodes=(3, 5), section_id=5),
            ElasticBeamColumn(id=5, nodes=(3, 6), section_id=4),
            ElasticBeamColumn(id=6, nodes=(7, 2), section_id=4),
        ],
        time_series=[LinearTimeSeries(id=1)],
    )


def test_splices_girders_and_braces_are_recognised() -> None:
    found = {
        (c.node_id, c.element_id): (c.topology, c.suggested)
        for c in joint_connections(_frame3d(), DesignSettings())
    }
    assert found[(2, 2)] == ("column splice", SPLICE)
    assert (2, 1) not in found  # one splice per joint, on the upper column
    assert found[(1, 1)][0] == "column base"
    assert found[(2, 6)] == ("brace", GUSSET)
    assert found[(7, 6)] == ("brace", GUSSET)
    # The column is stiffer about local z, so its depth runs along local y,
    # which is global Y for a vertical member: the beam along Y meets a
    # flange, the two along X meet the web.
    assert found[(3, 5)][0] == "beam to column flange"
    assert found[(3, 3)][0] == "beam to column web"
    assert found[(3, 4)][0] == "beam to column web"


def test_a_girder_continuous_over_a_column_has_no_beam_end_there() -> None:
    project = _frame3d()
    project.elements[3] = project.elements[3].model_copy(update={"section_id": 3})
    found = {(c.node_id, c.element_id) for c in joint_connections(project, DesignSettings())}
    assert (3, 3) not in found and (3, 4) not in found
