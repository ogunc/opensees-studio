"""The runner's shell-resultant reader: averaging, and what it refuses.

`eleResponse(tag, "stresses")` is element-specific and lies in shape as well as
in value, so the runner is defensive about it: a ShellMITC4 answers with four
gauss points of eight resultants, a bar answers with nothing, and a `Linear`
static algorithm answers with zeros (which the contour view reports as "not
reported" — see `reports/SHELL_CONTOURS_PLAN_2026-10-09.md`).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from opensees_studio.core import Node, Project
from opensees_studio.services.opensees_runner import OpenSeesRunner

#: Four gauss points of N11, N22, N12, M11, M22, M12, V13, V23.
FOUR_POINTS = [
    1000.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    2000.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    3000.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    4000.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
]


def _runner(ops: MagicMock) -> OpenSeesRunner:
    return OpenSeesRunner(
        Project(ndm=3, ndf=6, nodes=[Node(id=1, coords=(0, 0, 0))]), ops_module=ops
    )


def test_the_four_gauss_points_are_averaged() -> None:
    ops = MagicMock()
    ops.eleResponse.return_value = FOUR_POINTS
    values = _runner(ops)._element_stress_resultants(20)
    assert values is not None
    assert values.shape == (8,)
    assert values[0] == pytest.approx(2500.0)
    assert np.allclose(values[1:], 0.0)


def test_only_the_component_that_is_applied_shows_up() -> None:
    """The order is the contract: a moment must not land in a membrane slot."""
    point = [0.0, 0.0, 0.0, 500.0, 0.0, 0.0, 0.0, 0.0]  # M11 only
    ops = MagicMock()
    ops.eleResponse.return_value = point * 4
    values = _runner(ops)._element_stress_resultants(20)
    assert values is not None
    assert values[3] == pytest.approx(500.0)  # M11
    assert values[0] == 0.0 and values[1] == 0.0 and values[2] == 0.0


@pytest.mark.parametrize("answer", [[], None, [1.0, 2.0, 3.0]])
def test_an_element_that_does_not_report_resultants_is_skipped(answer: object) -> None:
    ops = MagicMock()
    ops.eleResponse.return_value = answer
    assert _runner(ops)._element_stress_resultants(1) is None


def test_an_element_that_raises_is_skipped() -> None:
    """Bars, trusses and zero-length elements simply do not have the response."""
    ops = MagicMock()
    ops.eleResponse.side_effect = RuntimeError("no such response")
    assert _runner(ops)._element_stress_resultants(1) is None


def test_a_zero_answer_is_recorded_as_zero_not_thrown_away() -> None:
    """A `Linear` solve reports zeros: the view must be able to say so."""
    ops = MagicMock()
    ops.eleResponse.return_value = [0.0] * 32
    values = _runner(ops)._element_stress_resultants(1)
    assert values is not None
    assert np.all(values == 0.0)
