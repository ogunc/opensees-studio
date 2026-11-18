"""The steel check on a member whose section names a built-up shape, against the hand ratio."""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core.design.aisc360 import Steel
from opensees_studio.core.design.built_up import analysis_section, built_up_ishape
from opensees_studio.core.design.built_up_model import BuiltUpShape
from opensees_studio.core.design.settings import DesignSettings, SteelMemberDesign
from opensees_studio.services.steel_design import steel_frame_check
from tests.integration.test_steel_design_run import (
    SPAN,
    W_DEAD,
    W_LIVE,
    E,
    G,
    _beam,
    _results,
    span_cb,
)

GIRDER = BuiltUpShape(name="PG1", d=24.0, bf=10.0, tf=0.75, tw=0.375)


def test_a_section_named_after_a_built_up_shape_is_checked_with_it() -> None:
    project = _beam()
    # The analysis section Design → Built-Up Shapes creates for the girder.
    project.sections[0] = analysis_section(
        GIRDER, section_id=project.sections[0].id, elastic_modulus=E, shear_modulus=G, ndm=2
    )
    settings = DesignSettings(built_up=[GIRDER])
    report = steel_frame_check(project, _results(project), settings)
    middle = next(m for m in report.members if m.element_id == 2)
    assert middle.shape == "PG1"
    moment = (1.2 * W_DEAD + 1.6 * W_LIVE) * SPAN**2 / 8
    strength = built_up_ishape(GIRDER).flexure_major(
        Steel(50.0, E, G), "LRFD", unbraced=SPAN, cb=span_cb()
    )
    assert middle.ratios["Major flexure"] == pytest.approx(moment / strength.available, rel=1e-6)


def test_a_member_override_can_name_a_built_up_shape() -> None:
    project = _beam()
    settings = DesignSettings(
        built_up=[GIRDER],
        members=[SteelMemberDesign(element_id=2, shape="pg1")],
        steel_grades={"BU": "A36"},
    )
    report = steel_frame_check(project, _results(project), settings)
    middle = next(m for m in report.members if m.element_id == 2)
    assert middle.shape == "PG1"
    assert middle.grade == "ASTM A36"
    other = next(m for m in report.members if m.element_id == 1)
    assert other.shape == "W18X50"
