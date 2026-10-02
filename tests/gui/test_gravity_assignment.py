"""Exercise the four-node campaign assignment path with Qt event processing."""

import cProfile
import pstats

import pytest
from examples.rc_frame_gravity import build_rc_frame_gravity

from opensees_studio.commands import (
    AddLoadPatternCommand,
    AddNodalLoadsCommand,
    AddTimeSeriesCommand,
)
from opensees_studio.core import LinearTimeSeries, PlainLoadPattern
from opensees_studio.views.main_window import MainWindow

pytestmark = pytest.mark.gui


def test_gravity_pattern_assignment_profile(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    project = build_rc_frame_gravity()
    assert len(project.nodes) == 4 and len(project.elements) == 3
    project.time_series.clear()
    project.load_patterns.clear()
    window._vm._project = project
    window._on_project_changed(project)
    window.show()
    profile = cProfile.Profile()
    profile.enable()
    window._vm.apply_command(AddTimeSeriesCommand(window._vm, LinearTimeSeries(id=1)))
    window._vm.apply_command(
        AddLoadPatternCommand(window._vm, PlainLoadPattern(id=1, time_series_id=1))
    )
    for _ in range(20):
        category = window._tree_categories["Nodes"]
        category.setExpanded(True)
        category.child(2).setSelected(True)
        category.child(3).setSelected(True)
        qtbot.wait(1)
        window._vm.apply_command(
            AddNodalLoadsCommand(window._vm, {3, 4}, (0, -180, 0, 0, 0, 0), pattern_id=1)
        )
        window._vm.undo_stack.undo()
    profile.disable()
    pstats.Stats(profile).strip_dirs().sort_stats("cumulative").print_stats(12)
    assert window._canvas.selection.nodes == frozenset({3, 4})
