"""Assign Zero-Length Element: one material per global DOF."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import ElasticUniaxial, Node, Project
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.views.dialogs.assign_zero_length import AssignZeroLengthDialog


def _project(ndm: int = 3, ndf: int = 6) -> Project:
    return Project(
        ndm=ndm,
        ndf=ndf,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(0.0, 0.0, 0.0)),
        ],
        materials=[
            ElasticUniaxial(id=1, name="soft", E=1.0),
            ElasticUniaxial(id=2, name="stiff", E=2.0),
        ],
    )


def _dialog(qtbot, project: Project) -> AssignZeroLengthDialog:  # type: ignore[no-untyped-def]
    dialog = AssignZeroLengthDialog(project, (1, 2))
    qtbot.addWidget(dialog)
    return dialog


@pytest.mark.gui
def test_the_dialog_starts_with_the_first_dof_and_its_material(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _project())

    assert dialog.property(TOPIC_PROPERTY) == "assign.zero_length"
    assert list(dialog.dof_checks) == [1, 2, 3, 4, 5, 6]
    assert [dof for dof, check in dialog.dof_checks.items() if check.isChecked()] == [1]

    element = dialog.build_element(7)

    assert (element.type, element.nodes) == ("ZeroLength", (1, 2))
    assert element.dofs == (1,)
    assert element.material_ids == (1,)


@pytest.mark.gui
def test_each_ticked_dof_carries_its_own_material_in_order(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _project())
    dialog.dof_checks[2].setChecked(True)
    dialog.dof_checks[6].setChecked(True)
    dialog.dof_materials[2].setCurrentIndex(1)
    dialog.dof_materials[6].setCurrentIndex(0)
    dialog.do_rayleigh.setChecked(True)

    element = dialog.build_element(9)

    assert element.dofs == (1, 2, 6)
    assert element.material_ids == (1, 2, 1)
    assert element.do_rayleigh is True


@pytest.mark.gui
def test_a_2d_model_offers_only_its_three_dofs(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _project(ndm=2, ndf=3))

    assert list(dialog.dof_checks) == [1, 2, 3]
    assert dialog.build_element(3).dofs == (1,)


@pytest.mark.gui
def test_no_ticked_dof_is_refused(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = _dialog(qtbot, _project())
    dialog.dof_checks[1].setChecked(False)

    with pytest.raises(ValueError, match="at least one DOF"):
        dialog.build_element(1)


@pytest.mark.gui
def test_without_a_uniaxial_material_the_dialog_says_so(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(0.0, 0.0, 0.0)),
        ],
    )
    dialog = _dialog(qtbot, project)

    assert not dialog.dof_materials[1].isEnabled()
    with pytest.raises(ValueError, match="uniaxial material"):
        dialog.build_element(1)
