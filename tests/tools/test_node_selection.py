"""Selection recolours the node point cloud in place instead of rebuilding it.

The nodes are one point per joint, drawn as screen-space spheres, so the state
array is written directly onto the PolyData. These tests check the colour lands
on the right joint and that selecting does not add an actor.
"""

from __future__ import annotations

import numpy as np
from tools.render_bench import RecordingPlotter

from opensees_studio.core import Node, Project
from opensees_studio.views.canvas3d.model_renderer import ModelRenderer


def _rendered(nodes: list[Node]) -> tuple[ModelRenderer, RecordingPlotter, Project]:
    project = Project(nodes=nodes)
    plotter = RecordingPlotter()
    renderer = ModelRenderer(plotter)
    renderer.render(project)
    return renderer, plotter, project


def test_selection_colours_the_sphere_of_the_selected_node() -> None:
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0)),
        Node(id=2, coords=(5.0, 0.0, 0.0)),
        Node(id=3, coords=(0.0, 5.0, 0.0)),
    ]
    renderer, _plotter, project = _rendered(nodes)

    renderer.update_selection(frozenset({2}), frozenset())

    assert renderer._node_pd is not None
    states = np.asarray(renderer._node_pd["_oss_state"])
    points = np.asarray(renderer._node_pd.points)
    coords = np.array([node.coords for node in project.nodes])

    # One point per joint: the selected node (row 1) is the only cyan point.
    assert np.array_equal(points, coords)
    assert states.tolist() == [0, 1, 0]


def test_selecting_does_not_add_an_actor() -> None:
    renderer, plotter, _project = _rendered(
        [Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(5.0, 0.0, 0.0))]
    )
    actors_after_render = plotter.meshes

    renderer.update_selection(frozenset({1}), frozenset())

    assert plotter.meshes == actors_after_render, "selection must not re-add the actor"


def test_clearing_the_selection_clears_every_sphere() -> None:
    renderer, _plotter, _project = _rendered(
        [Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(5.0, 0.0, 0.0))]
    )
    renderer.update_selection(frozenset({1, 2}), frozenset())
    renderer.update_selection(frozenset(), frozenset())

    assert renderer._node_pd is not None
    states = np.asarray(renderer._node_pd["_oss_state"])
    assert not states.any()
