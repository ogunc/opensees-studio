"""Results panel: the digits setting changes the display only; Export CSV is full precision."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from opensees_studio.core import Node, Project
from opensees_studio.services.results import PushoverResults, StaticResults, TransientResults
from opensees_studio.views.docks.results_panel import DEFAULT_DIGITS, ResultsPanel

THIRD = 1.0 / 3.0


def _project() -> Project:
    return Project(ndm=2, ndf=3, nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(1, 0, 0))])


def _static() -> StaticResults:
    return StaticResults(
        case_id=1,
        case_name="gravity",
        n_steps=1,
        node_disp={1: np.array([[THIRD, 1e-10, -2.0322856141383964e-06]]), 2: np.zeros((1, 3))},
        node_reaction={1: np.array([[0.1 + 0.2, 0.0, 12345.678901234567]]), 2: np.zeros((1, 3))},
        element_forces={},
    )


def _panel(qtbot) -> ResultsPanel:  # type: ignore[no-untyped-def]
    panel = ResultsPanel()
    qtbot.addWidget(panel)
    return panel


def _cell(panel: ResultsPanel, row: int, column: int, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[no-untyped-def]
    model = panel.current_model()
    assert model is not None
    return model.data(model.index(row, column), role)


@pytest.mark.gui
def test_digits_change_the_display_only(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)
    panel.show_results(_static(), _project())
    assert panel.digits() == DEFAULT_DIGITS == 6
    header = panel.current_model().headerData(3, Qt.Orientation.Horizontal)
    assert header == "R3 [rad]"
    assert _cell(panel, 0, 1) == "0.333333"
    before = panel.export_current(tmp_path / "before.csv").read_bytes()

    panel.set_digits(3)
    assert _cell(panel, 0, 1) == "0.333"
    assert _cell(panel, 0, 3) == "-2.03e-06"
    panel.set_digits(15)
    assert _cell(panel, 0, 1) == "0.333333333333333"
    assert _cell(panel, 0, 1, Qt.ItemDataRole.UserRole) == THIRD
    after = panel.export_current(tmp_path / "after.csv").read_bytes()
    assert after == before
    assert b"0.3333333333333333" in after and b"1e-10" in after

    # a new result keeps the chosen setting
    panel.show_results(_static(), _project())
    assert _cell(panel, 0, 1) == "0.333333333333333"


@pytest.mark.gui
def test_export_button_writes_the_current_tab(qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import opensees_studio.views.docks.results_panel as mod

    target = tmp_path / "reactions.csv"
    monkeypatch.setattr(
        mod.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    panel = _panel(qtbot)
    panel.show_results(_static(), _project())
    panel._tabs.setCurrentIndex(1)
    assert panel._export.isEnabled()
    panel._export.click()
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "Node,F1 [N],F2 [N],M3 [N·m]"
    assert lines[1] == "1,0.30000000000000004,0.0,12345.678901234567"
    # the element forces tab of this result has no rows: nothing to export
    panel._tabs.setCurrentIndex(2)
    assert not panel._export.isEnabled()


@pytest.mark.gui
def test_pushover_result_gets_a_curve_table(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = _panel(qtbot)
    panel.show_results(
        PushoverResults(
            case_id=2,
            case_name="push",
            n_steps=1,
            control_node=2,
            control_dof=1,
            control_disp=np.array([0.0, 0.01]),
            base_shear=np.array([0.0, THIRD]),
            node_disp={1: np.zeros((2, 3)), 2: np.zeros((2, 3))},
        ),
        _project(),
    )
    assert [panel._tabs.tabText(i) for i in range(panel._tabs.count())] == [
        "Curve",
        "Displacements",
        "Element forces",
    ]
    assert panel.tables()[0].columns == ["Step", "Control U1 [m]", "Base shear [N]"]
    assert _cell(panel, 1, 2, Qt.ItemDataRole.UserRole) == THIRD


@pytest.mark.gui
def test_transient_node_history_table(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    import h5py

    h5 = tmp_path / "th.h5"
    time = np.array([0.01, 0.02, 0.03])
    disp = np.array([[THIRD, 0.0, 0.0], [1e-10, 0.0, 0.0], [0.0, 0.0, 0.5]])
    with h5py.File(h5, "w") as f:
        f.create_dataset("time", data=time)
        for nid in (1, 2):
            for kind in ("disp", "vel", "accel"):
                f.create_dataset(f"nodes/{nid}/{kind}", data=disp * nid)
    panel = _panel(qtbot)
    panel.show_results(
        TransientResults(
            case_id=3, case_name="th", h5_path=h5, n_steps=3, dt=0.01, n_steps_requested=3
        ),
        _project(),
    )
    panel._tabs.setCurrentIndex(1)
    table = panel.tables()[0]
    assert table.columns == ["Time [s]", "U1 [m]", "U2 [m]", "R3 [rad]"]
    assert [row[1] for row in table.rows] == [THIRD, 1e-10, 0.0]
    panel._history_node.setCurrentIndex(1)
    panel._history_kind.setCurrentIndex(2)
    table = panel.tables()[0]
    assert table.title == "Node 2 acceleration history"
    assert table.columns[1] == "A1 [m/s^2]"
    assert [row[1] for row in table.rows] == [2 * THIRD, 2e-10, 0.0]
