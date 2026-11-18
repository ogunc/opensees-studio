"""The reaction overlay draws one batch of arrows and one of arcs.

No GL here: the renderer is driven against a recording plotter, so what is
checked is the geometry it hands to the plotter, not the pixels.
"""

from __future__ import annotations

import numpy as np
from tools.render_bench import RecordingPlotter

from opensees_studio.core import Node, Project
from opensees_studio.core.reactions import ReactionRow
from opensees_studio.views.canvas3d.model_renderer import ModelRenderer


def _render(rows: list[ReactionRow], *, show: bool) -> RecordingPlotter:
    project = Project(
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(4.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=3, coords=(8.0, 0.0, 0.0)),
        ]
    )
    plotter = RecordingPlotter()
    renderer = ModelRenderer(plotter)
    renderer.render(project)
    renderer.set_reactions(rows, show=show)
    return plotter


_ROWS = [
    ReactionRow(node_id=1, forces=(0.0, 0.0, -10.0), moments=(0.0, 0.0, 0.0)),
    ReactionRow(node_id=2, forces=(0.0, 0.0, -30.0), moments=(0.0, 0.0, 5.0)),
]


def test_the_overlay_draws_arrows_and_arcs() -> None:
    plotter = _render(_ROWS, show=True)

    assert "reactions_forces" in plotter.named
    assert "reactions_moments" in plotter.named, "the moment of node 2 needs an arc"


def test_the_arrows_sit_on_the_restrained_nodes() -> None:
    plotter = _render(_ROWS, show=True)
    bounds = np.asarray(plotter.named["reactions_forces"][-1].bounds)

    assert bounds[0] <= 0.0 and bounds[1] >= 4.0, "one arrow at each restrained node"
    assert bounds[2] < 8.0, "the free node gets no arrow"


def test_nothing_is_drawn_when_the_toggle_is_off() -> None:
    plotter = _render(_ROWS, show=False)

    assert "reactions_forces" not in plotter.named
    assert "reactions_moments" not in plotter.named


def test_a_case_without_reactions_draws_nothing() -> None:
    plotter = _render([], show=True)

    assert "reactions_forces" not in plotter.named
