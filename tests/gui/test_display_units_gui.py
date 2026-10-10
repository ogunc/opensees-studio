"""Changing the display units updates the numbers already on screen.

The model keeps its own unit system; every open view — results tables, force
diagram and deformed shape — is re-rendered in the new system without a re-run.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import Qt

from opensees_studio.commands import AddElementsCommand, AddNodesCommand, AddSectionsCommand
from opensees_studio.core import ElasticBeamColumn, ElasticSection, Node, UnitSystem
from opensees_studio.services.results import StaticResults

# Exact definitions, so the expectations do not copy the implementation:
# 1 in = 25.4 mm and 1 kip = 4448.2216152605 N.
IN_M = 0.0254
KIP_N = 4448.2216152605

# A 3 m cantilever tip pushed 6 mm down, carrying 10 kN·m at the root.
# 2D localForce: N, V, M at each end.
BEAM_FORCES = np.array([[0.0, 0.0, 10000.0, 0.0, 0.0, -10000.0]])


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=2, ndf=3)
    mw._vm.apply_command(
        AddNodesCommand(
            mw._vm,
            [Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(3.0, 0.0, 0.0))],
        )
    )
    mw._vm.apply_command(
        AddSectionsCommand(mw._vm, [ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5)]),
    )
    mw._vm.apply_command(
        AddElementsCommand(mw._vm, [ElasticBeamColumn(id=10, nodes=(1, 2), section_id=1)]),
    )
    mw._on_analysis_finished(_results())
    return mw


def _results() -> StaticResults:
    return StaticResults(
        case_id=1,
        case_name="tip load",
        n_steps=1,
        node_disp={1: np.zeros((1, 3)), 2: np.array([[0.006, -0.008, 0.0]])},
        node_reaction={1: np.array([[0.0, 1000.0, 10000.0]])},
        element_forces={10: BEAM_FORCES},
    )


def _cell(mw, row: int, column: int):  # type: ignore[no-untyped-def]
    """The displayed text of a cell."""
    model = mw._results_panel.current_model()
    assert model is not None
    return model.data(model.index(row, column), Qt.ItemDataRole.DisplayRole)


def _raw(mw, row: int, column: int) -> float:  # type: ignore[no-untyped-def]
    """The full-precision value behind a cell (the display rounds to 6 digits)."""
    model = mw._results_panel.current_model()
    assert model is not None
    return float(model.data(model.index(row, column), Qt.ItemDataRole.UserRole))


def _header(mw, column: int):  # type: ignore[no-untyped-def]
    model = mw._results_panel.current_model()
    assert model is not None
    return model.headerData(column, Qt.Orientation.Horizontal)


@pytest.mark.gui
def test_the_project_starts_showing_its_own_system(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    assert mw._vm.project.meta.units is UnitSystem.SI_M_N
    assert mw._vm.project.meta.display_units is None
    assert _header(mw, 1) == "U1 [m]"
    assert _cell(mw, 1, 1) == "0.006"


@pytest.mark.gui
def test_switching_the_display_system_converts_the_open_tables(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    shown_tab = mw._results_panel._tabs.currentIndex()

    mw._set_display_units(UnitSystem.US_IN_KIP)

    # Headers and values moved together, without re-running anything.
    assert _header(mw, 1) == "U1 [in]"
    assert _raw(mw, 1, 1) == pytest.approx(0.006 / IN_M)
    assert mw._results_panel._tabs.currentIndex() == shown_tab
    # The model did not move: OpenSees still has the numbers that were typed.
    assert mw._vm.project.meta.units is UnitSystem.SI_M_N
    assert mw._vm.project.meta.display_units is UnitSystem.US_IN_KIP

    # And back again.
    mw._set_display_units(UnitSystem.SI_M_N)
    assert _header(mw, 1) == "U1 [m]"
    assert _cell(mw, 1, 1) == "0.006"


@pytest.mark.gui
def test_the_status_bar_picker_follows_and_drives_the_display_system(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    assert mw._current_display_units() is UnitSystem.SI_M_N

    index = mw._units_combo.findData(UnitSystem.US_FT_KIP)
    assert index >= 0
    mw._units_combo.setCurrentIndex(index)  # fires currentIndexChanged

    assert mw._vm.project.meta.display_units is UnitSystem.US_FT_KIP
    assert mw._current_display_units() is UnitSystem.US_FT_KIP
    assert _header(mw, 1) == "U1 [ft]"  # the displacements tab is the open one
    mw._results_panel._tabs.setCurrentIndex(1)  # Reactions
    assert _header(mw, 1) == "F1 [kip]"
    assert _header(mw, 3) == "M3 [kip·ft]"
    assert mw._vm.project.meta.units is UnitSystem.SI_M_N  # the model is untouched


@pytest.mark.gui
def test_a_display_change_does_not_mark_the_project_as_reinterpreted(qtbot) -> None:  # type: ignore[no-untyped-def]
    """The conversion is a view setting: no node, element or load value changes."""
    mw = _window(qtbot)
    before = mw._vm.project.model_dump_json(exclude={"meta"})
    mw._set_display_units(UnitSystem.US_IN_KIP)
    assert mw._vm.project.model_dump_json(exclude={"meta"}) == before


@pytest.mark.gui
def test_the_deformed_shape_reports_the_peak_displacement_in_display_units(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._on_show_deformed()
    view = mw._post_dock.widget()
    # 6 mm across, 8 mm down → a 10 mm magnitude, not 8 and not 6.
    assert view._peak_label.text() == "0.01 m"

    mw._set_display_units(UnitSystem.SI_MM_N)
    assert view._peak_label.text() == "10 mm"

    mw._set_display_units(UnitSystem.US_IN_KIP)
    assert view._peak_label.text() == pytest.approx(f"{0.01 / IN_M:.4g} in")


@pytest.mark.gui
def test_the_force_diagram_is_redrawn_in_the_new_units(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._on_show_force_diagram()
    view = mw._post_dock.widget()
    assert view.current_component().is_moment  # the 10 kN·m root dominates
    assert "N·m" in view._units_label.text()

    mw._set_display_units(UnitSystem.US_IN_KIP)

    assert "kip·in" in view._units_label.text()
    # The overlay was re-rendered, in the new units: colour bar values and the
    # end labels both come back, and the ribbon data moved to display units.
    assert mw._diagram_renderer._actor is not None
    assert mw._diagram_renderer._label_actor is not None
    cells = mw._diagram_renderer._actor.GetMapper().GetInput().GetCellData()
    converted = np.asarray(cells.GetArray("value"))
    assert converted.size > 0
    assert np.all(np.abs(converted) < 10000.0)  # 10 kN·m is ~88.5 kip·in, not 10000


@pytest.mark.gui
def test_a_solved_model_shows_converted_element_forces(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._results_panel._tabs.setCurrentIndex(2)  # Element forces
    assert _cell(mw, 2, 2) == "M i"
    assert _raw(mw, 2, 4) == pytest.approx(10000.0)  # M i, N·m

    mw._set_display_units(UnitSystem.US_IN_KIP)

    assert _cell(mw, 2, 3) == "kip·in"
    assert _raw(mw, 2, 4) == pytest.approx(10000.0 / KIP_N / IN_M)
