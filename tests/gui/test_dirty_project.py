"""All existing GUI replacement paths share the unsaved-change gate."""

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from opensees_studio.core import Project
from opensees_studio.services import save_project
from opensees_studio.views.main_window import MainWindow

pytestmark = pytest.mark.gui


def test_discard_removes_previous_recovery_snapshot(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    path = save_project(Project(), tmp_path / "previous.osmodel")
    window.open_project(path)
    window._vm.mark_dirty()
    snapshot = window._vm.write_run_snapshot()
    monkeypatch.setattr(window, "_ask_save_changes", lambda: QMessageBox.StandardButton.Discard)
    window._on_new()
    assert not snapshot.exists()


@pytest.mark.parametrize(
    "entry", ["_on_new", "_on_new_2d", "_on_new_2d_truss", "_on_open", "open_project", "close"]
)
@pytest.mark.parametrize("dirty", [False, True])
def test_replacement_prompt_and_cancel(qtbot, tmp_path, monkeypatch, entry, dirty):
    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.new_project()
    project = window._vm.project
    path = save_project(Project(), tmp_path / "other.osmodel")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(path), ""))
    calls = []
    monkeypatch.setattr(
        window, "_ask_save_changes", lambda: calls.append(True) or QMessageBox.StandardButton.Cancel
    )
    if dirty:
        window._vm.mark_dirty()
    if entry == "open_project":
        window.open_project(path)
    else:
        getattr(window, entry)()
    assert bool(calls) == dirty
    if dirty:
        assert window._vm.project is project
        assert window._vm.is_dirty
    window._vm._set_dirty(False)


@pytest.mark.parametrize("choice", ["Save", "Discard"])
def test_save_or_discard_before_new(qtbot, tmp_path, monkeypatch, choice):
    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.new_project()
    window._vm.project.meta.name = "Unsaved"
    window._vm.mark_dirty()
    path = tmp_path / "saved.osmodel"
    monkeypatch.setattr(
        window, "_ask_save_changes", lambda: getattr(QMessageBox.StandardButton, choice)
    )
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(path), ""))
    window._on_new()
    assert not window._vm.is_dirty
    assert path.exists() == (choice == "Save")


def test_cancel_save_as_keeps_dirty_project(qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.new_project()
    project = window._vm.project
    window._vm.mark_dirty()
    monkeypatch.setattr(window, "_ask_save_changes", lambda: QMessageBox.StandardButton.Save)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: ("", ""))
    window._on_new()
    assert window._vm.project is project
    assert window._vm.is_dirty
    window._vm._set_dirty(False)
