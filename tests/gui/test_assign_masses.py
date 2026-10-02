"""Unit tests for AssignMassesDialog."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.views.dialogs.assign_masses import AssignMassesDialog


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
    dlg._mxx.setValue(0.0)
    dlg._myy.setValue(0.0)
    dlg._mzz.setValue(0.0)
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


@pytest.mark.gui
@pytest.mark.parametrize(
    "ndm,ndf,labels",
    [
        (2, 2, ["Ux:", "Uy:"]),
        (2, 3, ["Ux:", "Uy:", "Rz (Izz):"]),
        (3, 6, ["Ux:", "Uy:", "Uz:", "Rx (Ixx):", "Ry (Iyy):", "Rz (Izz):"]),
    ],
)
def test_active_mass_fields(qtbot, ndm, ndf, labels):
    from PySide6.QtWidgets import QFormLayout

    dlg = AssignMassesDialog(1, ndm=ndm, ndf=ndf)
    qtbot.addWidget(dlg)
    form = dlg.findChild(QFormLayout)
    assert [
        form.itemAt(i, QFormLayout.ItemRole.LabelRole).widget().text()
        for i in range(form.rowCount())
    ] == labels


@pytest.mark.gui
def test_planar_rz_mass_emits_third_component(qtbot):
    from unittest.mock import Mock

    from opensees_studio.core.geometry import Node
    from opensees_studio.core.project import Project
    from opensees_studio.services.opensees_runner import OpenSeesRunner

    dlg = AssignMassesDialog(1, ndm=2, ndf=3)
    qtbot.addWidget(dlg)
    dlg._mzz.lineEdit().setText("1e-10")
    dlg._mzz.interpretText()
    node = Node(id=1, coords=(0.0, 0.0, 0.0), mass=dlg.mass_vector())
    runner = OpenSeesRunner(Project(ndm=2, ndf=3))
    runner._ops = Mock()
    runner._emit_mass(node)
    runner._ops.mass.assert_called_once_with(1, 0.0, 0.0, 1e-10)
