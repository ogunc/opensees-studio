"""Design → Base Plate & Anchors and Bolted Connection: the calculators compute."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import Project


@pytest.mark.gui
def test_base_plate_dialog_checks_as_you_type(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.connection_calculators import BasePlateDialog

    dialog = BasePlateDialog(Project(ndm=3, ndf=6), {})
    qtbot.addWidget(dialog)
    dialog._pu.setValue(2.0e6)
    assert "Concrete bearing" in dialog._summary.text()
    dialog._pu.setValue(0.5e6)
    dialog._mu.setValue(0.2e6)
    assert "Anchor tension" in dialog._summary.text()
    assert dialog.governing_ratio() > 0.0


@pytest.mark.gui
def test_bolted_connection_dialog_reports_both(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.connection_calculators import BoltedConnectionDialog

    dialog = BoltedConnectionDialog(Project(ndm=3, ndf=6))
    qtbot.addWidget(dialog)
    text = dialog._summary.text()
    assert "Prying: Q =" in text and "most loaded bolt" in text
