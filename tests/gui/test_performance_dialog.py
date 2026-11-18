"""GUI smoke test for the performance monitor dialog."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.diagnostics.performance import perf
from opensees_studio.views.dialogs.performance import PerformanceDialog


@pytest.mark.gui
def test_performance_dialog_can_enable_collect_and_reset(qtbot) -> None:  # type: ignore[no-untyped-def]
    was_enabled = perf.enabled
    perf.disable()
    perf.reset()
    try:
        dialog = PerformanceDialog(None)
        qtbot.addWidget(dialog)

        assert dialog._table.columnCount() == 6
        assert dialog._table.rowCount() == 0
        assert not dialog._profile_btn.isEnabled()

        dialog._on_enable()
        with perf.span("test.span"):
            pass
        dialog._refresh()

        assert dialog._profile_btn.isEnabled()
        names = [dialog._table.item(row, 0).text() for row in range(dialog._table.rowCount())]
        assert "test.span" in names

        dialog._on_reset()
        assert dialog._table.rowCount() == 0
        dialog.close()
    finally:
        perf.reset()
        perf.disable()
        if was_enabled:
            perf.enable()
