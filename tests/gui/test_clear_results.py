"""A new or opened project must not inherit the previous result views."""

import pytest

from opensees_studio.services import save_project
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.views.main_window import MainWindow
from tests.gui.test_run_snapshot_recovery import _cantilever

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("replacement", ["new", "open"])
def test_project_change_clears_solved_results(qtbot, tmp_path, replacement):
    window = MainWindow()
    qtbot.addWidget(window)
    project = _cantilever()
    path = save_project(project, tmp_path / "frame.osmodel")
    window.open_project(path)
    result = OpenSeesRunner(project).run(project.analyses[0])
    window._on_analysis_finished(result)
    window._on_show_deformed()
    assert window._results_panel._export.isEnabled()
    if replacement == "new":
        window._on_new()
    else:
        window.open_project(path)
    assert window._latest_results is None
    assert window._results_panel._tabs.count() == 0
    assert not window._results_panel._export.isEnabled()
    assert not window._act_export_th_animation.isEnabled()
    assert window._post_dock is None
