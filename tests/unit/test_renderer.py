"""Unit tests for ModelRenderer (high-perf glyphed implementation)."""

from __future__ import annotations

import pytest

pv = pytest.importorskip("pyvista")
import numpy as np  # noqa: E402

from opensees_studio.core import (  # noqa: E402
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    Steel01,
    TrussElement,
)
from opensees_studio.services.deformation import DeformationSource  # noqa: E402
from opensees_studio.views.canvas3d.model_renderer import (  # noqa: E402
    ModelRenderer,
    RendererMode,
    _classify_support,
)


# ──────────────────────────── support classification ────────────────────────────
def test_classify_support_full_fix() -> None:
    assert _classify_support((True,) * 6, (0, 1, 2, 3, 4, 5)) == "fix"


def test_classify_support_pin_3d() -> None:
    assert _classify_support(
        (True, True, True, False, False, False), (0, 1, 2, 3, 4, 5)
    ) == "pin"


def test_classify_support_pin_2d() -> None:
    assert _classify_support(
        (True, True, False, False, False, False), (0, 1)
    ) == "fix"
    assert _classify_support(
        (True, True, False, False, False, False), (0, 1, 5)
    ) == "pin"


def test_classify_support_roller() -> None:
    assert _classify_support(
        (False, True, False, False, False, False), (0, 1, 5)
    ) == "roller"


# ──────────────────────────── renderer fixtures ────────────────────────────
@pytest.fixture
def offscreen_plotter():  # type: ignore[no-untyped-def]
    pv.OFF_SCREEN = True
    p = pv.Plotter(off_screen=True)
    yield p
    p.close()


@pytest.fixture
def small_3d_project() -> Project:
    return Project(
        ndm=3, ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(id=2, coords=(0, 0, 3.0)),
            Node(id=3, coords=(4.0, 0, 3.0), mass=(100, 100, 0, 0, 0, 0)),
        ],
        materials=[Steel01(id=1, Fy=420e6, E0=200e9, b=0.01)],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-4,
                                 Iy=1e-4, G=80e9, J=1e-6)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            TrussElement(id=2, nodes=(2, 3), area=1e-3, material_id=1),
        ],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1, time_series_id=1,
                nodal_loads=[NodalLoad(node_id=3, forces=(0, 0, -10e3, 0, 0, 0))],
            )
        ],
    )


# ──────────────────────────── core rendering ────────────────────────────
def test_render_empty_project_does_not_raise(offscreen_plotter) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(None)
    r.render(Project())


def test_render_creates_node_and_frame_polydata(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    # One polydata for nodes, one for frames.
    assert r._node_pd is not None
    assert r._frame_pd is not None
    assert len(r._node_ids_ordered) == 3
    assert len(r._frame_ids_ordered) == 2


def test_render_attaches_picking_metadata(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    node_ids = set(np.asarray(r._node_pd["_oss_id"]).tolist())
    frame_ids = set(np.asarray(r._frame_pd.cell_data["_oss_id"]).tolist())
    assert node_ids == {1, 2, 3}
    assert frame_ids == {1, 2}


def test_render_twice_does_not_leak_actors(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    aux1 = len(r._aux_actors)
    r.render(small_3d_project)
    aux2 = len(r._aux_actors)
    assert aux1 == aux2  # not doubled


# ──────────────────────────── selection ────────────────────────────
def test_update_selection_writes_state_array(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    r.update_selection(frozenset({1, 3}), frozenset({2}))

    node_states = np.asarray(r._node_pd["_oss_state"]).tolist()
    frame_states = np.asarray(r._frame_pd.cell_data["_oss_state"]).tolist()
    # Nodes 1 and 3 selected → row 0 and row 2
    assert node_states == [1, 0, 1]
    # Element 2 selected → it's the second frame (index 1 in frame_ids_ordered)
    selected_frame_idx = r._frame_id_to_row[2]
    assert frame_states[selected_frame_idx] == 1


def test_clear_selection(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    r.update_selection(frozenset({1}), frozenset())
    r.update_selection(frozenset(), frozenset())
    assert all(v == 0 for v in np.asarray(r._node_pd["_oss_state"]))


# ──────────────────────────── deformation modes ────────────────────────────
def test_set_deformed_mode_shifts_node_positions(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    # Node 3 gets a 0.5m horizontal disp; others zero.
    disp = np.zeros((3, 3))
    disp[2] = (0.5, 0.0, 0.0)
    src = DeformationSource(
        displacements=disp, node_id_to_row={1: 0, 2: 1, 3: 2}, scale=1.0,
    )
    r.set_mode(RendererMode.DEFORMED, src)
    pts = np.asarray(r._node_pd.points)
    # Node 3 was at x=4.0 → now x=4.5
    assert abs(pts[2, 0] - 4.5) < 1e-9
    # Nodes 1 and 2 unchanged
    assert tuple(pts[0]) == (0.0, 0.0, 0.0)


def test_set_mode_back_to_model_restores_original(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    disp = np.array([[0, 0, 0], [0, 0, 0], [10.0, 0, 0]])
    src = DeformationSource(displacements=disp,
                            node_id_to_row={1: 0, 2: 1, 3: 2}, scale=1.0)
    r.set_mode(RendererMode.DEFORMED, src)
    r.set_mode(RendererMode.MODEL)
    pts = np.asarray(r._node_pd.points)
    # Node 3 back to (4, 0, 3)
    assert tuple(pts[2]) == (4.0, 0.0, 3.0)


def test_deformation_scale_multiplies_displacement(offscreen_plotter, small_3d_project) -> None:  # type: ignore[no-untyped-def]
    r = ModelRenderer(offscreen_plotter)
    r.render(small_3d_project)
    disp = np.array([[0, 0, 0], [0, 0, 0], [1.0, 0, 0]])
    src = DeformationSource(displacements=disp,
                            node_id_to_row={1: 0, 2: 1, 3: 2}, scale=10.0)
    r.set_mode(RendererMode.DEFORMED, src)
    pts = np.asarray(r._node_pd.points)
    # Node 3: 4.0 + 10.0 * 1.0 = 14.0
    assert abs(pts[2, 0] - 14.0) < 1e-9


# ──────────────────────────── degenerate geometry ────────────────────────────
def test_diag_handles_degenerate_geometry() -> None:
    pts = np.array([[0, 0, 0], [0, 0, 0]])
    assert ModelRenderer._diag_of_points(pts) == 1.0
    assert ModelRenderer._diag_of_points(None) == 1.0
