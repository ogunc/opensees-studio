"""The Reactions tab shows what the viewport arrows draw."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import Node, Project
from opensees_studio.core.reactions import ReactionRow
from opensees_studio.views.docks.reactions_panel import ReactionsPanel


@pytest.mark.gui
def test_the_table_lists_every_component(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = ReactionsPanel()
    qtbot.addWidget(panel)

    panel.set_rows([ReactionRow(node_id=7, forces=(1.5, -2.0, 3.0), moments=(0.0, 0.5, -1.0))])

    assert panel.rows == 1
    table = panel._table
    assert [table.item(0, c).text() for c in range(7)] == [
        "7",
        "1.5",
        "-2",
        "3",
        "0",
        "0.5",
        "-1",
    ]


@pytest.mark.gui
def test_no_reactions_leaves_an_empty_table(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = ReactionsPanel()
    qtbot.addWidget(panel)

    panel.show_results(None, Project(nodes=[Node(id=1, coords=(0.0, 0.0, 0.0))]))

    assert panel.rows == 0


@pytest.mark.gui
def test_the_canvas_exposes_the_reaction_overlay(qtbot) -> None:  # type: ignore[no-untyped-def]
    """The window calls this on the canvas; it living only on the renderer broke the app."""
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas

    canvas = ModelCanvas()
    qtbot.addWidget(canvas)

    canvas.set_reactions([], show=False)
