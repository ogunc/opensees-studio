"""Options → Language: the menus and dialogs in Spanish, and back to English."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.core.i18n import catalog, translate


def _menu_titles(window) -> list[str]:  # type: ignore[no-untyped-def]
    return [a.text() for a in window.menuBar().actions()]


@pytest.mark.gui
def test_switching_to_spanish_and_back(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from opensees_studio.views.main_window import MainWindow

    monkeypatch.setattr(QSettings, "setValue", lambda *a, **k: None)
    window = MainWindow()
    qtbot.addWidget(window)
    english = _menu_titles(window)
    window._on_language("es")
    assert "Archivo" in _menu_titles(window) and "Diseño" in _menu_titles(window)
    save_as = next(
        a
        for a in window.findChildren(type(window._act_steel_check))
        if a is window._act_steel_check
    )
    assert save_as.text().startswith("Verificación de marcos de acero")
    window._on_language("en")
    assert _menu_titles(window) == english


@pytest.mark.gui
def test_every_menu_action_has_a_spanish_label(qtbot) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMenu

    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    missing = []
    for menu in window.menuBar().findChildren(QMenu):
        texts = [menu.title(), *(a.text() for a in menu.actions())]
        for text in texts:
            skip = (
                not text or text.startswith(tuple("0123456789")) or text in ("English", "Español")
            )
            if not skip and translate(text, "es") is None:
                missing.append(text)
    assert not sorted(set(missing)), (
        f"{len(set(missing))} labels without Spanish: {sorted(set(missing))}"
    )
    assert catalog("es")


@pytest.mark.gui
def test_a_dialog_opened_in_spanish_is_translated(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from opensees_studio.core import Project
    from opensees_studio.views.dialogs.concrete_design import ConcreteDesignDialog
    from opensees_studio.views.main_window import MainWindow

    monkeypatch.setattr(QSettings, "setValue", lambda *a, **k: None)
    window = MainWindow()
    qtbot.addWidget(window)
    window._on_language("es")
    try:
        dialog = ConcreteDesignDialog(Project(ndm=2, ndf=3), {})
        qtbot.addWidget(dialog)
        dialog.show()
        assert dialog.windowTitle() == "Verificación de marcos de hormigón (ACI 318-19)"
        from PySide6.QtWidgets import QLabel

        labels = [label.text() for label in dialog.findChildren(QLabel)]
        assert "Factor de hormigón liviano λ:" in labels
    finally:
        window._on_language("en")
