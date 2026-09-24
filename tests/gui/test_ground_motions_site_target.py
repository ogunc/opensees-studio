"""Ground Motions dialog, GM-2b: target from Ss, S1 and site class, vertical spectrum,
record-count warning in the Scale panel."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import PathTimeSeries
from tests.gui.test_ground_motions_scaling import DT, _open, _values, _write_at2

SS, S1 = 0.450, 0.117  # AFAD DD-2 reference case, ZC: SDS 0.585, SD1 0.1755


@pytest.mark.gui
def test_site_form_derives_reference_sds_sd1_and_sets_target(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    )
    mw, dlg = _open(qtbot)
    kind = dlg._target_kind
    kind.setCurrentIndex(kind.findData("tbdy2018_site"))
    assert dlg._ss.isEnabled() and not dlg._sds.isEnabled()
    dlg._ss.setValue(SS)
    dlg._s1.setValue(S1)
    dlg._site_class.setCurrentIndex(dlg._site_class.findData("ZC"))
    dlg._level.setCurrentIndex(dlg._level.findData("DD-2"))
    text = dlg.derived_text()
    assert "SDS = 0.5850 g" in text and "SD1 = 0.1755 g" in text
    assert "Fs = 1.3" in text and "F1 = 1.5" in text
    assert "TA = 0.0600 s" in text and "TB = 0.3000 s" in text

    dlg._set_target_btn.click()
    target = mw._vm.project.target_spectra[0]
    assert target.kind == "tbdy2018" and target.from_site
    assert target.sds == pytest.approx(0.585) and target.sd1 == pytest.approx(0.1755)
    assert (target.ss, target.s1, target.site_class, target.earthquake_level) == (
        SS,
        S1,
        "ZC",
        "DD-2",
    )
    assert "DD-2" in dlg.status_text()

    # ZF is refused with the core message, nothing replaces the target
    dlg._site_class.setCurrentIndex(dlg._site_class.findData("ZF"))
    assert "ZF" in dlg.derived_text()
    assert not dlg.set_target_tbdy_site(SS, S1, "ZF", "DD-2")
    assert "ZF" in dlg.status_text()
    assert mw._vm.project.target_spectra[0] == target

    # vertical option: derived line shows TAD, TBD and the target kind changes
    dlg._site_class.setCurrentIndex(dlg._site_class.findData("ZC"))
    dlg._vertical.setChecked(True)
    assert "TAD = 0.0200 s" in dlg.derived_text() and "TBD = 0.1000 s" in dlg.derived_text()
    dlg._set_target_btn.click()
    vertical = mw._vm.project.target_spectra[0]
    assert vertical.kind == "tbdy2018_vertical" and vertical.id == target.id
    assert vertical.sa_at(0.05)[0] == pytest.approx(0.8 * 0.585)
    mw._vm.undo_stack.undo()
    assert mw._vm.project.target_spectra[0].kind == "tbdy2018"

    # the direct form still works and the vertical flag applies to it too
    kind.setCurrentIndex(kind.findData("tbdy2018"))
    assert dlg._sds.isEnabled() and not dlg._ss.isEnabled()
    dlg._sds.setValue(1.0)
    dlg._sd1.setValue(0.4)
    assert "TAD = 0.0267 s" in dlg.derived_text()
    dlg._vertical.setChecked(False)
    assert "TA = 0.0800 s" in dlg.derived_text() and "TB = 0.4000 s" in dlg.derived_text()
    assert dlg.set_target_tbdy(1.0, 0.4)
    assert not mw._vm.project.target_spectra[0].from_site


@pytest.mark.gui
def test_period_range_with_three_records_shows_count_warning(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    mw, dlg = _open(qtbot)
    for i, peak in enumerate((0.25, 0.40, 0.30), start=1):
        path = tmp_path / f"rec{i}.AT2"
        _write_at2(path, _values(i, peak))
        assert dlg.import_file(str(path))
    project = mw._vm.project
    for rec in project.ground_motions:
        project.time_series.append(
            PathTimeSeries(id=rec.id, dt=DT, values=[0.0, 0.0], record_id=rec.id)
        )
    dlg._refresh()
    assert dlg.set_target_tbdy_site(SS, S1, "ZC", "DD-2")

    ids = [rec.id for rec in project.ground_motions]
    dlg.select_records(ids)
    dlg._method.setCurrentIndex(2)
    dlg._t1.setValue(0.8)
    preview = dlg.preview_scaling()
    assert preview is not None and len(preview.factors) == 3  # scaling still runs
    assert preview.warnings and "Only 3 records" in preview.warnings[0]
    assert "Only 3 records" in dlg.scale_warning_text() and "11 records" in dlg.scale_warning_text()
    assert dlg._scale_warning.isVisible()

    # PGA scaling has no record-count criterion: the warning goes away
    dlg._method.setCurrentIndex(0)
    dlg._target_pga.setValue(0.5)
    assert dlg.preview_scaling() is not None
    assert dlg.scale_warning_text() == ""

    # a paired selection of two records is one pair
    dlg.select_records(ids[:2])
    dlg._method.setCurrentIndex(2)
    dlg._pairs.setChecked(True)
    assert dlg.preview_scaling() is not None
    assert "Only 1 pair in the set" in dlg.scale_warning_text()


@pytest.mark.gui
def test_vertical_target_plot_stops_at_tld_and_scaling_refuses_beyond(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    mw, dlg = _open(qtbot)
    path = tmp_path / "rec1.AT2"
    _write_at2(path, _values(1, 0.3))
    assert dlg.import_file(str(path))
    project = mw._vm.project
    rec = project.ground_motions[0]
    project.time_series.append(
        PathTimeSeries(id=rec.id, dt=DT, values=[0.0, 0.0], record_id=rec.id)
    )
    dlg._refresh()
    assert dlg.set_target_tbdy(0.585, 0.1755, vertical=True)
    target = project.target_spectra[0]
    assert target.kind == "tbdy2018_vertical" and target.max_period == pytest.approx(3.0)

    # the target overlay is drawn only up to TLD = 3 s, with finite ordinates
    dlg.select_records([rec.id])
    log_periods, sa = dlg._target_curve.getData()  # the spectrum plot is in log-x mode
    periods = 10.0**log_periods
    assert periods.max() <= 3.0 + 1e-9 and np.all(np.isfinite(sa))
    assert periods.max() > 2.0  # the curve reaches close to TLD, not clipped early

    # period-range scaling: b T1 = 1.5 * 2.5 = 3.75 s exceeds TLD and is refused
    dlg._method.setCurrentIndex(2)
    dlg._t1.setValue(2.5)
    assert dlg.preview_scaling() is None
    assert "defined only up to TLD = 3 s" in dlg.status_text()
    # within the domain it runs
    dlg._t1.setValue(1.0)
    assert dlg.preview_scaling() is not None
