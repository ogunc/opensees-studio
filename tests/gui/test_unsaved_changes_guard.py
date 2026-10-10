"""Unsaved work must never disappear without a question.

``ProjectViewModel.is_dirty`` used to drive only the ``*`` in the window
title, so closing the window, File → New and File → Open dropped the
model in silence. These tests pin the confirmation dialog, each of its
three answers (Save / Discard / Cancel), and the rule that only a
user-initiated close asks: a programmatic ``close()`` during shutdown
must not open a modal dialog.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QFileDialog, QMessageBox

from opensees_studio.commands import AddNodesCommand
from opensees_studio.core import Node


class _SpontaneousClose(QCloseEvent):
    """A close the window manager sent, like clicking the title-bar button."""

    def spontaneous(self) -> bool:  # type: ignore[override]
        return True


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win._vm.new_project(ndm=2, ndf=3)
    win.show()
    qtbot.waitExposed(win)
    return win


def _make_dirty(window) -> None:  # type: ignore[no-untyped-def]
    """Add a node through the undo stack, which is what marks the project dirty."""
    window._vm.apply_command(AddNodesCommand(window._vm, [Node(id=1, coords=(0.0, 0.0, 0.0))]))
    assert window._vm.is_dirty


def _answer(monkeypatch: pytest.MonkeyPatch, button: QMessageBox.StandardButton) -> list[str]:
    """Patch the confirmation dialog; return the list of titles it was asked with."""
    seen: list[str] = []

    def _warning(parent, title, text, *args, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(title)
        return button

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(_warning))
    return seen


# ─────────────────────── File → Quit ───────────────────────
@pytest.mark.gui
def test_cancelling_the_quit_keeps_the_window_and_the_model(qtbot, window, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _make_dirty(window)
    seen = _answer(monkeypatch, QMessageBox.StandardButton.Cancel)

    window._on_quit()

    assert seen == ["Unsaved changes"]
    assert window.isVisible()
    assert [n.id for n in window._vm.project.nodes] == [1]
    # The cancelled request must not leak into the next close.
    assert window._user_close_requested is False


@pytest.mark.gui
def test_discarding_the_quit_throws_the_changes_away(qtbot, window, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _make_dirty(window)
    _answer(monkeypatch, QMessageBox.StandardButton.Discard)

    window._on_quit()

    assert not window.isVisible()


@pytest.mark.gui
def test_a_clean_project_quits_without_asking(qtbot, window, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert not window._vm.is_dirty
    seen = _answer(monkeypatch, QMessageBox.StandardButton.Cancel)

    window._on_quit()

    assert seen == []
    assert not window.isVisible()


@pytest.mark.gui
def test_saving_from_the_prompt_writes_the_file_then_closes(  # type: ignore[no-untyped-def]
    qtbot, window, monkeypatch, tmp_path
) -> None:
    _make_dirty(window)
    _answer(monkeypatch, QMessageBox.StandardButton.Save)
    target = tmp_path / "save-on-close.osmodel"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "")),
    )

    window._on_quit()

    assert target.exists()
    assert not window.isVisible()


# ─────────────────────── window-manager close ───────────────────────
@pytest.mark.gui
def test_the_window_manager_close_asks_too(qtbot, window, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _make_dirty(window)
    seen = _answer(monkeypatch, QMessageBox.StandardButton.Cancel)

    event = _SpontaneousClose()
    window.closeEvent(event)

    assert seen == ["Unsaved changes"]
    assert not event.isAccepted()
    assert window.isVisible()


@pytest.mark.gui
def test_a_programmatic_close_never_asks(qtbot, window, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Shutdown paths (tests, closeAllWindows) must not block on a modal dialog."""
    _make_dirty(window)
    seen = _answer(monkeypatch, QMessageBox.StandardButton.Cancel)

    window.close()

    assert seen == []
    assert not window.isVisible()


# ─────────────────────── new / open ───────────────────────
@pytest.mark.gui
def test_new_project_can_be_cancelled(qtbot, window, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _make_dirty(window)
    before = window._vm.project
    _answer(monkeypatch, QMessageBox.StandardButton.Cancel)

    window._on_new()

    assert window._vm.project is before
    assert [n.id for n in window._vm.project.nodes] == [1]


@pytest.mark.gui
def test_new_project_proceeds_after_discard(qtbot, window, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _make_dirty(window)
    before = window._vm.project
    _answer(monkeypatch, QMessageBox.StandardButton.Discard)

    window._on_new()

    assert window._vm.project is not before
    assert window._vm.project.nodes == []


@pytest.mark.gui
def test_open_can_be_cancelled_before_the_file_dialog(qtbot, window, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _make_dirty(window)
    before = window._vm.project
    _answer(monkeypatch, QMessageBox.StandardButton.Cancel)
    calls: list[str] = []

    def _get_open_file_name(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append("shown")
        return ("", "")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(_get_open_file_name))

    window._on_open()

    # The prompt comes first: the user is not asked to pick a file and only
    # then told the model would be discarded.
    assert calls == []
    assert window._vm.project is before


@pytest.mark.gui
def test_open_asks_and_then_opens(qtbot, window, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core import Project
    from opensees_studio.services import save_project

    _make_dirty(window)
    other = save_project(Project(nodes=[Node(id=7, coords=(1.0, 2.0, 0.0))]), tmp_path / "other")
    _answer(monkeypatch, QMessageBox.StandardButton.Discard)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *a, **k: (str(other), "")),
    )

    window._on_open()

    assert [n.id for n in window._vm.project.nodes] == [7]
    assert Path(window._vm.path) == other
