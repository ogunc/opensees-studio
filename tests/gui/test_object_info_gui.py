"""Right-click → Object Information, and the viewport title of what is displayed."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    UniformElementLoad,
)
from opensees_studio.core.object_info import element_info
from opensees_studio.services.results import StaticResults
from opensees_studio.views.dialogs.object_info import ObjectInfoDialog
from opensees_studio.views.main_window import MainWindow

pytestmark = pytest.mark.gui


def _project() -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, False, True, False, False, False)),
            Node(id=2, coords=(6.0, 0.0, 0.0), restraint=(False, False, True, False, False, False)),
        ],
        sections=[ElasticSection(id=1, name="W14X30", E=200e9, A=5.7e-3, Iz=1.21e-4)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="DEAD",
                time_series_id=1,
                element_loads=[UniformElementLoad(element_id=1, wy=-10e3)],
            )
        ],
        analyses=[StaticCase(id=1, name="DEAD", pattern_ids=[1])],
    )


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    win = MainWindow()
    qtbot.addWidget(win)
    win._vm.adopt(_project())
    return win


def test_the_dialog_shows_the_three_tabs(qtbot) -> None:  # type: ignore[no-untyped-def]
    info = element_info(_project(), 1)
    assert info is not None
    dlg = ObjectInfoDialog(info)
    qtbot.addWidget(dlg)

    assert dlg.tab_titles() == ["Location", "Assignments", "Loads"]
    assert ("Section", "1: W14X30") in dlg.rows(1)
    assert dlg.rows(2) == [("DEAD", "Uniform, local: wy -10 kN/m")]
    assert dlg.windowTitle().endswith("ElasticBeamColumn 1")


def test_a_right_click_offers_the_object_under_the_pointer_first(window, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    canvas = window._main_canvas
    monkeypatch.setattr(type(canvas), "node_at", lambda self, x, y, tol=12.0: None)
    monkeypatch.setattr(type(canvas), "frame_element_at", lambda self, x, y, tol=18.0: 1)

    menu = window._context_menu_at(QPoint(10, 10), canvas)

    assert isinstance(menu, QMenu)
    assert menu.actions()[0].text() == "Object Information: Element 1…"
    assert menu.actions()[1].isSeparator()
    menu.deleteLater()
    dialog = window._show_object_info("element", 1)
    assert isinstance(dialog, ObjectInfoDialog)
    assert dialog.isVisible()
    dialog.close()


def test_with_nothing_under_the_pointer_the_one_selected_object_is_offered(
    window, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    canvas = window._main_canvas
    monkeypatch.setattr(type(canvas), "node_at", lambda self, x, y, tol=12.0: None)
    monkeypatch.setattr(type(canvas), "frame_element_at", lambda self, x, y, tol=18.0: None)

    assert window._object_at(QPoint(10, 10), canvas) is None
    canvas.selection.set_selection({2}, set())
    assert window._object_at(QPoint(10, 10), canvas) == ("node", 2)
    canvas.selection.set_selection({1, 2}, set())
    assert window._object_at(QPoint(10, 10), canvas) is None


def test_the_viewport_title_says_what_is_displayed(window) -> None:  # type: ignore[no-untyped-def]
    results = StaticResults(
        case_id=1,
        case_name="DEAD",
        n_steps=1,
        node_disp={1: np.zeros((1, 3)), 2: np.zeros((1, 3))},
        element_forces={1: np.zeros((1, 6))},
    )
    window._on_analysis_finished(results)
    label = window._main_canvas._result_label
    assert label.text().startswith("DEAD")

    window._set_display_title("Deformed Shape")
    assert label.text().startswith("Deformed Shape")
    assert "DEAD" in label.text()

    window._tear_down_post_dock()
    assert label.text().startswith("DEAD")
