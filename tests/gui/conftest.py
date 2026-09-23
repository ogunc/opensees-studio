"""GUI test session boundary: tear Qt and VTK down while the QApplication lives.

Without this, windows a test left open (a MainWindow with its ModelCanvas
render window, active timers) are finalized during interpreter exit, after
pytest has already run its last GC pass, in whatever order Python picks.
"""

from __future__ import annotations

import gc
from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session", autouse=True)
def _qt_vtk_session_teardown(qapp) -> Iterator[None]:  # type: ignore[no-untyped-def]
    yield
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer

    # Finalize every VTK render window first, while its Qt widget exists.
    try:
        import pyvista
    except ImportError:
        pass
    else:
        pyvista.close_all()

    for timer in qapp.findChildren(QTimer):
        timer.stop()
    for widget in qapp.topLevelWidgets():
        for timer in widget.findChildren(QTimer):
            timer.stop()
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    gc.collect()
