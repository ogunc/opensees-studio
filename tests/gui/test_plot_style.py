"""Every pyqtgraph plot shows real axis values in a readable font.

No automatic SI prefix (the "x0.001" multiplier that made 0.4 g read as
400), and tick and axis-label fonts at least the application font size.
"""

from __future__ import annotations

import re

import numpy as np
import pytest

pytest.importorskip("PySide6")

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication, QWidget

from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs.generate_excitation import GenerateExcitationDialog
from opensees_studio.views.dialogs.ground_motions import GroundMotionsDialog
from opensees_studio.views.dialogs.material_tester import MaterialTesterDialog
from opensees_studio.views.dialogs.section_editor import FiberSectionEditor
from opensees_studio.views.docks.hysteresis import HysteresisView
from opensees_studio.views.docks.pushover_curve import PushoverCurveView
from opensees_studio.views.docks.response_spectrum import ResponseSpectrumView
from opensees_studio.views.docks.time_history import TimeHistoryView

AXES = ("left", "bottom", "right", "top")


def _owners(qtbot) -> dict[str, QWidget]:  # type: ignore[no-untyped-def]
    vm = ProjectViewModel()
    vm.new_project()
    gm = GroundMotionsDialog(vm)
    owners = {
        "Ground Motions": gm,
        "Generate excitation": GenerateExcitationDialog(gm.view_model),
        "Material Tester": MaterialTesterDialog(vm),
        "Fiber Section Editor": FiberSectionEditor([1]),
        "Time-History Plot": TimeHistoryView(),
        "Hysteresis": HysteresisView(),
        "Pushover curve": PushoverCurveView(),
        "Response spectrum": ResponseSpectrumView(),
    }
    for widget in owners.values():
        qtbot.addWidget(widget)
    owners["Ground Motions"]._vm_ref = vm
    return owners


def _points(css_size: str) -> float:
    match = re.fullmatch(r"([\d.]+)pt", css_size)
    assert match, css_size
    return float(match.group(1))


@pytest.mark.gui
def test_every_plot_axis_has_no_si_prefix_and_a_readable_font(qtbot) -> None:  # type: ignore[no-untyped-def]
    app_points = QApplication.font().pointSizeF()
    plots_seen = 0
    for owner_name, owner in _owners(qtbot).items():
        plots = owner.findChildren(pg.PlotWidget)
        assert plots, f"{owner_name}: no plot found"
        for plot in plots:
            plots_seen += 1
            for name in AXES:
                axis = plot.getAxis(name)
                where = f"{owner_name} {name} axis"
                assert axis.autoSIPrefix is False, where
                assert axis.style["tickFont"] is not None, where
                assert axis.style["tickFont"].pointSizeF() >= app_points, where
                assert _points(axis.labelStyle["font-size"]) >= app_points, where
    assert plots_seen >= 10


@pytest.mark.gui
def test_small_values_are_shown_as_they_are(qtbot) -> None:  # type: ignore[no-untyped-def]
    """A 0.4 g spectrum plateau is labelled 0.4 on the axis, never 400 with x0.001."""
    view = TimeHistoryView()
    qtbot.addWidget(view)
    plot = view._plot
    plot.plot(np.linspace(0.0, 1.0, 50), 0.0004 * np.sin(np.linspace(0.0, 6.0, 50)))
    view.show()
    qtbot.waitExposed(view)
    left = plot.getAxis("left")
    assert left.autoSIPrefixScale == 1.0
    assert "x0.001" not in left.labelString() and "(m" not in left.labelString()
    ticks = left.tickValues(-0.0004, 0.0004, 200)
    labels = [s for spacing, values in ticks for s in left.tickStrings(values, 1.0, spacing)]
    assert any("0.0004" in s or "4e-04" in s or "0.0002" in s for s in labels), labels
