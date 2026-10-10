"""Every offered beam integration rule reaches the live build and runs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import openseespy.opensees as ops
import pytest

from opensees_studio.core import BEAM_INTEGRATION_RULES
from opensees_studio.services import load_project
from opensees_studio.services.opensees_runner import OpenSeesRunner

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
COLUMN_LENGTH = 144.0  # sectionLocation and sectionWeight come back scaled by it


def _with_rule(rule: str, points: int):  # type: ignore[no-untyped-def]
    project = load_project(EXAMPLES / "rc_frame_gravity.osmodel")
    project.elements = [
        el.model_copy(update={"integration": rule, "integration_points": points})
        if el.id in (1, 2)
        else el
        for el in project.elements
    ]
    return project


def test_lobatto_4_section_locations_in_the_live_build() -> None:
    project = _with_rule("Lobatto", 4)
    OpenSeesRunner(project).build()
    length = COLUMN_LENGTH
    root5 = 5.0**-0.5
    expected = length * np.array([0.0, (1 - root5) / 2, (1 + root5) / 2, 1.0])
    assert np.allclose(ops.sectionLocation(1), expected, rtol=0, atol=1e-9)
    weights = np.array(ops.sectionWeight(1)) / length
    assert np.allclose(weights, [1 / 12, 5 / 12, 5 / 12, 1 / 12], rtol=0, atol=1e-12)
    result = OpenSeesRunner(project).run(project.analyses[0])
    assert result.n_steps == project.analyses[0].n_steps


weights_by_rule: dict[str, tuple[float, ...]] = {}


@pytest.mark.parametrize("rule", BEAM_INTEGRATION_RULES)
def test_each_rule_takes_effect_and_the_gravity_case_runs(rule: str) -> None:
    points = 4
    project = _with_rule(rule, points)
    OpenSeesRunner(project).build()
    weights = ops.sectionWeight(1)
    assert len(weights) == points
    assert sum(weights) == pytest.approx(COLUMN_LENGTH, rel=1e-9)
    weights_by_rule[rule] = tuple(np.round(weights, 9))
    ops.wipe()
    result = OpenSeesRunner(project).run(project.analyses[0])
    assert result.disp(3, 2) < 0.0


def test_the_rules_give_different_weights() -> None:
    for rule in BEAM_INTEGRATION_RULES:
        if rule not in weights_by_rule:
            test_each_rule_takes_effect_and_the_gravity_case_runs(rule)
    assert len(set(weights_by_rule.values())) == len(BEAM_INTEGRATION_RULES)


def test_composite_simpson_stays_refused_because_the_build_gets_it_wrong() -> None:
    """Why CompositeSimpson is not offered: its weights do not add up to the length."""
    project = _with_rule("Lobatto", 5)
    OpenSeesRunner(project).build()
    ops.beamIntegration("CompositeSimpson", 99, 1, 5)
    ops.element("forceBeamColumn", 99, 1, 3, 1, 99)
    assert sum(ops.sectionWeight(99)) == pytest.approx(COLUMN_LENGTH * 4 / 3, rel=1e-9)
