"""Status-bar unit picker syncs with the project's display units."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import UnitSystem


@pytest.mark.gui
def test_status_bar_combo_lists_all_unit_systems(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    assert mw._units_combo.count() == len(list(UnitSystem))


@pytest.mark.gui
def test_status_bar_combo_reflects_the_model_system(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    mw._vm.project.meta.units = UnitSystem.US_IN_KIP
    mw._sync_units_combo()
    assert mw._units_combo.currentData() == UnitSystem.US_IN_KIP


@pytest.mark.gui
def test_status_bar_combo_reflects_the_display_system(qtbot) -> None:  # type: ignore[no-untyped-def]
    """A project shown in another system shows *that* system in the picker."""
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    mw._vm.project.meta.display_units = UnitSystem.US_FT_KIP
    mw._sync_units_combo()
    assert mw._units_combo.currentData() == UnitSystem.US_FT_KIP


@pytest.mark.gui
def test_status_bar_combo_write_updates_the_display_system(qtbot) -> None:  # type: ignore[no-untyped-def]
    """The combo sets what results are shown in; the model keeps its own units."""
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    # Default is SI_M_N — switch to US_IN_KIP via the combo.
    target_idx = mw._units_combo.findData(UnitSystem.US_IN_KIP)
    mw._units_combo.setCurrentIndex(target_idx)
    assert mw._vm.project.meta.display_units == UnitSystem.US_IN_KIP
    assert mw._vm.project.meta.units == UnitSystem.SI_M_N  # the typed values did not move
    assert mw._vm.is_dirty


@pytest.mark.gui
def test_status_bar_combo_no_project_noop(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Before a project is loaded, changing the combo is a no-op."""
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    # No crash even with no project.
    mw._units_combo.setCurrentIndex(2)
    assert mw._vm.project is None
