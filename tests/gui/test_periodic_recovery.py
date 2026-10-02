"""Recovery timer uses the existing atomic snapshot and restore path."""

import pytest

from opensees_studio.services import load_project, save_project
from opensees_studio.views.main_window import MainWindow
from tests.gui.test_run_snapshot_recovery import _cantilever

pytestmark = pytest.mark.gui


def test_periodic_snapshot_only_when_dirty_and_restores(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    path = save_project(_cantilever(), tmp_path / "frame.osmodel")
    window.open_project(path)
    assert window._recovery_timer.interval() == window._recovery_minutes * 60000
    window._recovery_timer.start(20)
    qtbot.wait(60)
    assert not window._vm.run_snapshot_path.exists()
    window._vm.project.meta.name = "Recovered"
    window._vm.mark_dirty()
    qtbot.waitUntil(window._vm.run_snapshot_path.exists)
    window._recovery_timer.stop()
    assert load_project(window._vm.run_snapshot_path).meta.name == "Recovered"
    assert "recovery snapshot written" in window._save_state.text()
    window._vm.restore_run_snapshot()
    assert window._vm.project.meta.name == "Recovered"
    assert window._vm.is_dirty
