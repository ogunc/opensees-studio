"""Global load entry by default, local as an option, and the local-axes view toggle."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.views.dialogs import (
    AssignDistributedLoadDialog,
    AssignPointElementLoadDialog,
    TrapezoidalLoadDialog,
)


def test_the_uniform_load_dialog_starts_global_and_can_switch_to_local(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = AssignDistributedLoadDialog(1, ndm=3)
    qtbot.addWidget(dialog)

    assert not dialog.is_local()
    assert dialog._labels["wx"].text() == "Fx:"
    assert dialog.values() == (0.0, 0.0, 0.0)

    dialog.set_local(True)
    assert dialog.is_local()
    assert dialog._labels["wx"].text() == "wx:"


def test_the_uniform_dialog_disables_the_out_of_plane_axis_in_2d(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = AssignDistributedLoadDialog(1, ndm=2)
    qtbot.addWidget(dialog)

    assert not dialog._spinboxes["wy"].isEnabled()  # global Y
    assert dialog._spinboxes["wz"].isEnabled()  # global Z

    dialog.set_local(True)
    assert dialog._spinboxes["wy"].isEnabled()  # local y is in-plane
    assert not dialog._spinboxes["wz"].isEnabled()  # local z is out of plane


def test_the_point_load_dialog_starts_global_and_returns_a_global_vector(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = AssignPointElementLoadDialog(1, ndm=3)
    qtbot.addWidget(dialog)
    dialog._fields["Py"].setValue(-3.0)

    assert not dialog.is_local()
    assert dialog.vector() == (0.0, -3.0, 0.0)

    dialog.set_local(True)
    assert dialog.is_local()


def test_the_trapezoidal_load_dialog_starts_global(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = TrapezoidalLoadDialog(1, 3)
    qtbot.addWidget(dialog)

    assert not dialog.is_local()
    assert dialog._labels["wx"].text() == "Fx:"
    dialog.set_local(True)
    assert dialog._labels["wx"].text() == "wx:"


def test_the_uniform_load_menu_converts_a_global_z_load_per_member(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QDialog

    from opensees_studio.commands import (
        AddElementsCommand,
        AddNodesCommand,
        AddSectionsCommand,
    )
    from opensees_studio.core import (
        ElasticBeamColumn,
        ElasticSection,
        Node,
        PlainLoadPattern,
        UniformElementLoad,
    )
    from opensees_studio.views.dialogs import AssignDistributedLoadDialog
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.new_project(ndm=3, ndf=6)
    window._vm.apply_command(
        AddNodesCommand(
            window._vm,
            [
                Node(id=1, coords=(0.0, 0.0, 0.0)),
                Node(id=2, coords=(1.0, 0.0, 0.0)),
                Node(id=3, coords=(0.0, 0.0, 0.0)),
                Node(id=4, coords=(0.0, 0.0, 1.0)),
            ],
        )
    )
    window._vm.apply_command(
        AddSectionsCommand(
            window._vm,
            [ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=2e-5)],
        )
    )
    window._vm.apply_command(
        AddElementsCommand(
            window._vm,
            [
                ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
                ElasticBeamColumn(id=2, nodes=(3, 4), section_id=1),
            ],
        )
    )
    window._canvas.selection.set_selection(set(), {1, 2})
    window._refresh_action_enablement()

    def _accept(dialog: AssignDistributedLoadDialog) -> int:
        dialog._spinboxes["wz"].setValue(-10.0)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(AssignDistributedLoadDialog, "exec", _accept)
    window._act_assign_distributed_load.trigger()

    loads = {
        load.element_id: load
        for pattern in window._vm.project.load_patterns
        if isinstance(pattern, PlainLoadPattern)
        for load in pattern.element_loads
    }
    assert loads[1] == UniformElementLoad(element_id=1, wz=-10.0)
    assert loads[2] == UniformElementLoad(element_id=2, wx=-10.0)


def test_view_local_axes_toggle_updates_the_viewport(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.new_project()
    # QSettings may carry a view/default from a previous app run; start from off.
    window._act_show_local_axes.setChecked(False)
    window._sync_visibility_actions()
    assert not window._canvas.view_settings.show_local_axes

    window._act_show_local_axes.trigger()

    assert window._canvas.view_settings.show_local_axes
    assert window._act_show_local_axes.isChecked()
