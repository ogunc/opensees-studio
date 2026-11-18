"""RC fibre templates: the concrete fills the section once and the bars sit where stated."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core.sections import rc_circular_fibres, rc_rectangular_fibres


def _rect_area(p) -> float:  # type: ignore[no-untyped-def]
    return abs((p.y_j - p.y_i) * (p.z_j - p.z_i))


def test_rectangle_concrete_area_and_bars() -> None:
    patches, layers = rc_rectangular_fibres(
        core_material_id=1,
        cover_material_id=2,
        steel_material_id=3,
        h=0.6,
        b=0.4,
        cover=0.05,
        n_top=4,
        n_bottom=3,
        n_side=2,
        bar_area=3e-4,
    )
    assert sum(_rect_area(p) for p in patches) == pytest.approx(0.6 * 0.4)
    assert _rect_area(patches[0]) == pytest.approx(0.5 * 0.3)  # the confined core
    assert {p.material_id for p in patches[1:]} == {2}
    assert sum(lay.n_bars for lay in layers) == 4 + 3 + 2 * 2
    assert layers[0].y_start == pytest.approx(0.25)  # top bars at h/2 - cover


def test_circle_rings_and_bars() -> None:
    patches, bars = rc_circular_fibres(
        core_material_id=1,
        cover_material_id=2,
        steel_material_id=3,
        diameter=0.6,
        cover=0.05,
        n_bars=8,
        bar_area=3e-4,
    )
    assert (patches[0].r_outer, patches[1].r_inner, patches[1].r_outer) == (0.25, 0.25, 0.3)
    assert len(bars) == 8
    assert all(math.hypot(b.y_start, b.z_start) == pytest.approx(0.25) for b in bars)


@pytest.mark.parametrize(
    "bad",
    [{"cover": 0.3}, {"n_top": 1}, {"bar_area": 0.0}],
)
def test_bad_rectangles_are_refused(bad) -> None:  # type: ignore[no-untyped-def]
    args = dict(
        core_material_id=1,
        cover_material_id=2,
        steel_material_id=3,
        h=0.6,
        b=0.4,
        cover=0.05,
        n_top=3,
        n_bottom=3,
        n_side=0,
        bar_area=3e-4,
    )
    with pytest.raises(ValueError):
        rc_rectangular_fibres(**{**args, **bad})
