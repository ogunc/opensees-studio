"""Drawing on a model that already has members.

The report — "no se puede dibujar nodos y elementos frame" — on a project that
already held a portal frame: every click near a column or a rafter hit the
*member*, and a member is not a drawing target. The canvas emitted
`elementPicked`, the tools' base handler ignores it, and the click vanished with
no message at all: no node, no element, nothing in the status bar.

A member is now only a pick target for the select tool. Nodes stay pickable, so
an existing node is still reused as an endpoint.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from opensees_studio.commands import AddElementsCommand, AddNodesCommand, AddSectionsCommand
from opensees_studio.core import ElasticBeamColumn, ElasticSection, Node

MIDPOINT = np.array([[2.0, 0.0, 0.0]])  # the middle of the member below


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1100, 750)
    win.show()
    qtbot.waitExposed(win)
    win._vm.new_project(ndm=2, ndf=3)
    win._vm.apply_command(
        AddNodesCommand(win._vm, [Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(4, 0, 0))]),
    )
    win._vm.apply_command(
        AddSectionsCommand(win._vm, [ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5)]),
    )
    win._vm.apply_command(
        AddElementsCommand(win._vm, [ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)]),
    )
    win._on_view_top()
    return win


def _click_on_member(window, dx: int = 0, dy: int = 0) -> None:  # type: ignore[no-untyped-def]
    canvas = window._canvas
    screen = canvas._project_world_to_screen(MIDPOINT, canvas.renderer)
    assert screen is not None
    x, y = float(screen[0][0]) + dx, canvas.height() - float(screen[0][1]) + dy
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(int(x), int(y)),
    )


@pytest.mark.gui
def test_draw_node_over_a_member_places_the_node(qtbot, window) -> None:  # type: ignore[no-untyped-def]
    window._on_draw_node_tool()

    _click_on_member(window)

    assert len(window._vm.project.nodes) == 3
    assert "added node 3" in window.statusBar().currentMessage()


@pytest.mark.gui
def test_draw_frame_over_a_member_builds_the_frame(qtbot, window) -> None:  # type: ignore[no-untyped-def]
    """Two clicks that both land on members still draw the frame."""
    window._on_draw_frame_tool()

    _click_on_member(window, dx=-120, dy=-60)
    assert "first node" in window.statusBar().currentMessage()
    _click_on_member(window, dx=120, dy=60)

    assert len(window._vm.project.elements) == 2, window.statusBar().currentMessage()


@pytest.mark.gui
def test_the_select_tool_still_picks_the_member(qtbot, window) -> None:  # type: ignore[no-untyped-def]
    """The change is scoped to the draw tools: Select must keep working."""
    canvas = window._canvas
    window._act_tool_select.trigger()
    seen: list[int] = []
    canvas.elementPicked.connect(seen.append)

    _click_on_member(window)

    assert seen == [1]
    assert canvas.selection.elements == frozenset({1})


@pytest.mark.gui
def test_a_node_on_the_member_is_still_reused(qtbot, window) -> None:  # type: ignore[no-untyped-def]
    """The node at (0, 0, 0) is a target: clicking it must not create a duplicate."""
    canvas = window._canvas
    window._on_draw_frame_tool()
    screen = canvas._project_world_to_screen(np.array([[0.0, 0.0, 0.0]]), canvas.renderer)
    assert screen is not None
    x, y = float(screen[0][0]), canvas.height() - float(screen[0][1])

    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(int(x), int(y)),
    )

    assert len(window._vm.project.nodes) == 2  # reused, not duplicated
    assert "first node = 1" in window.statusBar().currentMessage()
