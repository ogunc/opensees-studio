"""Design → Base Plates through the dialog and the menu."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")
pytest.importorskip("openseespy")

from opensees_studio.views.dialogs.base_plates import BasePlatesDialog


def _solved():  # type: ignore[no-untyped-def]
    from tests.integration.test_base_plates_run import _solved

    return _solved()


@pytest.mark.gui
def test_the_dialog_lists_checks_edits_and_sizes(qtbot) -> None:  # type: ignore[no-untyped-def]
    project, settings, results = _solved()
    project.design = settings
    dialog = BasePlatesDialog(project, results)
    qtbot.addWidget(dialog)
    assert dialog._table.rowCount() == 2
    assert dialog._table.item(0, 2).text() == "fixed"
    assert "2 column base(s)" in dialog._summary.text()
    dialog._table.selectAll()
    dialog.size_selected()
    assert [d.tp for d in dialog.designs().values()] == [pytest.approx(1.25)] * 2
    assert all(r.status == "OK" for r in dialog.run_check())
    dialog._fields["n_length"].setValue(22.0)
    dialog.apply_to_selected()
    assert {d.n_length for d in dialog.designs().values()} == {22.0}
    saved = dialog.settings().base_plates
    assert [p.node_id for p in saved] == [1, 2]


@pytest.mark.gui
def test_the_menu_stores_the_plates_in_one_undo_step(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    project, _settings, results = _solved()
    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.adopt(project)
    for result in results.values():
        mw._case_results.put(project, result)

    def _accept(self) -> int:  # type: ignore[no-untyped-def]
        self._table.selectAll()
        self.size_selected()
        return 1

    monkeypatch.setattr(BasePlatesDialog, "exec", _accept)
    assert mw._act_base_plates.isEnabled()
    mw._act_base_plates.trigger()
    assert len(mw._vm.project.design.base_plates) == 2
    assert "Base plates: 2 column base(s)." in mw._console.toPlainText()
    mw._vm.undo_stack.undo()
    assert mw._vm.project.design is None
