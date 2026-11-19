"""The canvas loads: one pattern or all, by kind, stacked in colours, with values."""

from __future__ import annotations

import pytest

pv = pytest.importorskip("pyvista")
import numpy as np  # noqa: E402

from opensees_studio.core import (  # noqa: E402
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    PointElementLoad,
    Project,
    TrapezoidalElementLoad,
    UniformElementLoad,
)
from opensees_studio.core.load_display import PATTERN_PALETTE, hex_to_rgb  # noqa: E402
from opensees_studio.core.view_settings import ViewSettings  # noqa: E402
from opensees_studio.views.canvas3d.model_renderer import ModelRenderer  # noqa: E402
from opensees_studio.views.canvas3d.style import RenderStyle  # noqa: E402

KN = 1_000.0


@pytest.fixture
def plotter():  # type: ignore[no-untyped-def]
    pv.OFF_SCREEN = True
    p = pv.Plotter(off_screen=True, window_size=(800, 400))
    yield p
    p.close()


def _beam() -> Project:
    """A 6 m 2D beam: DEAD uniform, LIVE 50 kN, EQUIPMENT 20 kN, PARTITION partial."""
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, False, True, False, False, False)),
            Node(id=2, coords=(6.0, 0.0, 0.0), restraint=(False, False, True, False, False, False)),
        ],
        sections=[ElasticSection(id=1, E=200e9, A=5.7e-3, Iz=1.21e-4)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="DEAD",
                time_series_id=1,
                element_loads=[UniformElementLoad(element_id=1, wy=-10 * KN)],
            ),
            PlainLoadPattern(
                id=2,
                name="LIVE",
                time_series_id=1,
                point_loads=[PointElementLoad(element_id=1, py=-50 * KN, x=0.5)],
            ),
            PlainLoadPattern(
                id=3,
                name="EQUIPMENT",
                time_series_id=1,
                point_loads=[PointElementLoad(element_id=1, py=-20 * KN, x=0.25)],
            ),
            PlainLoadPattern(
                id=4,
                name="PARTITION",
                time_series_id=1,
                distributed_loads=[
                    TrapezoidalElementLoad(
                        element_id=1, x_start=1 / 3, x_end=2 / 3, wy_start=-8 * KN, wy_end=-8 * KN
                    )
                ],
            ),
        ],
    )


def _render(plotter, **settings: object) -> ModelRenderer:  # type: ignore[no-untyped-def]
    renderer = ModelRenderer(plotter, settings=ViewSettings(**settings))
    renderer.render(_beam())
    return renderer


def _mesh(renderer: ModelRenderer, name: str) -> pv.PolyData | None:
    actor = renderer._plotter.actors.get(name)
    return None if actor is None else pv.wrap(actor.GetMapper().GetInput())


def test_all_patterns_take_their_palette_colour_and_the_legend_names_them(plotter) -> None:  # type: ignore[no-untyped-def]
    renderer = _render(plotter)

    lines = _mesh(renderer, "loads_element")
    assert lines is not None
    colors = {tuple(row) for row in np.asarray(lines.cell_data["rgb"])}
    expected = {
        tuple(np.round(np.asarray(hex_to_rgb(PATTERN_PALETTE[i])) * 255).astype(int))
        for i in (0, 3)  # DEAD and PARTITION
    }
    assert colors == expected
    assert [label for label, _ in renderer._load_legend_entries] == [
        "Load patterns",
        "DEAD",
        "LIVE",
        "EQUIPMENT",
        "PARTITION",
    ]
    assert renderer._plotter.actors.get("loads_legend_4") is not None


def test_a_partial_load_is_stacked_above_the_uniform_one(plotter) -> None:  # type: ignore[no-untyped-def]
    lines = _mesh(_render(plotter), "loads_element")
    assert lines is not None
    rgb = np.asarray(lines.cell_data["rgb"])
    partition = tuple(np.round(np.asarray(hex_to_rgb(PATTERN_PALETTE[3])) * 255).astype(int))
    points = np.asarray(lines.points)
    heights: dict[bool, list[float]] = {True: [], False: []}
    for cell in range(lines.n_cells):
        ids = lines.get_cell(cell).point_ids
        heights[tuple(rgb[cell]) == partition].extend(points[ids, 2].tolist())
    # Loads act down (-Z): the partition diagram sits wholly above the dead one,
    # and both above the 50 kN point load, which is drawn on the member.
    assert min(heights[True]) > max(heights[False]) - 1e-9
    assert min(heights[False]) > 0.0


def test_one_pattern_is_drawn_alone_in_the_colours_of_its_kind(plotter) -> None:  # type: ignore[no-untyped-def]
    renderer = _render(plotter, load_pattern_id=2)

    assert _mesh(renderer, "loads_element") is None
    arrows = _mesh(renderer, "loads_point")
    assert arrows is not None
    assert "rgb" not in arrows.point_data
    assert renderer._load_legend_entries == [["Load pattern: LIVE", RenderStyle().label_ink]]


def test_each_kind_of_load_can_be_hidden(plotter) -> None:  # type: ignore[no-untyped-def]
    renderer = _render(plotter, show_frame_point_loads=False)
    assert _mesh(renderer, "loads_point") is None
    assert _mesh(renderer, "loads_element") is not None
    assert [label for label, _ in renderer._load_legend_entries] == [
        "Load patterns",
        "DEAD",
        "PARTITION",
    ]

    plotter.clear()
    renderer = _render(plotter, show_frame_distributed_loads=False)
    assert _mesh(renderer, "loads_element") is None
    assert _mesh(renderer, "loads_point") is not None


def test_arrow_sizes_follow_the_forces(plotter) -> None:  # type: ignore[no-untyped-def]
    arrows = _mesh(_render(plotter, show_frame_distributed_loads=False), "loads_point")
    assert arrows is not None
    xs = np.asarray(arrows.points)[:, 0]
    zs = np.asarray(arrows.points)[:, 2]
    live = zs[np.abs(xs - 3.0) < 0.5]
    equipment = zs[np.abs(xs - 1.5) < 0.5]
    # Each arrow ends on the member and reaches up its length: 50 kN is longer.
    assert live.max() > equipment.max() * 1.5


def test_values_are_written_only_when_asked(plotter) -> None:  # type: ignore[no-untyped-def]
    assert _render(plotter)._load_values_actor is None
    plotter.clear()
    assert _render(plotter, show_load_values=True)._load_values_actor is not None


def test_a_single_pattern_project_draws_as_before_without_a_legend(plotter) -> None:  # type: ignore[no-untyped-def]
    project = _beam()
    project.load_patterns = project.load_patterns[:1]
    renderer = ModelRenderer(plotter)
    renderer.render(project)

    lines = _mesh(renderer, "loads_element")
    assert lines is not None
    assert "rgb" not in lines.cell_data
    assert renderer._load_legend_entries == []
