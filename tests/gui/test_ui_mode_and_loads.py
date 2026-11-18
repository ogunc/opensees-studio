"""Dark mode, the compact ribbon and the applied-loads panel."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QToolButton

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    UniformElementLoad,
)
from opensees_studio.core.load_queries import loads_on_element, loads_on_node
from opensees_studio.views.main_window import MainWindow
from opensees_studio.views.ribbon import build_ribbon_tabs
from opensees_studio.views.ribbon.widget import LABEL_LIMIT
from opensees_studio.views.theme import viewport_style


def _project() -> Project:
    return Project(
        nodes=[Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(6.0, 0.0, 0.0))],
        sections=[ElasticSection(id=1, E=200e9, A=5.7e-3, Iz=1.21e-4)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="DEAD",
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=1, forces=(0.0, 0.0, -5000.0, 0.0, 0.0, 0.0))],
                element_loads=[UniformElementLoad(element_id=1, wy=-3000.0)],
            )
        ],
    )


# ── dark mode ────────────────────────────────────────────────────
def test_dark_mode_swaps_the_palette_and_the_viewport(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    app = QApplication.instance()
    assert isinstance(app, QApplication)

    window._act_dark_mode.setChecked(True)

    assert window._dark_mode
    assert app.palette().color(QPalette.ColorRole.Window).lightness() < 128
    assert window._canvas._style.background_top == viewport_style(True).background_top

    window._act_dark_mode.setChecked(False)

    assert not window._dark_mode
    assert app.palette().color(QPalette.ColorRole.Window).lightness() > 128
    assert window._canvas._style.background_top == viewport_style(False).background_top


# ── compact ribbon ───────────────────────────────────────────────
def test_long_labels_are_icons_with_a_tooltip(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    bar = window._ribbon
    by_action = {b.defaultAction(): b for b in bar.findChildren(QToolButton) if b.defaultAction()}

    checked = 0
    for tab in build_ribbon_tabs(window.menuBar()):
        groups = list(tab.groups)
        for material in tab.materials:
            groups.extend(material.groups)
        for group in groups:
            for item in group.items + group.overflow:
                button = by_action.get(item.action)
                if button is None:
                    continue
                checked += 1
                label = item.action.text().replace("&", "").replace("…", "")
                assert button.toolTip(), f"{label!r} has no tooltip"
                if len(label) > LABEL_LIMIT:
                    assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly, (
                        f"{label!r} is longer than {LABEL_LIMIT} but still shows text"
                    )

    assert checked >= 80


def test_short_labels_keep_their_text(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    bar = window._ribbon
    by_action = {b.defaultAction(): b for b in bar.findChildren(QToolButton) if b.defaultAction()}

    for tab in build_ribbon_tabs(window.menuBar()):
        groups = list(tab.groups)
        for material in tab.materials:
            groups.extend(material.groups)
        for group in groups:
            for item in group.items:
                label = item.action.text().replace("&", "").replace("…", "")
                button = by_action.get(item.action)
                if button is None or len(label) > LABEL_LIMIT:
                    continue
                assert button.toolButtonStyle() != Qt.ToolButtonStyle.ToolButtonIconOnly


# ── applied loads ────────────────────────────────────────────────
def test_loads_on_a_node_and_a_member() -> None:
    project = _project()

    node_rows = loads_on_node(project, 1)
    assert len(node_rows) == 1
    assert node_rows[0].kind == "nodal"
    assert node_rows[0].pattern == "DEAD"
    assert node_rows[0].components[2] == -5000.0

    element_rows = loads_on_element(project, 1)
    assert len(element_rows) == 1
    assert element_rows[0].kind == "uniform"
    assert element_rows[0].components[1] == -3000.0


@pytest.mark.gui
def test_the_properties_panel_lists_the_loads(qtbot) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QGroupBox

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window._vm.adopt(_project())
    window._props.set_project(window._vm.project)
    window._canvas.selection.set_selection({1}, set())
    window._props.update_for_selection(frozenset({1}), frozenset())

    titles = [box.title() for box in window._props.findChildren(QGroupBox)]
    assert any("Cargas aplicadas" in title for title in titles)
