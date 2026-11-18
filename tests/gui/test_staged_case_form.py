"""Analyze → Cases → Staged construction: the stage table round-trips."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import ConstructionStage, StagedCase
from opensees_studio.views.dialogs.case_forms import form_for


@pytest.mark.gui
def test_the_stage_table_round_trips(qtbot) -> None:  # type: ignore[no-untyped-def]
    case = StagedCase(
        id=4,
        name="Build",
        new_joints="follow",
        stages=[
            ConstructionStage(name="Pour", add_group_ids=[1, 2], pattern_ids=[1], n_steps=2),
            ConstructionStage(name="Strike", remove_group_ids=[3]),
        ],
    )
    form = form_for(case, [], [])
    qtbot.addWidget(form)
    form.populate(case)
    assert form.read() == case
    form._append(ConstructionStage(name="Finishes", pattern_ids=[2]))
    again = form.read()
    assert [s.name for s in again.stages] == ["Pour", "Strike", "Finishes"]
    assert again.stages[2].pattern_ids == [2]


@pytest.mark.gui
def test_time_dependent_stages_round_trip(qtbot) -> None:  # type: ignore[no-untyped-def]
    case = StagedCase(
        id=2,
        name="Creep",
        time_dependent=True,
        start_time=14.0,
        stages=[ConstructionStage(name="Load", pattern_ids=[1], duration=3650.0, time_steps=40)],
    )
    form = form_for(case, [], [])
    qtbot.addWidget(form)
    assert form.read() == case


@pytest.mark.gui
def test_the_mc2010_dialog_builds_the_material(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core import Project
    from opensees_studio.views.dialogs.mc2010_concrete import Mc2010ConcreteDialog

    dialog = Mc2010ConcreteDialog(Project(ndm=2, ndf=3))
    qtbot.addWidget(dialog)
    material = dialog.material()
    assert material.type == "TDConcreteMC10"
    assert material.fc == pytest.approx(-38e6)  # MPa -> Pa
    assert "φ =" in dialog._preview.text()
