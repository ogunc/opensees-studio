"""Hardening in the material dialog and in the Material Tester."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from opensees_studio.core import Hardening, Project
from opensees_studio.viewmodels.material_tester_vm import MaterialTesterViewModel
from opensees_studio.views.dialogs.material_forms import FORM_REGISTRY, HardeningForm, form_for

H_KIN = 1526.3157894736842


@pytest.mark.gui
def test_form_builds_the_source_material_from_typed_text(qtbot) -> None:  # type: ignore[no-untyped-def]
    assert FORM_REGISTRY["Hardening"] is HardeningForm
    form = HardeningForm()
    qtbot.addWidget(form)
    for field, text in (
        (form._e, "29000"),
        (form._sigma_y, "36"),
        (form._h_iso, "0"),
        (form._h_kin, repr(H_KIN)),
    ):
        field.lineEdit().selectAll()
        qtbot.keyClicks(field, text)
        qtbot.keyClick(field, Qt.Key.Key_Return)
    mat = form.read(5)
    assert mat == Hardening(id=5, E=29000.0, sigmaY=36.0, H_iso=0.0, H_kin=H_KIN)


@pytest.mark.gui
def test_form_populates_an_existing_material(qtbot) -> None:  # type: ignore[no-untyped-def]
    mat = Hardening(id=2, name="A36", E=29000.0, sigmaY=36.0, H_iso=10.0, H_kin=H_KIN, eta=0.25)
    form = form_for(mat)
    qtbot.addWidget(form)
    assert form._h_kin.text() == "1526.3157894736842"
    assert form.read() == mat


def test_material_tester_offers_hardening() -> None:
    mat = Hardening(id=1, E=29000.0, sigmaY=36.0, H_iso=0.0, H_kin=H_KIN)
    vm = MaterialTesterViewModel(Project(ndm=2, ndf=2, materials=[mat]))
    assert vm.materials() == [mat] and vm.material_id == 1
