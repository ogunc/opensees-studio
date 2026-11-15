"""Edit → Copy / Paste: the selection, pasted at an offset with its loads, then selected."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qtbot, monkeypatch):  # type: ignore[no-untyped-def]
    from opensees_studio.commands import AddElementLoadsCommand, AddElementsCommand, AddNodesCommand
    from opensees_studio.core import ElasticBeamColumn, Node
    from opensees_studio.views.dialogs import replicate
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=3, ndf=6)
    vm = mw._vm
    vm.apply_command(
        AddNodesCommand(
            vm,
            [
                Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
                Node(id=2, coords=(0.0, 0.0, 3.0)),
            ],
        )
    )
    tool_section = mw._vm.project.next_section_id()
    from opensees_studio.commands import AddSectionsCommand
    from opensees_studio.core import make_default_section

    vm.apply_command(AddSectionsCommand(vm, [make_default_section(tool_section)]))
    vm.apply_command(
        AddElementsCommand(vm, [ElasticBeamColumn(id=1, nodes=(1, 2), section_id=tool_section)])
    )
    vm.apply_command(AddElementLoadsCommand(vm, {1}, wz=-100.0))
    # Accept the Paste dialog with an offset of 5 along X.
    monkeypatch.setattr(replicate.PasteDialog, "exec", lambda self: 1)
    monkeypatch.setattr(replicate.PasteDialog, "offset", lambda self: (5.0, 0.0, 0.0))
    yield mw
    mw._help_controller.uninstall()


def test_paste_waits_for_a_copy(window) -> None:
    window._refresh_action_enablement()
    assert not window._act_paste.isEnabled()
    assert window._act_paste.toolTip() == "Copy a selection first (Edit → Copy)."


def test_copy_then_paste_places_a_loaded_copy_and_selects_it(window) -> None:
    project = window._vm.project
    window._canvas.selection.set_selection(set(), {1})  # the member alone
    window._act_copy.trigger()
    assert window._act_paste.isEnabled()
    window._act_paste.trigger()

    assert len(project.nodes) == 4 and len(project.elements) == 2
    new_nodes = {n.id: n for n in project.nodes if n.id not in (1, 2)}
    assert sorted(n.coords for n in new_nodes.values()) == [(5.0, 0.0, 0.0), (5.0, 0.0, 3.0)]
    assert any(n.restraint == (True,) * 6 for n in new_nodes.values())
    pattern = project.load_patterns[0]
    assert [load.element_id for load in pattern.element_loads] == [1, 2]
    assert window._canvas.selection.elements == frozenset({2})
    assert window._paste_offset == (5.0, 0.0, 0.0)

    window._vm.undo_stack.undo()  # one step
    assert len(project.nodes) == 2 and len(project.elements) == 1


def test_a_new_project_empties_the_clipboard(window) -> None:
    window._canvas.selection.set_selection({1, 2}, set())
    window._act_copy.trigger()
    window._vm.new_project(ndm=3, ndf=6)
    window._refresh_action_enablement()
    assert not window._act_paste.isEnabled()
