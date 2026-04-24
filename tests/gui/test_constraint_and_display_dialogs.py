"""GUI tests for equalDOF and display-option dialogs."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.views.dialogs.assign_equal_dof import AssignEqualDOFDialog  # noqa: E402
from opensees_studio.views.dialogs.display_options import DisplayOptionsDialog  # noqa: E402


@pytest.mark.gui
def test_assign_equal_dof_dialog_defaults_to_shear_frame_dofs(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = AssignEqualDOFDialog([3, 4], ndf=3)
    qtbot.addWidget(dlg)

    c = dlg.constraint()
    assert c.retained_node == 3
    assert c.constrained_node == 4
    assert c.dofs == (2, 3)


@pytest.mark.gui
def test_display_options_dialog_round_trip(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = DisplayOptionsDialog(
        show_node_labels=False,
        show_element_labels=True,
    )
    qtbot.addWidget(dlg)

    dlg._show_node_labels.setChecked(True)
    dlg._show_element_labels.setChecked(False)
    assert dlg.values() == (True, False)
