"""The Case combo lists the cases and switching one repoints the window."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.services.results import StaticResults
from opensees_studio.views.main_window import MainWindow


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    w = MainWindow()
    qtbot.addWidget(w)
    w._vm.new_project()
    return w


def _case(case_id: int, name: str) -> StaticResults:
    return StaticResults(case_id=case_id, case_name=name, n_steps=1)


@pytest.mark.gui
def test_showing_a_case_fills_the_combo(window) -> None:  # type: ignore[no-untyped-def]
    """The first bug here was `_display_results` never refreshing the list."""
    results = _case(1, "DEAD")
    window._case_results.put(window._vm.project, results)

    window._display_results(results)

    assert window._case_combo.count() == 1
    assert window._case_combo.itemText(0) == "DEAD · Static"
    assert window._case_combo.isEnabled()


@pytest.mark.gui
def test_choosing_another_case_repoints_the_window(window) -> None:  # type: ignore[no-untyped-def]
    first, second = _case(1, "DEAD"), _case(2, "EQX")
    window._case_results.put(window._vm.project, first)
    window._case_results.put(window._vm.project, second)
    window._display_results(first)
    assert window._latest_results is first

    index = window._case_combo.findData(2)
    window._case_combo.setCurrentIndex(index)

    assert window._latest_results is second


@pytest.mark.gui
def test_without_results_the_combo_is_empty_and_disabled(window) -> None:  # type: ignore[no-untyped-def]
    window._refresh_case_combo()

    assert window._case_combo.count() == 0
    assert not window._case_combo.isEnabled()
