"""Design → Footings through the dialog and the menu."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")
pytest.importorskip("openseespy")

from PySide6.QtCore import Qt

from opensees_studio.views.dialogs.footings import FootingsDialog


def _solved():  # type: ignore[no-untyped-def]
    from tests.integration.test_base_plates_run import _solved

    return _solved()


@pytest.mark.gui
def test_the_dialog_lists_checks_edits_and_sizes(qtbot) -> None:  # type: ignore[no-untyped-def]
    project, settings, results = _solved()
    project.design = settings
    dialog = FootingsDialog(project, results)
    qtbot.addWidget(dialog)
    assert dialog._table.rowCount() == 2
    assert dialog._table.item(0, 2).text() == "W14X90"
    assert "2 footing(s)" in dialog._summary.text()
    dialog._table.selectAll()
    dialog.size_selected()
    assert all(r.status == "OK" for r in dialog.run_check())
    dialog._fields["soil_cover"].setValue(40.0)
    dialog.apply_to_selected()
    assert {d.soil_cover for d in dialog.designs().values()} == {40.0}
    # Untick the second support: it keeps no footing.
    dialog._table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    assert [f.node_id for f in dialog.settings().footings] == [1]
    assert dialog.settings().footing_service_sets == []
    assert "node 1" in dialog._details.toPlainText().lower()


@pytest.mark.gui
def test_the_menu_stores_the_footings_in_one_undo_step(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
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

    monkeypatch.setattr(FootingsDialog, "exec", _accept)
    assert mw._act_footings.isEnabled()
    mw._act_footings.trigger()
    assert len(mw._vm.project.design.footings) == 2
    assert "Footings: 2 footing(s)." in mw._console.toPlainText()
    # Design data: the results stay current.
    assert mw._case_results.current(mw._vm.project)
    mw._vm.undo_stack.undo()
    assert mw._vm.project.design is None
