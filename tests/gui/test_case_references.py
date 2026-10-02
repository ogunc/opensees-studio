"""Invalid case references remain repairable but cannot be applied or run."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog, QMessageBox

from opensees_studio.core import PushoverCase, StaticCase
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs.case_manager import AnalysisCaseManagerDialog
from opensees_studio.views.main_window import MainWindow
from tests.gui.test_run_snapshot_recovery import _cantilever

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("missing", ["pattern", "time series", "control node", "preload case"])
def test_invalid_case_marked_refused_and_named(qtbot, missing):
    project = _cantilever()
    case = PushoverCase(
        id=2, pattern_ids=[1], control_node=2, control_dof=1, target_disp=0.1, step_size=0.01
    )
    if missing == "pattern":
        case = case.model_copy(update={"pattern_ids": [99]})
    elif missing == "time series":
        project.time_series.clear()
    elif missing == "control node":
        case = case.model_copy(update={"control_node": 99})
    else:
        case = case.model_copy(update={"preload_case_ids": [99]})
    project.analyses = [case]
    vm = ProjectViewModel()
    vm._project = project
    dialog = AnalysisCaseManagerDialog(vm)
    qtbot.addWidget(dialog)
    assert "Invalid references" in dialog._list.item(0).text()
    assert f"missing {missing}" in dialog._list.item(0).toolTip()
    dialog._on_apply()
    assert f"missing {missing}" in dialog.message_text()
    assert not vm.is_dirty
    with pytest.raises(ValueError, match=f"missing {missing}"):
        OpenSeesRunner(project).run(case)


def test_save_warns_but_preserves_invalid_case(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window._vm._project = _cantilever()
    window._vm.project.analyses = [StaticCase(id=1, pattern_ids=[99])]
    window._vm._path = tmp_path / "invalid.osmodel"
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: messages.append(a[2]))
    window._on_save()
    assert "missing pattern 99" in messages[0]
    assert window._vm.path.exists()


def test_new_case_with_invalid_defaults_can_be_repaired_before_commit(qtbot, monkeypatch):
    vm = ProjectViewModel()
    vm._project = _cantilever()
    vm.project.analyses.clear()
    vm.project.load_patterns[0] = vm.project.load_patterns[0].model_copy(update={"id": 8})
    dialog = AnalysisCaseManagerDialog(vm)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **kw: ("Static", True))
    dialog._on_add()
    assert not vm.project.analyses
    form = dialog._stack.currentWidget()
    for row in range(form._patterns_picker.count()):
        item = form._patterns_picker.item(row)
        item.setSelected(item.data(Qt.ItemDataRole.UserRole) == 8)
    dialog._on_apply()
    assert vm.project.analyses[0].pattern_ids == [8]
