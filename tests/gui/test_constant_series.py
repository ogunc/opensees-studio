"""Constant preload creation, editing and reference-safe deletion."""

from unittest.mock import Mock

import pytest

from opensees_studio.core import PlainLoadPattern
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs.constant_time_series import ConstantTimeSeriesDialog

pytestmark = pytest.mark.gui


def test_constant_crud_and_exact_emission(qtbot):
    vm = ProjectViewModel()
    vm.new_project(ndm=2, ndf=3)
    dialog = ConstantTimeSeriesDialog(vm)
    qtbot.addWidget(dialog)
    dialog._factor.setValue(2.5)
    dialog._add()
    dialog._list.setCurrentRow(0)
    dialog._factor.setValue(3.5)
    dialog._apply()
    series = vm.project.time_series[0]
    runner = OpenSeesRunner(vm.project)
    runner._ops = Mock()
    runner._emit_time_series(series)
    runner._ops.timeSeries.assert_called_once_with("Constant", 1, "-factor", 3.5)
    vm.project.load_patterns.append(PlainLoadPattern(id=1, time_series_id=1))
    dialog._list.setCurrentRow(0)
    dialog._delete()
    assert "used by pattern 1" in dialog._message.text()
    assert len(vm.project.time_series) == 1
    vm.project.load_patterns.clear()
    dialog._delete()
    assert not vm.project.time_series
    vm.undo_stack.undo()
    assert vm.project.time_series[0] == series
