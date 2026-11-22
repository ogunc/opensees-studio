"""Ground Motions dialog: RNC-07 and NSCM Managua target spectra and their case spectra."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from tests.gui.test_ground_motions_scaling import _open


@pytest.mark.gui
def test_rnc07_form_sets_target_and_case_spectrum(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    )
    mw, dlg = _open(qtbot)
    kind = dlg._target_kind
    kind.setCurrentIndex(kind.findData("rnc07"))
    assert dlg._a0.isEnabled() and not dlg._sds.isEnabled()
    assert not dlg._reduction.isEnabled()
    dlg._a0.setValue(0.3)
    dlg._nic_soil.setCurrentIndex(dlg._nic_soil.findData("II"))
    dlg._nic_class.setCurrentIndex(dlg._nic_class.findData("B"))
    text = dlg.derived_text()
    assert "zone C" in text and "S=1.5" in text and "peak 1.2150 g" in text

    dlg._set_target_btn.click()
    target = mw._vm.project.target_spectra[0]
    assert target.kind == "rnc07" and target.soil == "II" and target.reduction is None
    assert target.sa_at(0.3)[0] == pytest.approx(1.5 * 2.7 * 0.3)

    # the reduced spectrum: Q = 2, Ω = 2 on the plateau
    dlg._nic_reduced.setChecked(True)
    assert dlg._reduction.isEnabled() and dlg._nic_regularity.isEnabled()
    dlg._reduction.setValue(2.0)
    reduced = dlg.current_target()
    assert reduced is not None
    assert reduced.sa_at(0.3)[0] == pytest.approx(1.215 / 4.0)

    count = len(mw._vm.project.spectra)
    dlg._case_btn.click()
    spectra = mw._vm.project.spectra
    assert len(spectra) == count + 1
    assert max(spectra[-1].periods) == pytest.approx(10.0)


@pytest.mark.gui
def test_nscm_form_refuses_class_e_free_and_reads_managua(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    )
    mw, dlg = _open(qtbot)
    kind = dlg._target_kind
    kind.setCurrentIndex(kind.findData("nscm2021"))
    assert not dlg._nic_zone.isEnabled()
    assert dlg._nic_soil.findData("E") == -1  # class E needs a site study
    dlg._a0.setValue(0.36667)
    dlg._nic_soil.setCurrentIndex(dlg._nic_soil.findData("D"))
    dlg._nic_class.setCurrentIndex(dlg._nic_class.findData("II"))
    text = dlg.derived_text()
    assert "Z4" in text and "Fas=1.4" in text

    dlg._set_target_btn.click()
    target = mw._vm.project.target_spectra[0]
    assert target.kind == "nscm2021" and target.importance_class == "II"
    a0 = 0.36667 * 1.4
    assert target.sa_at(0.3)[0] == pytest.approx(2.4 * a0)
