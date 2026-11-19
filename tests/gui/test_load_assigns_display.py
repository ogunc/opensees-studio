"""Display → Show Load Assigns: the dialog and what it does to the viewport."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QDialog

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    PointElementLoad,
    Project,
    UniformElementLoad,
)
from opensees_studio.core.view_settings import ViewSettings
from opensees_studio.services import save_project
from opensees_studio.views.dialogs.load_display import ALL_PATTERNS, LoadDisplayDialog
from opensees_studio.views.main_window import MainWindow

pytestmark = pytest.mark.gui


def _project() -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, False, True, False, False, False)),
            Node(id=2, coords=(6.0, 0.0, 0.0), restraint=(False, False, True, False, False, False)),
        ],
        sections=[ElasticSection(id=1, E=200e9, A=5.7e-3, Iz=1.21e-4)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="DEAD",
                time_series_id=1,
                element_loads=[UniformElementLoad(element_id=1, wy=-10e3)],
            ),
            PlainLoadPattern(
                id=2,
                name="LIVE",
                time_series_id=1,
                point_loads=[PointElementLoad(element_id=1, py=-50e3, x=0.5)],
            ),
        ],
    )


def test_the_dialog_lists_the_patterns_and_returns_the_choice(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = LoadDisplayDialog(_project().load_patterns, ViewSettings())
    qtbot.addWidget(dlg)
    assert [dlg._pattern.itemText(i) for i in range(dlg._pattern.count())] == [
        ALL_PATTERNS,
        "DEAD",
        "LIVE",
    ]
    assert dlg.changes()["load_pattern_id"] is None

    dlg.set_pattern(2)
    dlg.set_kind("shell", False)
    dlg.set_show_values(True)
    changes = dlg.changes()
    assert changes["load_pattern_id"] == 2
    assert changes["show_shell_loads"] is False
    assert changes["show_load_values"] is True
    assert changes["show_loads"] is True


def test_the_menu_applies_the_choice_to_the_viewport(qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    path = save_project(_project(), tmp_path / "beam.osmodel")
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.open_project(path)
    window._apply_view_settings(show_loads=False)
    assert window._act_show_load_assigns.isEnabled()

    def _accept(dialog: LoadDisplayDialog) -> int:
        dialog.set_pattern(2)
        dialog.set_kind("frame_distributed", False)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(LoadDisplayDialog, "exec", _accept)
    window._act_show_load_assigns.trigger()

    settings = window._canvas.view_settings
    assert settings.load_pattern_id == 2
    assert settings.show_frame_distributed_loads is False
    assert settings.show_loads is True
    assert window._act_vis_loads.isChecked()
    assert window._canvas._renderer._load_legend_entries == [["Load pattern: LIVE", "#111111"]]
