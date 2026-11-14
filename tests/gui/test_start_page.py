"""The start page with no project open, and File → Open Recent."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import QSettings

from opensees_studio.views.start_page import MAX_RECENT, RecentFiles


@pytest.fixture
def recent(tmp_path: Path) -> RecentFiles:
    return RecentFiles(QSettings(str(tmp_path / "recent.ini"), QSettings.Format.IniFormat))


def _touch(folder: Path, name: str) -> Path:
    path = folder / name
    path.write_text("{}", encoding="utf-8")
    return path


@pytest.fixture
def window(qtbot, tmp_path):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._recent = RecentFiles(QSettings(str(tmp_path / "w.ini"), QSettings.Format.IniFormat))
    mw._start_page._recent = mw._recent
    yield mw
    mw._help_controller.uninstall()


@pytest.mark.gui
def test_newest_first_without_duplicates_and_capped(recent, tmp_path) -> None:
    files = [_touch(tmp_path, f"p{k}.osmodel") for k in range(MAX_RECENT + 2)]
    for path in files:
        recent.add(path)
    recent.add(files[3])
    paths = recent.paths()
    assert paths[0] == files[3].resolve()
    assert len(paths) == MAX_RECENT
    assert len(set(paths)) == len(paths)


@pytest.mark.gui
def test_a_missing_file_is_hidden_not_forgotten(recent, tmp_path) -> None:
    path = _touch(tmp_path, "gone.osmodel")
    recent.add(path)
    path.unlink()
    assert recent.paths() == []
    path.write_text("{}", encoding="utf-8")
    assert recent.paths() == [path.resolve()]


@pytest.mark.gui
def test_the_start_page_shows_until_a_project_exists(window) -> None:
    assert window._central.currentWidget() is window._start_page
    window._vm.new_project(ndm=3, ndf=6)
    assert window._central.currentWidget() is window._main_canvas


@pytest.mark.gui
def test_saving_and_opening_fill_the_recent_menu(window, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QFileDialog

    window._vm.new_project(ndm=3, ndf=6)
    target = tmp_path / "frame.osmodel"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    assert window._on_save_as()
    assert window._recent.paths() == [target.resolve()]

    window._fill_recent_menu()
    texts = [action.text() for action in window._menu_recent.actions()]
    assert texts[0] == "&1 frame.osmodel"

    window._on_clear_recent()
    window._fill_recent_menu()
    assert "No recent projects" in [a.text() for a in window._menu_recent.actions()]
