"""Options → Autosave Recovery Copy: unsaved changes copied for recovery, the file untouched."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OPENSEES_STUDIO_DATA_DIR", str(tmp_path / "data"))
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    yield mw
    mw._autosave_timer.stop()
    mw._help_controller.uninstall()


def _add_node(window) -> None:
    from opensees_studio.commands import AddNodesCommand
    from opensees_studio.core import Node

    vm = window._vm
    vm.apply_command(AddNodesCommand(vm, [Node(id=vm.project.next_node_id(), coords=(1, 2, 3))]))


def test_the_default_is_every_five_minutes_and_the_choice_is_kept(window, qtbot) -> None:
    from PySide6.QtCore import QSettings

    assert window._autosave_actions[5].isChecked()
    assert window._autosave_timer.interval() == 5 * 60_000
    window._autosave_actions[0].trigger()
    assert not window._autosave_timer.isActive()
    assert QSettings().value("autosave/minutes") in (0, "0")
    window._autosave_actions[5].trigger()  # back to the default for the other tests
    assert window._autosave_timer.isActive()


def test_a_saved_project_gets_its_copy_beside_it_and_save_removes_it(window, tmp_path) -> None:
    from opensees_studio.services import run_snapshot_path

    window._vm.new_project()
    path = tmp_path / "frame.osmodel"
    window._vm.save(path)
    before = path.read_bytes()
    window._autosave()  # nothing unsaved: nothing written
    assert not run_snapshot_path(path).exists()

    _add_node(window)
    window._autosave()
    assert run_snapshot_path(path).is_file()
    assert path.read_bytes() == before  # the project file is never touched
    window._vm.save(path)
    assert not run_snapshot_path(path).exists()


def test_a_never_saved_project_is_offered_on_the_start_page(window, qtbot) -> None:
    from opensees_studio.services import run_snapshot_path

    window._vm.new_project()
    _add_node(window)
    window._autosave()
    snapshot = run_snapshot_path(None)
    assert snapshot.is_file()

    from opensees_studio.views.main_window import MainWindow

    again = MainWindow()
    qtbot.addWidget(again)
    try:
        button = again._start_page._recover
        assert not button.isHidden() and "Recover the unsaved project" in button.text()
        button.click()
        assert again._vm.project is not None
        assert len(again._vm.project.nodes) == 1
        assert again._vm.is_dirty and again._vm.path is None
    finally:
        again._autosave_timer.stop()
        again._help_controller.uninstall()
