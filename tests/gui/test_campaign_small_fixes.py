"""Run guidance, restored window bounds and clean-run recovery cleanup."""

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QLabel

from opensees_studio.services import save_project
from opensees_studio.views.dialogs.case_manager import AnalysisCaseManagerDialog
from opensees_studio.views.main_window import MainWindow
from tests.gui.test_run_snapshot_recovery import _cantilever

pytestmark = pytest.mark.gui


def test_case_manager_run_guidance(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.new_project()
    dialog = AnalysisCaseManagerDialog(window._vm)
    qtbot.addWidget(dialog)
    assert any("Analyze &gt; Run (F5)" in label.text() for label in dialog.findChildren(QLabel))


def test_main_window_geometry_fits_available_screen(qtbot, monkeypatch):
    from opensees_studio.views import screen_fit

    area = QRect(0, 0, 1280, 900)
    monkeypatch.setattr(screen_fit, "available_geometry", lambda widget: area)
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1900, 1100)
    window.move(2000, 1200)
    window.show()
    qtbot.wait(30)
    assert area.contains(window.frameGeometry())


@pytest.mark.parametrize("dirty", [False, True])
def test_successful_run_removes_only_clean_snapshot(qtbot, tmp_path, dirty):
    path = save_project(_cantilever(), tmp_path / "frame.osmodel")
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project(path)
    if dirty:
        window._vm.mark_dirty()
    with qtbot.waitSignal(window._runner.finished, timeout=10000):
        window._runner.run(
            window._vm.project,
            window._vm.project.analyses[0],
            results_dir=tmp_path / "results",
            project_path=path,
        )
    assert window._vm.run_snapshot_path.exists() == dirty
