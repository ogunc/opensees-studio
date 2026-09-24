"""Ground Motions dialog: import, metadata, trace, relink, remove."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import GroundMotionRecord

# dt chosen so the 1 Hz sine peaks land exactly on the sample grid.
DT = 0.025
NPTS = 200
AMP = 0.35


def _sine_values() -> np.ndarray:
    t = np.arange(NPTS) * DT
    return AMP * np.sin(2.0 * np.pi * 1.0 * t)


def _write_at2(path) -> None:  # type: ignore[no-untyped-def]
    values = _sine_values()
    lines = [
        "PEER NGA STRONG MOTION DATABASE RECORD",
        "Synthetic sine, station TEST, component 000",
        "ACCELERATION TIME SERIES IN UNITS OF G",
        f"{NPTS}   {DT}   NPTS, DT",
    ]
    for i in range(0, NPTS, 5):
        lines.append("  ".join(f"{v: .7E}" for v in values[i : i + 5]))
    path.write_text("\n".join(lines) + "\n")


def _open(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    mw._act_ground_motions.trigger()
    dlg = mw._ground_motions_dlg
    assert dlg is not None
    qtbot.addWidget(dlg)
    return mw, dlg


@pytest.mark.gui
def test_action_opens_non_modal_dialog_and_reuses_it(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw, dlg = _open(qtbot)
    assert not dlg.isModal()
    mw._act_ground_motions.trigger()
    assert mw._ground_motions_dlg is dlg


@pytest.mark.gui
def test_import_synthetic_at2_shows_metadata(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    mw, dlg = _open(qtbot)
    at2 = tmp_path / "synthetic.AT2"
    _write_at2(at2)

    assert dlg.import_file(str(at2))

    project = mw._vm.project
    assert len(project.ground_motions) == 1
    rec = project.ground_motions[0]
    assert rec.format == "peer_at2"
    assert rec.npts == NPTS
    assert rec.dt == pytest.approx(DT)
    assert rec.status == "ok"
    assert len(rec.content_hash) == 64

    assert dlg._table.rowCount() == 1
    assert dlg._table.item(0, 0).text() == "synthetic"
    assert dlg._table.item(0, 2).text() == str(NPTS)
    assert float(dlg._table.item(0, 3).text()) == pytest.approx(AMP, rel=1e-3)  # PGA
    assert float(dlg._table.item(0, 4).text()) > 0.0  # D5-95
    assert dlg._table.item(0, 5).text() == "ok"

    # Import is undoable.
    mw._vm.undo_stack.undo()
    assert project.ground_motions == []
    assert dlg._table.rowCount() == 0


@pytest.mark.gui
def test_trace_plots_npts_points(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _mw, dlg = _open(qtbot)
    at2 = tmp_path / "synthetic.AT2"
    _write_at2(at2)
    dlg.import_file(str(at2))

    dlg._table.selectRow(0)
    data = dlg.curve_data()
    assert data is not None
    times, accel = data
    assert len(times) == NPTS
    assert len(accel) == NPTS
    assert max(abs(accel)) == pytest.approx(AMP, rel=1e-3)


@pytest.mark.gui
def test_relink_clears_missing_status(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    mw, dlg = _open(qtbot)
    values = _sine_values()
    replacement = tmp_path / "found-again.txt"
    replacement.write_text("\n".join(repr(float(v)) for v in values) + "\n")

    mw._vm.project.ground_motions.append(
        GroundMotionRecord(
            id=1,
            name="Lost",
            source_path="nowhere/gone.txt",
            format="single_column",
            dt=DT,
            npts=NPTS,
            status="missing",
        )
    )
    dlg._refresh()
    assert dlg._table.item(0, 5).text() == "missing"

    dlg._table.selectRow(0)
    assert dlg.relink_selected(str(replacement))

    rec = mw._vm.project.ground_motions[0]
    assert rec.status == "ok"
    assert rec.source_path.endswith("found-again.txt")
    assert rec.content_hash != ""
    assert dlg._table.item(0, 5).text() == "ok"


@pytest.mark.gui
def test_remove_updates_table_and_refuses_when_in_use(qtbot, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    from opensees_studio.core import PathTimeSeries

    # The refusal pops a modal warning; stub it out for the test.
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    )

    mw, dlg = _open(qtbot)
    first = tmp_path / "one.AT2"
    second = tmp_path / "two.AT2"
    _write_at2(first)
    _write_at2(second)
    dlg.import_file(str(first))
    dlg.import_file(str(second))
    assert dlg._table.rowCount() == 2

    dlg._table.selectRow(1)
    assert dlg.remove_selected()
    assert dlg._table.rowCount() == 1
    assert [r.id for r in mw._vm.project.ground_motions] == [1]

    # A record backing a time series cannot be removed.
    mw._vm.project.time_series.append(
        PathTimeSeries(id=1, dt=DT, values=list(_sine_values()), record_id=1)
    )
    dlg._refresh()
    dlg._table.selectRow(0)
    assert not dlg.remove_selected()
    assert len(mw._vm.project.ground_motions) == 1
