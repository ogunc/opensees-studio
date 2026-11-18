"""Define → Create Truss: the wizard, the default material, one undo step."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog

from opensees_studio.core import ElasticUniaxial, TrussElement, TrussType
from opensees_studio.views.dialogs import TrussWizard


def _window(qtbot, ndm: int = 2, ndf: int = 2):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=ndm, ndf=ndf)
    return mw


def _accept(monkeypatch, setup=lambda wizard: None) -> None:  # type: ignore[no-untyped-def]
    def _fake_exec(self: TrussWizard) -> int:
        setup(self)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(TrussWizard, "exec", _fake_exec)


@pytest.mark.gui
def test_the_wizard_builds_a_truss_with_a_default_material_in_one_undo_step(
    qtbot, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    _accept(monkeypatch)
    mw._refresh_action_enablement()
    assert mw._act_truss_wizard.isEnabled()

    mw._act_truss_wizard.trigger()

    project = mw._vm.project
    (material,) = project.materials
    assert isinstance(material, ElasticUniaxial)
    assert project.elements and all(isinstance(e, TrussElement) for e in project.elements)
    assert {e.material_id for e in project.elements} == {material.id}
    assert len(project.nodes) == 14  # 6 panels: 7 bottom + 7 top
    assert mw._canvas.selection.elements == {e.id for e in project.elements}

    mw._vm.undo_stack.undo()
    assert (project.nodes, project.elements, project.materials) == ([], [], [])


@pytest.mark.gui
def test_the_wizard_uses_the_chosen_type_and_an_existing_material(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot, ndm=3, ndf=6)
    mw._vm.project.materials.append(ElasticUniaxial(id=5, name="S355", E=210e9))

    def setup(wizard: TrussWizard) -> None:
        wizard._type.setCurrentIndex(2)  # Warren
        wizard._panels.setValue(4)

    _accept(monkeypatch, setup)
    mw._act_truss_wizard.trigger()

    project = mw._vm.project
    assert len(project.materials) == 1
    assert {e.material_id for e in project.elements} == {5}
    assert len(project.nodes) == 5 + 4  # Warren: top nodes at mid-panel
    assert all(node.restraint[3:] == (True, True, True) for node in project.nodes)


@pytest.mark.gui
def test_the_geometry_page_refuses_a_pitched_truss_with_odd_panels(qtbot) -> None:  # type: ignore[no-untyped-def]
    wizard = TrussWizard([], ndm=2, ndf=2)
    qtbot.addWidget(wizard)
    assert wizard._page_geometry.isComplete()
    wizard._chords.setCurrentIndex(1)  # pitched
    wizard._panels.setValue(5)
    assert not wizard._page_geometry.isComplete()
    assert "even number" in wizard._geometry_summary.text()
    wizard._type.setCurrentIndex(2)  # Warren wants an odd count when pitched
    assert wizard._page_geometry.isComplete()
    assert wizard.spec(material_id=1).truss_type is TrussType.WARREN


@pytest.mark.gui
def test_the_plate_form_keeps_the_unit_weight(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core import ElasticMembranePlateSection
    from opensees_studio.views.dialogs.section_forms import ElasticMembranePlateSectionForm

    form = ElasticMembranePlateSectionForm()
    qtbot.addWidget(form)
    form.populate(ElasticMembranePlateSection(id=2, E=1, nu=0.2, h=0.2, unit_weight=24e3))
    assert form.read().unit_weight == 24e3
