"""GUI tests for analysis case forms."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import (  # noqa: E402
    NodalLoad,
    PlainLoadPattern,
    StaticCase,
    TransientCase,
)
from opensees_studio.views.dialogs.case_forms import TransientCaseForm  # noqa: E402


def _patterns():  # type: ignore[no-untyped-def]
    return [
        PlainLoadPattern(
            id=1,
            name="Gravity",
            time_series_id=1,
            nodal_loads=[NodalLoad(node_id=1, forces=(0.0, -1.0, 0.0, 0.0, 0.0, 0.0))],
        ),
        PlainLoadPattern(
            id=2,
            name="EQ",
            time_series_id=1,
            nodal_loads=[NodalLoad(node_id=1, forces=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0))],
        ),
    ]


@pytest.mark.gui
def test_transient_case_form_round_trips_preload_and_damping(qtbot) -> None:  # type: ignore[no-untyped-def]
    analyses = [
        StaticCase(id=1, name="Gravity", pattern_ids=[1], n_steps=10),
        StaticCase(id=2, name="Wind", pattern_ids=[2], n_steps=5),
    ]
    form = TransientCaseForm(_patterns(), analyses)
    qtbot.addWidget(form)

    case = TransientCase(
        id=3,
        name="Earthquake",
        pattern_ids=[2],
        preload_case_ids=[1],
        remove_patterns=[1],
        dt=0.01,
        n_steps=3995,
        rayleigh_alpha_m=0.01,
        rayleigh_beta_k=2.5e-4,
        rayleigh_mode1_damping=0.02,
    )
    form.populate(case)

    rebuilt = form.read()
    assert rebuilt.pattern_ids == [2]
    assert rebuilt.preload_case_ids == [1]
    assert rebuilt.remove_patterns == [1]
    assert rebuilt.dt == pytest.approx(0.01)
    assert rebuilt.n_steps == 3995
    assert rebuilt.rayleigh_alpha_m == pytest.approx(0.01)
    assert rebuilt.rayleigh_beta_k == pytest.approx(2.5e-4)
    assert rebuilt.rayleigh_mode1_damping == pytest.approx(0.02)


@pytest.mark.gui
def test_transient_case_form_zero_mode1_damping_reads_as_none(qtbot) -> None:  # type: ignore[no-untyped-def]
    form = TransientCaseForm(_patterns(), [StaticCase(id=1, name="Gravity", pattern_ids=[1])])
    qtbot.addWidget(form)

    form._name_edit.setText("Transient")
    form._dt.setValue(0.02)
    form._n_steps.setValue(100)
    form._mode1_damping.setValue(0.0)
    form._beta_k.setValue(1.0e-4)
    form._patterns_picker.item(1).setSelected(True)

    rebuilt = form.read(case_id=2)
    assert rebuilt.pattern_ids == [2]
    assert rebuilt.rayleigh_beta_k == pytest.approx(1.0e-4)
    assert rebuilt.rayleigh_mode1_damping is None
