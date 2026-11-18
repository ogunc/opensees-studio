"""Opening another project must not keep the previous project's results.

The canvas is re-rendered for the new model, but the result tabs, charts and
post-processing overlays lived outside that renderer and stayed behind.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.services.results import StaticResults
from opensees_studio.views.main_window import MainWindow

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.mark.gui
def test_opening_another_project_clears_the_previous_results(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.open_project(EXAMPLES / "cantilever.osmodel")
    project = window._vm.project
    assert project is not None
    results = StaticResults(case_id=1, case_name="old", n_steps=1)
    window._latest_results = results
    window._results_panel.show_results(results, project)
    window._set_result_caption("Old results")
    assert window._results_panel._tabs.count() > 0

    assert window.open_project(EXAMPLES / "space_frame_3d.osmodel")

    assert window._latest_results is None
    assert window._results_panel.tables() == []
    assert window._results_panel._tabs.count() == 0
    assert window._results_panel._title.text() == ""
    assert window._post_dock is None
