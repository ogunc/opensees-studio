"""Ground Motions dialog, GM-2: spectrum plot, target spectrum, scaling."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import PathTimeSeries, gravity, response_spectrum

DT = 0.01
NPTS = 1500


def _values(seed: int, peak: float) -> np.ndarray:
    t = np.arange(NPTS) * DT
    rng = np.random.default_rng(seed)
    a = np.zeros_like(t)
    for f in np.linspace(0.5, 5.0, 12):
        a += rng.uniform(0.3, 1.0) * np.sin(2.0 * np.pi * f * t + rng.uniform(0, 2 * np.pi))
    a *= np.exp(-((t - 6.0) ** 2) / 12.0)
    return a * (peak / np.max(np.abs(a)))


def _write_at2(path, values: np.ndarray) -> None:  # type: ignore[no-untyped-def]
    lines = [
        "PEER NGA STRONG MOTION DATABASE RECORD",
        "Synthetic, station TEST, component 000",
        "ACCELERATION TIME SERIES IN UNITS OF G",
        f"{values.size}   {DT}   NPTS, DT",
    ]
    for i in range(0, values.size, 5):
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


def _import_two(dlg, tmp_path):  # type: ignore[no-untyped-def]
    first, second = tmp_path / "one.AT2", tmp_path / "two.AT2"
    _write_at2(first, _values(1, 0.25))
    _write_at2(second, _values(2, 0.40))
    assert dlg.import_file(str(first))
    assert dlg.import_file(str(second))


@pytest.mark.gui
def test_spectrum_plot_one_curve_per_selected_record_plus_target(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    mw, dlg = _open(qtbot)
    _import_two(dlg, tmp_path)
    # header says "IN UNITS OF G", so the imports know their units
    assert [r.accel_units for r in mw._vm.project.ground_motions] == ["g", "g"]

    dlg.select_records([1])
    assert dlg.spectrum_curve_count() == 1

    assert dlg.set_target_tbdy(sds=1.0, sd1=0.4)
    assert mw._vm.project.target_spectra[0].kind == "tbdy2018"
    dlg.select_records([1, 2])
    assert dlg.spectrum_curve_count() == 3  # two records + target

    log_periods, sa = dlg.spectrum_curve_data()[0]  # log axis: pyqtgraph hands back log10(T)
    assert len(log_periods) == len(sa) == 100
    assert np.all(np.isfinite(log_periods)) and log_periods[0] == pytest.approx(-2.0)  # no T = 0
    assert np.all(np.diff(log_periods) > 0)

    # the target is undoable and its overlay follows
    mw._vm.undo_stack.undo()
    assert mw._vm.project.target_spectra == []
    dlg.select_records([1, 2])
    assert dlg.spectrum_curve_count() == 2


@pytest.mark.gui
def test_apply_writes_series_factors_and_undo_restores(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    mw, dlg = _open(qtbot)
    _import_two(dlg, tmp_path)
    project = mw._vm.project
    g = gravity(project.meta.units)
    rec1, rec2 = project.ground_motions
    project.time_series.append(
        PathTimeSeries(id=1, dt=DT, values=list(_values(1, 0.25)), record_id=rec1.id, factor=g)
    )
    project.time_series.append(
        PathTimeSeries(id=2, dt=DT, values=list(_values(2, 0.40)), record_id=rec2.id, factor=g)
    )
    dlg._refresh()

    # (a) PGA scaling to 0.5 g: series factor = (0.5 / PGA) * g
    dlg.select_records([rec1.id, rec2.id])
    dlg._method.setCurrentIndex(0)
    dlg._target_pga.setValue(0.5)
    preview = dlg.preview_scaling()
    assert preview is not None
    assert preview.factors[rec1.id] == pytest.approx(0.5 / 0.25)
    assert preview.factors[rec2.id] == pytest.approx(0.5 / 0.40)
    assert dlg.apply_scaling()
    assert project.time_series[0].factor == pytest.approx(2.0 * g)
    assert project.time_series[1].factor == pytest.approx(1.25 * g)
    assert [r.accel_units for r in project.ground_motions] == ["g", "g"]  # records untouched

    mw._vm.undo_stack.undo()
    assert project.time_series[0].factor == pytest.approx(g)
    assert project.time_series[1].factor == pytest.approx(g)
    mw._vm.undo_stack.redo()
    assert project.time_series[0].factor == pytest.approx(2.0 * g)

    # (c) period-range scaling against a TBDY target, uniform factor
    assert dlg.set_target_tbdy(sds=1.0, sd1=0.4)
    dlg.select_records([rec1.id, rec2.id])
    dlg._method.setCurrentIndex(2)
    dlg._t1.setValue(0.8)
    preview = dlg.preview_scaling()
    assert preview is not None
    assert preview.factors[rec1.id] == pytest.approx(preview.factors[rec2.id])
    assert preview.min_ratio == pytest.approx(1.3, rel=1e-9)
    assert dlg._scaled_curve is not None
    assert dlg.apply_scaling()
    k = preview.factors[rec1.id]
    assert project.time_series[0].factor == pytest.approx(k * g)
    target = project.target_spectra[0]
    scaled = [
        response_spectrum(DT, k * _values(seed, peak), periods=preview.periods).sa
        for seed, peak in ((1, 0.25), (2, 0.40))
    ]
    ratio = np.mean(scaled, axis=0) / target.sa_at(preview.periods)
    assert float(np.min(ratio)) == pytest.approx(1.3, rel=1e-6)
    mw._vm.undo_stack.undo()
    assert project.time_series[0].factor == pytest.approx(2.0 * g)


@pytest.mark.gui
def test_unknown_units_record_shows_refusal(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    mw, dlg = _open(qtbot)
    _import_two(dlg, tmp_path)
    rec = mw._vm.project.ground_motions[0]

    dlg.select_records([rec.id])
    dlg.set_selected_units("unknown")  # undoable units command
    assert rec.accel_units == "unknown"
    assert dlg._table.item(0, 5).text() == "unknown"

    dlg.select_records([rec.id])
    assert dlg.spectrum_curve_count() == 0
    assert "unknown acceleration units" in dlg.status_text()

    dlg._method.setCurrentIndex(0)
    assert dlg.preview_scaling() is None
    assert f"Record '{rec.name}' has unknown acceleration units" in dlg.status_text()
    assert "Define > Ground Motions" in dlg.status_text()

    mw._vm.undo_stack.undo()
    assert rec.accel_units == "g"


@pytest.mark.gui
def test_user_table_target_and_sa_t1(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    mw, dlg = _open(qtbot)
    _import_two(dlg, tmp_path)
    table = tmp_path / "target.txt"
    table.write_text("# T  Sa[g]\n0.05 0.5\n0.5, 1.0\n2.0 0.25\n5.0 0.05\n")
    assert dlg.set_target_table(str(table))
    target = mw._vm.project.target_spectra[0]
    assert target.kind == "user" and target.sa_at(0.5)[0] == pytest.approx(1.0)

    rec = mw._vm.project.ground_motions[0]
    mw._vm.project.time_series.append(
        PathTimeSeries(id=1, dt=DT, values=list(_values(1, 0.25)), record_id=rec.id)
    )
    dlg._refresh()
    dlg.select_records([rec.id])
    dlg._method.setCurrentIndex(1)
    dlg._t1.setValue(0.5)
    preview = dlg.preview_scaling()
    assert preview is not None
    k = preview.factors[rec.id]
    sa = response_spectrum(DT, k * _values(1, 0.25), periods=[0.5]).sa[0]
    assert sa == pytest.approx(1.0, rel=1e-6)  # AT2 values carry 7 significant digits
    assert dlg.apply_scaling()
    assert mw._vm.project.time_series[0].factor == pytest.approx(
        k * gravity(mw._vm.project.meta.units)
    )
