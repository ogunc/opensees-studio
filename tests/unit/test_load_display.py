"""core.load_display: which patterns are drawn, their colours and the value text."""

from __future__ import annotations

import pytest

from opensees_studio.core import PlainLoadPattern, ProjectMeta, UnitSystem
from opensees_studio.core.load_display import (
    PATTERN_PALETTE,
    format_force,
    format_line_load,
    format_pressure,
    hex_to_rgb,
    pattern_colors,
    shown_patterns,
)
from opensees_studio.core.units import UnitConverter
from opensees_studio.core.view_settings import ViewSettings

SI = UnitConverter.of(ProjectMeta(units=UnitSystem.SI_M_N))
KIP_IN = UnitConverter.of(ProjectMeta(units=UnitSystem.US_IN_KIP))


def _patterns(n: int) -> list[PlainLoadPattern]:
    return [PlainLoadPattern(id=i, name=f"P{i}", time_series_id=1) for i in range(1, n + 1)]


def test_all_patterns_or_the_one_chosen_or_all_when_it_is_gone() -> None:
    patterns = _patterns(3)
    assert shown_patterns(patterns, None) == patterns
    assert shown_patterns(patterns, 2) == [patterns[1]]
    assert shown_patterns(patterns, 99) == patterns


def test_each_pattern_keeps_its_colour_in_project_order_and_the_palette_wraps() -> None:
    colors = pattern_colors(_patterns(len(PATTERN_PALETTE) + 1))
    assert colors[1] == PATTERN_PALETTE[0]
    assert colors[len(PATTERN_PALETTE) + 1] == PATTERN_PALETTE[0]
    assert len(set(colors.values())) == len(PATTERN_PALETTE)
    assert hex_to_rgb("#ff8000") == pytest.approx((1.0, 128 / 255, 0.0))


def test_values_are_written_in_the_display_units() -> None:
    assert format_force(50_000.0, SI) == "50 kN"
    assert format_force(250.0, SI) == "250 N"
    assert format_force(11.2, KIP_IN) == "11.2 kip"
    assert format_line_load(10_000.0, None, SI) == "10 kN/m"
    assert format_line_load(0.0, 15_000.0, SI) == "0 to 15 kN/m"
    assert format_line_load(8_000.0, 8_000.0, SI) == "8 kN/m"
    assert format_line_load(0.5, None, KIP_IN) == "0.5 kip/in"
    assert format_pressure(2_500.0, SI) == "2.5 kPa"
    shown_in_kn_m = UnitConverter(model=UnitSystem.SI_MM_N, display=UnitSystem.SI_M_N)
    assert format_line_load(10.0, None, shown_in_kn_m) == "10 kN/m"  # 10 N/mm


def test_a_view_that_does_not_use_the_load_options_saves_without_them() -> None:
    assert (
        ViewSettings()
        .model_dump()
        .keys()
        .isdisjoint(
            {
                "load_pattern_id",
                "show_joint_loads",
                "show_frame_point_loads",
                "show_frame_distributed_loads",
                "show_shell_loads",
                "show_load_values",
            }
        )
    )
    chosen = ViewSettings(load_pattern_id=3, show_shell_loads=False, show_load_values=True)
    assert ViewSettings.model_validate(chosen.model_dump()) == chosen
