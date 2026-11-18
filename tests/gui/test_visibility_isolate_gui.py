"""GUI tests for hiding, isolating and box-selecting only what is visible."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import QRectF

from opensees_studio.views.main_window import MainWindow

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "isolated_portal2d.osmodel"


def _window(qtbot):  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.open(EXAMPLE)
    return window


@pytest.mark.gui
def test_isolate_shows_only_the_selection_and_show_all_restores_it(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(qtbot)
    project = window._vm.project
    assert project is not None
    element = next(element for element in project.elements if len(element.nodes) >= 2)
    element_nodes = set(element.nodes)
    window._canvas.selection.set_selection(set(), {element.id})
    window._refresh_action_enablement()

    assert window._act_isolate_selected.isEnabled()
    window._act_isolate_selected.trigger()

    hidden_nodes, hidden_elements = window._canvas.hidden
    assert hidden_nodes == frozenset({node.id for node in project.nodes} - element_nodes)
    assert hidden_elements == frozenset({other.id for other in project.elements} - {element.id})
    assert window._act_show_all_objects.isEnabled()
    assert window._canvas.selection.elements == frozenset({element.id})

    menu = window._canvas_context_menu()
    texts = [action.text() for action in menu.actions()]
    assert window._act_isolate_selected.text() in texts
    assert window._act_show_all_objects.text() in texts
    menu.deleteLater()

    window._act_show_all_objects.trigger()
    assert window._canvas.hidden == (frozenset(), frozenset())
    assert not window._act_show_all_objects.isEnabled()


@pytest.mark.gui
def test_the_view_menu_lists_isolate_selected(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(qtbot)
    assert window._act_isolate_selected in window._menus["view"].actions()


@pytest.mark.gui
def test_box_selection_ignores_hidden_nodes_and_elements(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    window = _window(qtbot)
    project = window._vm.project
    canvas = window._canvas
    assert project is not None
    hidden_node = project.nodes[-1].id
    hidden_element = project.elements[-1].id
    canvas.set_hidden(nodes={hidden_node}, elements={hidden_element})
    canvas.selection.clear()

    def all_in_view(coords):  # type: ignore[no-untyped-def]
        return np.full((len(coords), 2), 300.0)

    monkeypatch.setattr(canvas, "_project_to_display", all_in_view)
    monkeypatch.setattr(canvas, "height", lambda: 600)
    monkeypatch.setattr(canvas, "devicePixelRatioF", lambda: 1.0)
    canvas._select_in_box(QRectF(0.0, 0.0, 500.0, 600.0), crossing=False)

    assert hidden_node not in canvas.selection.nodes
    assert hidden_element not in canvas.selection.elements
    assert canvas.selection.nodes == frozenset(
        node.id for node in project.nodes if node.id != hidden_node
    )
    assert canvas.selection.elements == frozenset(
        element.id for element in project.elements if element.id != hidden_element
    )
