"""The influence-line case form, Display → Influence Line and its vehicle envelope."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")
pytest.importorskip("openseespy")

from opensees_studio.core import InfluenceLineCase
from opensees_studio.core.analysis import Axle
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.views.dialogs import InfluenceLineDialog
from opensees_studio.views.dialogs.case_forms import form_for


def _girder():  # type: ignore[no-untyped-def]
    from tests.integration.test_influence_line_run import PIN, ROLLER, _beam

    project = _beam({1: PIN, 3: ROLLER}, [0.0, 5.0, 10.0])
    case = InfluenceLineCase(
        id=1,
        name="Girder",
        path=[1, 2],
        stations=10,
        axles=[Axle(load=100.0), Axle(load=100.0, offset=2.0)],
    )
    project.analyses.append(case)
    return project, OpenSeesRunner(project).run(case)


@pytest.mark.gui
def test_the_case_form_round_trips(qtbot) -> None:  # type: ignore[no-untyped-def]
    case = InfluenceLineCase(
        id=3,
        name="Truck",
        path=[4, 5, 6],
        stations=8,
        direction="Z",
        load=-1.0,
        axles=[Axle(load=35.0), Axle(load=145.0, offset=4.3)],
    )
    form = form_for(case, [], [case])
    qtbot.addWidget(form)
    assert form._path.text() == "4, 5, 6"
    assert form._axles.text() == "35@0, 145@4.3"
    assert form.read() == case


@pytest.mark.gui
def test_the_dialog_plots_a_line_and_envelopes_the_vehicle(qtbot) -> None:  # type: ignore[no-untyped-def]
    project, results = _girder()
    dialog = InfluenceLineDialog(project, results)
    qtbot.addWidget(dialog)
    # Opens on the first member of the path, member forces, in-plane moment.
    assert dialog._component.currentText() == "M3"
    dialog._end.setCurrentText("j")
    line = dialog.line()
    assert line is not None
    assert np.abs(line).max() == pytest.approx(2.5)  # L/4 at midspan
    # The axles of the case are in the table; the midspan moment peaks at P(L-a)/2.
    assert [(a.load, a.offset) for a in dialog.axles()] == [(100.0, 0.0), (100.0, 2.0)]
    dialog._quantity.setCurrentIndex(1)  # reactions
    dialog._target.setValue(1)
    dialog._component.setCurrentText("Uz")
    found = dialog.envelope()
    assert found.maximum == pytest.approx(100.0 + 100.0 * 0.8)
    assert "maximum 180" in dialog._summary.text()


@pytest.mark.gui
def test_a_missing_member_is_reported(qtbot) -> None:  # type: ignore[no-untyped-def]
    project, results = _girder()
    dialog = InfluenceLineDialog(project, results)
    qtbot.addWidget(dialog)
    dialog._target.setValue(99)
    assert dialog.line() is None
    assert "Member 99 has no end forces" in dialog._summary.text()


@pytest.mark.gui
def test_the_display_action_follows_the_results(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    project, results = _girder()
    mw._vm.adopt(project)
    assert not mw._act_influence_line.isEnabled()
    mw._display_results(results)
    assert mw._act_influence_line.isEnabled()
    opened: list[object] = []
    monkeypatch.setattr(InfluenceLineDialog, "exec", lambda self: opened.append(self) or 0)
    mw._act_influence_line.trigger()
    assert opened
    assert "Influence line" in mw._results_panel._title.text()
