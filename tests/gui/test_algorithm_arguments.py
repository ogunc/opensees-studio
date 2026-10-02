"""Solver argument form round trip and exact OpenSees emission."""

from unittest.mock import Mock

import pytest

from opensees_studio.core import StaticCase
from opensees_studio.services import load_project, save_project
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.views.dialogs.case_forms import StaticCaseForm
from tests.gui.test_run_snapshot_recovery import _cantilever

pytestmark = pytest.mark.gui


def test_modified_newton_initial_form_save_and_emission(qtbot, tmp_path):
    project = _cantilever()
    form = StaticCaseForm(project.load_patterns, [])
    qtbot.addWidget(form)
    form.populate(StaticCase(id=1, pattern_ids=[1]))
    form._algorithm.setCurrentText("ModifiedNewton")
    form._algorithm_args.setCurrentIndex(1)
    case = form.read()
    project.analyses = [case]
    saved = load_project(save_project(project, tmp_path / "initial.osmodel"))
    assert saved.analyses[0] == case
    assert case.algorithm_args == ("-initial",)
    runner = OpenSeesRunner(saved)
    runner._ops = Mock()
    runner._setup_analysis(case)
    runner._ops.algorithm.assert_called_once_with("ModifiedNewton", "-initial")
    form._algorithm.setCurrentText("Linear")
    assert form.read().algorithm_args == ()
    assert "algorithm_args" not in form.read().model_dump()
