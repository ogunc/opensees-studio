"""The colour bands of a design ratio: steps at 0.5, 0.7, 0.9 and the limit."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core.design.ratio_bands import (
    NOT_DESIGNED_COLOR,
    ratio_bands,
    ratio_color,
    ratio_text,
)


def test_bands_step_at_fractions_of_the_limit() -> None:
    bands = ratio_bands(1.0)
    assert [b.upper for b in bands[:-1]] == [0.5, 0.7, 0.9, 1.0]
    assert math.isinf(bands[-1].upper)
    assert bands[-1].label == "> 1.00"
    assert [b.upper for b in ratio_bands(0.8)[:-1]] == pytest.approx([0.4, 0.56, 0.72, 0.8])


def test_colours_follow_the_bands() -> None:
    bands = ratio_bands()
    assert ratio_color(0.2) == bands[0].color
    assert ratio_color(0.5) == bands[0].color  # an upper bound belongs to its band
    assert ratio_color(0.95) == bands[3].color
    assert ratio_color(1.0) == bands[3].color
    assert ratio_color(1.01) == bands[-1].color
    assert ratio_color(1.01, limit=1.1) == bands[3].color


def test_a_ratio_prints_with_three_decimals_everywhere() -> None:
    # The overlay used two (0.28) while the report showed 0.28389: the same
    # number read as two different ones.
    assert ratio_text(0.28389) == "0.284"
    assert ratio_text(1.0) == "1.000"
    assert ratio_text(0.0) == "0.000"


def test_the_overlay_report_and_memory_print_the_same_ratio() -> None:
    from opensees_studio.core import Project
    from opensees_studio.services.calc_memory import build_member_memory
    from opensees_studio.services.steel_design import DesignReport, MemberResult

    member = MemberResult(element_id=4, shape="W10X12", status="OK", ratio=0.28389)
    page = build_member_memory(Project(), DesignReport(members=[member]), fmt="markdown")
    assert "| 4 | W10X12 | 0.284 | OK |" in page


def test_a_member_not_designed_is_grey_whatever_its_ratio() -> None:
    assert ratio_color(5.0, designed=False) == NOT_DESIGNED_COLOR
