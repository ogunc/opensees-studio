"""The case forms preserve the gravity-then-lateral command sequence and curve."""

from unittest.mock import Mock

import numpy as np
import openseespy.opensees as ops
import pytest
from examples.rc_frame_pushover import build_rc_frame_pushover

from opensees_studio.core import StaticCase, TransientCase
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.views.dialogs.case_forms import PushoverCaseForm, TransientCaseForm, form_for

pytestmark = pytest.mark.gui


def test_gui_preloads_match_rc_pushover_sequence_and_curve(qtbot):
    reference = build_rc_frame_pushover()
    recorded = Mock(wraps=ops)
    expected = OpenSeesRunner(reference, ops_module=recorded).run(reference.analyses[1])
    commands = recorded.mock_calls
    rebuilt = reference.model_copy(deep=True)
    rebuilt.analyses = []
    for case in reference.analyses:
        form = form_for(case, rebuilt.load_patterns, reference.analyses)
        qtbot.addWidget(form)
        rebuilt.analyses.append(form.read())
    recorded.reset_mock()
    actual = OpenSeesRunner(rebuilt, ops_module=recorded).run(rebuilt.analyses[1])
    assert recorded.mock_calls == commands
    np.testing.assert_allclose(actual.control_disp, expected.control_disp, rtol=1e-10, atol=1e-12)
    np.testing.assert_allclose(actual.base_shear, expected.base_shear, rtol=1e-10, atol=1e-12)
    print(
        "Pushover maximum absolute curve difference:",
        np.max(np.abs(actual.base_shear - expected.base_shear)),
    )


@pytest.mark.parametrize("kind", ["Pushover", "Transient"])
def test_preload_order_and_only_static(qtbot, kind):
    project = build_rc_frame_pushover()
    project.analyses.append(StaticCase(id=200, pattern_ids=[1]))
    case = project.analyses[1] if kind == "Pushover" else TransientCase(id=3, dt=0.01, n_steps=1)
    case = case.model_copy(update={"preload_case_ids": [200, 100]})
    cls = PushoverCaseForm if kind == "Pushover" else TransientCaseForm
    form = cls(project.load_patterns, project.analyses)
    qtbot.addWidget(form)
    form.populate(case)
    assert form._preload_picker.count() == 2
    assert form.read().preload_case_ids == [200, 100]
    assert not project.case_reference_errors(case)
    assert (
        "cycle"
        in project.case_reference_errors(case.model_copy(update={"preload_case_ids": [case.id]}))[0]
    )
