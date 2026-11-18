"""Design → Connections by Joint through the dialog and the menu."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")
pytest.importorskip("openseespy")

from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.views.dialogs.joint_connections import JointConnectionsDialog


def _solved():  # type: ignore[no-untyped-def]
    from tests.integration.test_joint_connections_run import _simple_beam_portal

    project = _simple_beam_portal()
    return project, {1: OpenSeesRunner(project).run(project.analyses[0])}


@pytest.mark.gui
def test_the_dialog_lists_the_connections_and_edits_shear_tabs(qtbot) -> None:  # type: ignore[no-untyped-def]
    project, results = _solved()
    dialog = JointConnectionsDialog(project, results)
    qtbot.addWidget(dialog)
    assert dialog._table.rowCount() == 4
    statuses = [dialog._table.item(r, 5).text() for r in range(4)]
    assert statuses.count("OK") == 2
    assert "2 shear tab(s) checked, 0 over the limit" in dialog._summary.text()
    tab_rows = [r for r in range(4) if dialog._table.item(r, 5).text() == "OK"]
    dialog._table.selectRow(tab_rows[0])
    assert dialog._apply.isEnabled()
    dialog._fields["tp"].setValue(0.5)
    dialog.apply_to_selected()
    saved = dialog.settings().shear_tabs
    assert len(saved) == 1 and saved[0].tp == 0.5


@pytest.mark.gui
def test_the_menu_stores_the_tabs_in_one_undo_step(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    project, results = _solved()
    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.adopt(project)
    for result in results.values():
        mw._case_results.put(project, result)

    def _accept(self) -> int:  # type: ignore[no-untyped-def]
        rows = [r for r in range(self._table.rowCount()) if self._table.item(r, 5).text() == "OK"]
        self._table.selectRow(rows[0])
        self._bolts.setValue(3)
        self.apply_to_selected()
        return 1

    monkeypatch.setattr(JointConnectionsDialog, "exec", _accept)
    assert mw._act_joint_connections.isEnabled()
    mw._act_joint_connections.trigger()
    assert [t.bolts for t in mw._vm.project.design.shear_tabs] == [3]
    assert "Connections by joint: 4 connection(s), 2 shear tab(s)." in mw._console.toPlainText()
    mw._vm.undo_stack.undo()
    assert mw._vm.project.design is None
