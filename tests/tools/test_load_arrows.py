"""Load arrows keep their geometry after batching into one glyph actor.

The arrows used to be one `pv.Arrow` per load, placed by hand. They are now a
point cloud oriented by the load vector, which is only correct if the glyph
filter aligns the template the way we believe — the first attempt had the arrow
lying along X. These tests pin the geometry: the tip sits on the joint, the body
extends against the load, and a load at 45 degrees is rotated, not stretched.
"""

from __future__ import annotations

import pytest
from tools.render_bench import RecordingPlotter

from opensees_studio.core import (
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
)
from opensees_studio.views.canvas3d.model_renderer import ModelRenderer

#: Two nodes 10 units apart: the arrow is a 5 % of the model diagonal long.
_SPAN = 10.0
_SCALE = _SPAN * 0.05
#: The arrowhead is wider than the shaft, so the perpendicular extent is not zero.
_HEAD = 0.12


def _load_arrow_bounds(force: tuple[float, float, float]) -> list[float]:
    """Bounds of the single nodal-load actor for one load at the origin."""
    project = Project(
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(0.0, 0.0, _SPAN)),
        ],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=1, forces=(*force, 0.0, 0.0, 0.0))],
            )
        ],
    )
    plotter = RecordingPlotter()
    ModelRenderer(plotter).render(project)
    return list(plotter.named["loads_nodal"][0].bounds)


def test_a_downward_load_has_its_tip_on_the_joint() -> None:
    xmin, xmax, ymin, ymax, zmin, zmax = _load_arrow_bounds((0.0, 0.0, -1000.0))

    assert zmin == pytest.approx(0.0, abs=1e-3), "the tip must end on the joint"
    assert zmax == pytest.approx(_SCALE, abs=1e-2), "the body goes against the load"
    assert abs(xmax - xmin) < _HEAD and abs(ymax - ymin) < _HEAD, "a Z load must not lean"


def test_the_arrow_follows_the_load_direction() -> None:
    xmin, xmax, _ymin, _ymax, zmin, zmax = _load_arrow_bounds((1000.0, 0.0, 0.0))

    assert xmax == pytest.approx(0.0, abs=1e-3), "the tip must end on the joint"
    assert xmin == pytest.approx(-_SCALE, abs=1e-2), "the body goes against the load"
    assert abs(zmax - zmin) < _HEAD


def test_a_diagonal_load_is_rotated_not_stretched() -> None:
    xmin, xmax, _ymin, _ymax, zmin, zmax = _load_arrow_bounds((1000.0, 0.0, -1000.0))

    span_x = abs(xmax - xmin)
    span_z = abs(zmax - zmin)
    # 45 degrees: the body covers the same length along both axes.
    assert span_x == pytest.approx(span_z, rel=0.15)
    assert 0.2 < span_x < _SCALE + _HEAD
