"""Unit tests for AssignMassesDialog."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.views.dialogs.assign_masses import AssignMassesDialog  # noqa: E402


@pytest.mark.gui
def test_mass_vector_default_is_zero(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = AssignMassesDialog(n_selected=3, ndf=6)
    qtbot.addWidget(dlg)
    assert dlg.mass_vector() == (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


@pytest.mark.gui
def test_mass_vector_reads_spinboxes(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = AssignMassesDialog(n_selected=1, ndf=6)
    qtbot.addWidget(dlg)
    dlg._mx.setValue(5000.0)
    dlg._my.setValue(5000.0)
    dlg._mz.setValue(100.0)
    dlg._mxx.setValue(0.0); dlg._myy.setValue(0.0); dlg._mzz.setValue(0.0)
    assert dlg.mass_vector() == (5000.0, 5000.0, 100.0, 0.0, 0.0, 0.0)


@pytest.mark.gui
def test_xy_link_ties_y_to_x(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Toggling the lumped-mass checkbox should mirror Mx → My live."""
    dlg = AssignMassesDialog(n_selected=1, ndf=6)
    qtbot.addWidget(dlg)
    dlg._xy_link.setChecked(True)
    dlg._mx.setValue(4200.0)
    assert dlg._my.value() == pytest.approx(4200.0)
    dlg._xy_link.setChecked(False)
    dlg._mx.setValue(9999.0)
    # After unlink, Y stays where it was.
    assert dlg._my.value() == pytest.approx(4200.0)


@pytest.mark.gui
def test_ndf_3_hides_rotational_fields(qtbot) -> None:  # type: ignore[no-untyped-def]
    """For ndf=3 models there are no rotational DOFs on a joint."""
    dlg = AssignMassesDialog(n_selected=1, ndf=3)
    qtbot.addWidget(dlg)
    # The rotational spinboxes exist but aren't in the form layout.
    # We can still read them; they default to 0.
    vec = dlg.mass_vector()
    assert vec[3:] == (0.0, 0.0, 0.0)
