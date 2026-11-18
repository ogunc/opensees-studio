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
def _isolated_settings(tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
    """Keep QSettings (recent projects, language, …) out of the user's own."""
    from PySide6.QtCore import QSettings

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path_factory.mktemp("qsettings")),
    )


@pytest.fixture(autouse=True)
def _fresh_load_pattern_memory() -> Iterator[None]:
    """The load dialogs offer the last pattern used; one test must not choose for the next."""
    from opensees_studio.views.dialogs import load_target

    load_target.remember_pattern(None)
    yield
    load_target.remember_pattern(None)


@pytest.fixture(autouse=True)
def _unlock_without_asking(monkeypatch: pytest.MonkeyPatch) -> None:
    """A locked model unlocks as if the user said Yes.

    The model locks itself once an analysis has results, and an edit then asks
    in a modal box that would wedge a test of something else. The tests of the
    lock (test_model_lock.py) put their own answer in its place.
    """
    from opensees_studio.views.main_window import MainWindow

    monkeypatch.setattr(MainWindow, "_confirm_unlock", lambda self: True)


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
