"""GUI tests for Define dialogs."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import LinearTimeSeries, Project  # noqa: E402
from opensees_studio.views.dialogs.linear_time_series import LinearTimeSeriesDialog  # noqa: E402
from opensees_studio.views.dialogs.plain_pattern import PlainPatternDialog  # noqa: E402


@pytest.mark.gui
def test_linear_time_series_dialog_builds_entity(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = LinearTimeSeriesDialog(next_ts_id=3)
    qtbot.addWidget(dlg)

    dlg._name_edit.setText("Gravity")
    dlg._factor_spin.setValue(1.5)

    ts = dlg.time_series()
    assert ts.id == 3
    assert ts.name == "Gravity"
    assert ts.factor == pytest.approx(1.5)


@pytest.mark.gui
def test_plain_pattern_dialog_uses_selected_time_series(qtbot) -> None:  # type: ignore[no-untyped-def]
    proj = Project(time_series=[
        LinearTimeSeries(id=1, name="GravityTS"),
        LinearTimeSeries(id=2, name="RampTS"),
    ])
    dlg = PlainPatternDialog(project=proj, next_pattern_id=4)
    qtbot.addWidget(dlg)

    dlg._name_edit.setText("Gravity")
    dlg._ts_cb.setCurrentIndex(1)

    pat = dlg.pattern()
    assert pat.id == 4
    assert pat.name == "Gravity"
    assert pat.time_series_id == 2
