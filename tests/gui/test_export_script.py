"""File → Export → OpenSees script: the model leaves the application as code."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QFileDialog, QInputDialog

from opensees_studio.services.opensees_script import case_label

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture
def window_with_project(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    assert win.open_project(EXAMPLES / "cantilever.osmodel")
    return win


def _choose(monkeypatch: pytest.MonkeyPatch, target: Path, case: str | None) -> None:
    """Answer the two dialogs: which case, and where to write."""
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    if case is not None:
        monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: (case, True)))


@pytest.mark.gui
def test_exporting_writes_a_runnable_model_script(
    qtbot, window_with_project, monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    target = tmp_path / "cantilever.py"
    _choose(monkeypatch, target, "Model only")

    window_with_project._on_export_script()

    source = target.read_text(encoding="utf-8")
    assert "ops.model('basic', '-ndm', 3, '-ndf', 6)" in source
    assert "Analysis:" not in source


@pytest.mark.gui
def test_exporting_can_include_a_case(qtbot, window_with_project, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    case = window_with_project._vm.project.analyses[0]
    target = tmp_path / "cantilever_case.py"
    _choose(monkeypatch, target, case_label(case))

    window_with_project._on_export_script()

    source = target.read_text(encoding="utf-8")
    assert f"# --- Analysis: case {case_label(case)} ---" in source
    assert "ops.analysis('Static')" in source


@pytest.mark.gui
def test_cancelling_the_case_chooser_writes_nothing(
    qtbot, window_with_project, monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    target = tmp_path / "never.py"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("", False)))

    window_with_project._on_export_script()

    assert not target.exists()


@pytest.mark.gui
def test_without_a_project_it_says_so(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    from opensees_studio.views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    assert win._vm.project is None
    calls: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *a, **k: calls.append(a[1]))
    )

    win._on_export_script()

    assert calls == ["Export script"]
