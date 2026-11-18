"""Right-click on a member while diagrams or a deformed shape are visible."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu

from opensees_studio.commands import AddElementsCommand, AddNodesCommand, AddSectionsCommand
from opensees_studio.core import (
    CombinationTerm,
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    LoadCombination,
    Node,
    PlainLoadPattern,
    StaticCase,
    UnitSystem,
)
from opensees_studio.services.results import CombinationResults, StaticResults


class _NoExecMenu(QMenu):
    """A menu that does not enter a modal event loop in the test."""

    def exec(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=3, ndf=6)
    mw._vm.apply_command(
        AddNodesCommand(
            mw._vm,
            [
                Node(id=1, coords=(0.0, 0.0, 0.0)),
                Node(id=2, coords=(3.0, 0.0, 0.0)),
            ],
        )
    )
    mw._vm.apply_command(
        AddSectionsCommand(
            mw._vm,
            [ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6)],
        )
    )
    mw._vm.apply_command(
        AddElementsCommand(
            mw._vm,
            [ElasticBeamColumn(id=10, nodes=(1, 2), section_id=1)],
        )
    )
    mw._vm.project.time_series.append(LinearTimeSeries(id=1))
    mw._vm.project.load_patterns.append(PlainLoadPattern(id=1, time_series_id=1))
    mw._vm.project.analyses.append(StaticCase(id=1, name="case", n_steps=1, pattern_ids=[1]))
    return mw


def _results(*, axial: float = 100.0, with_displacements: bool = True) -> StaticResults:
    forces = np.zeros((1, 12))
    forces[0, 0] = axial
    forces[0, 6] = -axial
    return StaticResults(
        case_id=1,
        case_name="case",
        n_steps=1,
        node_disp={1: np.zeros((1, 6)), 2: np.zeros((1, 6))} if with_displacements else {},
        element_forces={10: forces},
    )


def _install_menu_recorder(mw, monkeypatch):  # type: ignore[no-untyped-def]
    calls: list[bool] = []

    def menu() -> QMenu:
        calls.append(True)
        return _NoExecMenu()

    monkeypatch.setattr(mw, "_canvas_context_menu", menu)
    return calls


@pytest.mark.gui
def test_a_right_click_on_a_member_with_a_force_diagram_opens_its_window(
    qtbot, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._latest_results = _results()
    mw._on_show_force_diagram()
    assert mw._post_mode == "force"
    assert mw._diagram_renderer.is_drawn

    calls = _install_menu_recorder(mw, monkeypatch)
    monkeypatch.setattr(mw._canvas, "frame_element_at", lambda *args, **kwargs: 10)

    mw._on_canvas_context_menu(QPoint(20, 20))

    assert calls == []  # the menu did not open
    assert len(mw._element_diagram_windows) == 1
    window = mw._element_diagram_windows[0]
    assert window.bundle.element_id == 10
    assert "Element 10" in window._header.text()
    assert window._axial.plot.listDataItems()  # the axial curve is drawn
    assert len(window._panels) == 9  # 3 rows x 3 columns
    assert window._axial._max_labels  # the maximum is labelled
    window._distance.setValue(1.5)
    assert window._axial._query_line is not None
    assert "100" in window._axial.value.text()
    assert window._deformation._legend is not None
    assert len(window._deformation._legend.items) == 2  # absolute and relative


@pytest.mark.gui
def test_without_a_post_processing_view_the_menu_is_unchanged(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._latest_results = _results()
    calls = _install_menu_recorder(mw, monkeypatch)
    monkeypatch.setattr(mw._canvas, "frame_element_at", lambda *args, **kwargs: 10)

    mw._on_canvas_context_menu(QPoint(20, 20))

    assert calls == [True]
    assert mw._element_diagram_windows == []


@pytest.mark.gui
def test_an_empty_area_keeps_the_normal_menu(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._latest_results = _results()
    mw._on_show_force_diagram()
    calls = _install_menu_recorder(mw, monkeypatch)
    monkeypatch.setattr(mw._canvas, "frame_element_at", lambda *args, **kwargs: None)

    mw._on_canvas_context_menu(QPoint(20, 20))

    assert calls == [True]
    assert mw._element_diagram_windows == []


@pytest.mark.gui
def test_a_zero_diagram_does_not_hijack_the_right_click(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._latest_results = _results(axial=0.0)
    mw._on_show_force_diagram()
    assert not mw._diagram_renderer.is_drawn
    calls = _install_menu_recorder(mw, monkeypatch)
    monkeypatch.setattr(mw._canvas, "frame_element_at", lambda *args, **kwargs: 10)

    mw._on_canvas_context_menu(QPoint(20, 20))

    assert calls == [True]
    assert mw._element_diagram_windows == []


@pytest.mark.gui
def test_a_right_click_with_a_deformed_shape_opens_the_window(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._latest_results = _results()
    mw._on_show_deformed()
    assert mw._post_mode == "deformed"
    calls = _install_menu_recorder(mw, monkeypatch)
    monkeypatch.setattr(mw._canvas, "frame_element_at", lambda *args, **kwargs: 10)

    mw._on_canvas_context_menu(QPoint(20, 20))

    assert calls == []
    assert len(mw._element_diagram_windows) == 1


@pytest.mark.gui
def test_the_result_picker_switches_to_a_combination(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    results = _results()
    mw._latest_results = results
    mw._vm.project.combinations.append(
        LoadCombination(
            id=1,
            name="ULS",
            terms=[CombinationTerm(ref_id=1, factor=1.0)],
        )
    )
    mw._case_results.put(mw._vm.project, results)
    mw._on_show_force_diagram()
    mw._show_element_diagrams(10)

    window = mw._element_diagram_windows[0]
    assert window._results.count() == 2
    assert window._results.currentData() == "case:1"

    index = window._results.findData("combination:1")
    assert index >= 0
    window._results.setCurrentIndex(index)

    assert isinstance(mw._latest_results, CombinationResults)
    assert window.bundle.case_name.startswith("ULS")
    assert window._results.currentData() == "combination:1"


@pytest.mark.gui
def test_the_units_picker_rewrites_the_window(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._latest_results = _results()
    mw._on_show_force_diagram()
    mw._show_element_diagrams(10)

    window = mw._element_diagram_windows[0]
    assert mw._current_display_units() is UnitSystem.SI_M_N

    index = window._units.findData(UnitSystem.US_IN_KIP.value)
    assert index >= 0
    window._units.setCurrentIndex(index)

    assert mw._current_display_units() is UnitSystem.US_IN_KIP
    assert "kip" in window._axial.value.text()
    assert "in" in window._distance.suffix()


@pytest.mark.gui
def test_back_to_model_restores_the_plain_right_click(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._latest_results = _results()
    mw._on_show_force_diagram()
    mw._on_back_to_model()
    calls = _install_menu_recorder(mw, monkeypatch)
    monkeypatch.setattr(mw._canvas, "frame_element_at", lambda *args, **kwargs: 10)

    mw._on_canvas_context_menu(QPoint(20, 20))

    assert calls == [True]
    assert mw._element_diagram_windows == []
