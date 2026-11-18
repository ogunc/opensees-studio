"""The viewport caption and Analyze → Delete All Results."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.services.results import StaticResults


def _results(name: str = "DEAD") -> StaticResults:
    return StaticResults(
        case_id=1,
        case_name=name,
        n_steps=1,
        node_disp={1: np.zeros((1, 6))},
        element_forces={1: np.zeros((1, 12))},
    )


def _window(qtbot, tmp_path):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.new_project()
    window._vm._path = tmp_path / "model.osmodel"
    return window


@pytest.mark.gui
def test_the_caption_names_the_results_on_screen(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    window = _window(qtbot, tmp_path)

    window._on_analysis_finished(_results("DEAD"))

    label = window._main_canvas._result_label
    assert label.isVisibleTo(window._main_canvas)
    assert "DEAD" in label.text()
    assert "Static" in label.text()


@pytest.mark.gui
def test_going_back_to_the_model_clears_the_caption(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    window = _window(qtbot, tmp_path)
    window._on_analysis_finished(_results())

    window._on_back_to_model()

    assert not window._main_canvas._result_label.isVisibleTo(window._main_canvas)


@pytest.mark.gui
def test_delete_all_results_clears_memory_and_the_file(qtbot, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    window = _window(qtbot, tmp_path)
    window._on_analysis_finished(_results())
    window._on_case_finished(_results())
    db = tmp_path / "model_results.sqlite"
    assert db.exists()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window._on_clear_results()

    assert not db.exists()
    assert window._latest_results is None
    assert not window._main_canvas._result_label.isVisibleTo(window._main_canvas)
    assert not window._act_clear_results.isEnabled()


@pytest.mark.gui
def test_delete_all_results_can_be_cancelled(qtbot, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    window = _window(qtbot, tmp_path)
    window._on_case_finished(_results())
    db = tmp_path / "model_results.sqlite"
    assert db.exists()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    window._on_clear_results()

    assert db.exists()
