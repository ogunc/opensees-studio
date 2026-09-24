"""GUI tests for analysis case forms."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import (
    NodalLoad,
    PlainLoadPattern,
    StaticCase,
    TransientCase,
)
from opensees_studio.views.dialogs.case_forms import TransientCaseForm


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


@pytest.mark.gui
def test_modal_case_form_offers_auto_arpack_dense_and_shows_a_stored_other_name(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core import ModalCase
    from opensees_studio.views.dialogs.case_forms import ModalCaseForm

    form = ModalCaseForm(_patterns(), [])
    qtbot.addWidget(form)
    offered = [form._solver.itemData(i) for i in range(form._solver.count())]
    assert offered == ["auto", "genBandArpack", "fullGenLapack"]
    assert "500 free DOF" in form._solver.itemText(0)

    # A new case reads back the routing default.
    form._name_edit.setText("Modes")
    assert form._read_specific(7).solver == "auto"

    # An explicit choice round-trips by its data, not by its label.
    form._populate_specific(ModalCase(id=7, name="Modes", n_modes=4, solver="fullGenLapack"))
    assert form._read_specific(7).solver == "fullGenLapack"

    # A stored symmBandLapack (loads, refused at run time) is shown, not silently replaced.
    form._populate_specific(ModalCase(id=7, name="Modes", solver="symmBandLapack"))
    assert form._solver.currentData() == "symmBandLapack"
    assert "refused" in form._solver.currentText()
    assert form._read_specific(7).solver == "symmBandLapack"
