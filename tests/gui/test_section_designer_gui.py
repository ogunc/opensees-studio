"""Define → Section Designer: commands, undo, DXF import, and the section OK adds."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog, QDialogButtonBox

from opensees_studio.core import ElasticSection, FiberSection, Project, ProjectMeta, Steel02
from opensees_studio.views.dialogs.section_designer import SectionDesignerDialog


def _project() -> Project:
    steel = Steel02(id=3, name="A572", Fy=345e6, E0=200e9, b=0.01)
    return Project(meta=ProjectMeta(), ndm=3, ndf=6, materials=[steel])


@pytest.mark.gui
def test_commands_build_the_section_and_undo_steps_back(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = SectionDesignerDialog(_project())
    qtbot.addWidget(dialog)
    ok = dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    dialog._command.setText("rect 0.3 0.5")
    dialog.run()
    assert dialog._command.text() == ""
    assert dialog._list.count() == 1 and ok.isEnabled()
    assert pytest.approx(0.15) == dialog.properties().A  # type: ignore[union-attr]
    assert dialog.run("hole circle 0.1")
    assert pytest.approx(0.15 - 3.14159265 * 0.05**2) == dialog.properties().A  # type: ignore[union-attr]
    assert not dialog.run("rect")
    assert "Usage" in dialog._message.text()
    dialog.undo()
    assert dialog._list.count() == 1
    assert "J =" in dialog._summary.text()


@pytest.mark.gui
def test_elastic_and_fiber_results(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = SectionDesignerDialog(_project())
    qtbot.addWidget(dialog)
    dialog.run("ishape 0.3 0.15 0.012 0.008")
    dialog._name.setText("Built-up I")
    dialog._from_material.setCurrentIndex(1)
    elastic = dialog.built_section()
    assert isinstance(elastic, ElasticSection)
    assert elastic.name == "Built-up I" and elastic.E == 200e9
    assert pytest.approx(dialog._j.value()) == elastic.J
    dialog._kind.setCurrentIndex(1)
    fiber = dialog.built_section()
    assert isinstance(fiber, FiberSection)
    assert {f.material_id for f in fiber.fibres} == {3}


@pytest.mark.gui
def test_import_dxf(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    import ezdxf

    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4  # mm
    doc.modelspace().add_lwpolyline([(0, 0), (300, 0), (300, 500), (0, 500)], close=True)
    path = tmp_path / "rect.dxf"
    doc.saveas(path)
    dialog = SectionDesignerDialog(_project())
    qtbot.addWidget(dialog)
    assert dialog.import_dxf(path)
    props = dialog.properties()
    assert props is not None
    assert pytest.approx(0.15) == props.A
    assert (props.y_c, props.z_c) == pytest.approx((0.0, 0.0), abs=1e-12)
    assert "millimetres" in dialog._message.text()
    assert not dialog.import_dxf(tmp_path / "missing.dxf")


@pytest.mark.gui
def test_the_menu_adds_the_section(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.adopt(_project())

    def _accept(self) -> int:  # type: ignore[no-untyped-def]
        self.run("pipe 0.3 0.01")
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(SectionDesignerDialog, "exec", _accept)
    mw._act_section_designer.trigger()
    project = mw._vm.project
    assert len(project.sections) == 1
    assert project.sections[0].name == "Designed section"
    mw._vm.undo_stack.undo()
    assert not project.sections
