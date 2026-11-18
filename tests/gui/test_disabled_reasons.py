"""A greyed-out command says what it waits for, and stops saying it once enabled."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.core.i18n import translate


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=3, ndf=6)
    yield mw
    mw._help_controller.uninstall()


@pytest.mark.gui
def test_every_reason_names_a_real_action_and_has_spanish(window) -> None:
    for reason, names in window._DISABLED_REASONS:
        assert translate(reason, "es") is not None, reason
        for name in names:
            assert hasattr(window, name), name


@pytest.mark.gui
def test_selection_commands_wait_for_a_selection_and_say_so(window) -> None:
    window._refresh_action_enablement()
    for name in ("_act_assign_section", "_act_assign_material", "_act_shell_formulation"):
        action = getattr(window, name)
        assert not action.isEnabled(), name
        assert action.toolTip() == "Select one or more elements first."
    assert not window._act_create_shell.isEnabled()
    assert not window._act_add_plain_pattern.isEnabled()
    assert window._act_show_deformed.statusTip().startswith("Run a Static analysis")


@pytest.mark.gui
def test_the_reason_goes_once_the_command_is_enabled(window) -> None:
    from opensees_studio.commands import AddNodesCommand
    from opensees_studio.core import Node

    window._vm.apply_command(AddNodesCommand(window._vm, [Node(id=1, coords=(0.0, 0.0, 0.0))]))
    window._canvas.selection.set_selection(nodes={1}, elements=set())
    window._refresh_action_enablement()
    assert window._act_assign_support.isEnabled()
    assert window._act_assign_support.statusTip() == ""
