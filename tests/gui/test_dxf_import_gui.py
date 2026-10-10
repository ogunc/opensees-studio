"""Importing a DXF drawing through the dialog and the File menu.

The conversion itself is pinned in ``tests/unit/test_dxf_import.py``; here the
wiring is: the dialog reads the file and explains it, the menu action inserts
what the dialog says it will, in one undo step, and a drawing with nothing to
import is refused before the model is touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")
pytest.importorskip("ezdxf")

import ezdxf
from PySide6.QtWidgets import QDialog, QMessageBox

from opensees_studio.commands import AddSectionsCommand
from opensees_studio.core import ElasticSection
from opensees_studio.views.dialogs import DxfImportDialog


def _drawing(
    tmp_path: Path,
    *,
    name: str = "frame.dxf",
    insunits: int = 6,
    factor: float = 1.0,
) -> Path:
    """A small portal frame drawing: two columns, a beam, and an axis layer.

    ``factor`` scales the coordinates, so a drawing that says it is in
    millimetres can carry millimetre-sized numbers (6 m is 6000 mm).
    """
    document = ezdxf.new("R2010")
    document.header["$INSUNITS"] = insunits
    msp = document.modelspace()

    def dart(x: float, y: float) -> tuple[float, float]:
        return (x * factor, y * factor)

    msp.add_line(dart(0, 0), dart(0, 4), dxfattribs={"layer": "COLUMNAS"})
    msp.add_line(dart(6, 0), dart(6, 4), dxfattribs={"layer": "COLUMNAS"})
    msp.add_line(dart(0, 4), dart(6, 4), dxfattribs={"layer": "VIGAS"})
    msp.add_line(dart(0, 0), dart(6, 0), dxfattribs={"layer": "EJES"})
    msp.add_circle(dart(3, 2), 0.5 * factor, dxfattribs={"layer": "EJES"})
    path = tmp_path / name
    document.saveas(path)
    return path


def _section(sid: int = 1, name: str = "S") -> ElasticSection:
    return ElasticSection(id=sid, name=name, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6)


def _window(qtbot, *, ndm: int = 3, ndf: int = 6, sections: bool = True):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=ndm, ndf=ndf)
    if sections:
        mw._vm.apply_command(AddSectionsCommand(mw._vm, [_section()]))
    return mw


# ──────────────────────────── the dialog ────────────────────────────
@pytest.mark.gui
def test_the_dialog_reads_a_drawing_and_says_what_it_will_do(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core import Project

    project = Project(ndm=3, ndf=6, sections=[_section()])
    dialog = DxfImportDialog(project, sections=[_section()])
    qtbot.addWidget(dialog)

    assert dialog.load(_drawing(tmp_path))

    # Every layer is offered, all of them ticked to start with.
    listed = [dialog._layers.item(row).text() for row in range(dialog._layers.count())]
    assert listed == ["COLUMNAS", "EJES", "VIGAS"]
    assert dialog.chosen_layers() == listed
    # Four straight bars and one circle: the bar count is in the summary, the
    # circle is in the "not imported" note.
    assert "4 member(s)" in dialog._summary.text()
    assert "1 CIRCLE" in dialog._summary.text()
    assert dialog.plane() == "XZ"  # elevations are what portal drawings are
    assert dialog._ok.isEnabled()


@pytest.mark.gui
def test_unticking_a_layer_takes_its_bars_out(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    from opensees_studio.core import Project

    project = Project(ndm=3, ndf=6)
    dialog = DxfImportDialog(project, sections=[_section()])
    qtbot.addWidget(dialog)
    dialog.load(_drawing(tmp_path))

    axes = next(
        dialog._layers.item(row)
        for row in range(dialog._layers.count())
        if dialog._layers.item(row).text() == "EJES"
    )
    axes.setCheckState(Qt.CheckState.Unchecked)

    assert dialog.chosen_layers() == ["COLUMNAS", "VIGAS"]
    assert "3 member(s)" in dialog._summary.text()


@pytest.mark.gui
def test_a_unitless_drawing_says_nothing_is_converted(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core import Project

    project = Project(ndm=3, ndf=6)
    dialog = DxfImportDialog(project, sections=[_section()])
    qtbot.addWidget(dialog)

    dialog.load(_drawing(tmp_path, name="unitless.dxf", insunits=0))

    assert "unitless" in dialog._units.text()
    assert "nothing is converted" in dialog._units.text()
    assert dialog.scale() == 1.0


@pytest.mark.gui
def test_a_millimetre_drawing_is_scaled_to_the_project_units(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core import Project

    project = Project(ndm=3, ndf=6)  # SI metres
    dialog = DxfImportDialog(project, sections=[_section()])
    qtbot.addWidget(dialog)

    # A drawing dimensioned in millimetres: 6000 by 4000 of them.
    dialog.load(_drawing(tmp_path, name="mm.dxf", insunits=4, factor=1000.0))

    assert "millimetres" in dialog._units.text()
    assert dialog.scale() == pytest.approx(1e-3)
    bars = dialog.imported_bars(1)
    assert bars is not None
    assert (6.0, 0.0, 4.0) in [node.coords for node in bars.nodes]  # 6000 mm → 6 m


@pytest.mark.gui
def test_a_2d_project_reads_the_drawing_as_its_own_plane(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core import Project

    project = Project(ndm=2, ndf=3)
    dialog = DxfImportDialog(project, sections=[_section()])
    qtbot.addWidget(dialog)

    assert not dialog._plane.isEnabled()
    assert dialog.plane() == "XY"


@pytest.mark.gui
def test_a_drawing_with_nothing_to_import_is_refused(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core import Project

    document = ezdxf.new("R2010")
    document.modelspace().add_circle((0, 0), 1)
    path = tmp_path / "circles.dxf"
    document.saveas(path)

    dialog = DxfImportDialog(Project(ndm=3, ndf=6), sections=[_section()])
    qtbot.addWidget(dialog)
    dialog.load(path)

    assert not dialog._ok.isEnabled()
    assert "Nothing to import" in dialog._summary.text()


@pytest.mark.gui
def test_a_file_that_cannot_be_read_is_reported_in_the_dialog(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core import Project

    path = tmp_path / "broken.dxf"
    path.write_text("not a drawing\n" * 10, encoding="utf-8")

    dialog = DxfImportDialog(Project(ndm=3, ndf=6), sections=[_section()])
    qtbot.addWidget(dialog)

    assert dialog.load(path) is False
    assert "not a readable DXF" in dialog._summary.text()
    assert not dialog._ok.isEnabled()


# ──────────────────────────── through the menu ────────────────────────────
@pytest.mark.gui
def test_the_menu_imports_the_bars_in_one_undo_step(qtbot, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    # Millimetre drawing, millimetre numbers, metre project.
    path = _drawing(tmp_path, name="mm.dxf", insunits=4, factor=1000.0)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.StandardButton.Ok)

    def _fake_load(self: DxfImportDialog) -> None:
        assert self.load(path)
        self._layers.item(1).setCheckState(self._layers.item(1).checkState())  # no-op, stays

    real_init = DxfImportDialog.__init__

    def _init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        real_init(self, *args, **kwargs)
        _fake_load(self)

    monkeypatch.setattr(DxfImportDialog, "__init__", _init)
    monkeypatch.setattr(DxfImportDialog, "exec", lambda self: int(QDialog.DialogCode.Accepted))

    assert mw._act_import_dxf.isEnabled()
    mw._act_import_dxf.trigger()

    project = mw._vm.project
    assert len(project.elements) == 4  # columns, beam and the axis bar
    assert (0.0, 0.0, 0.0) in [tuple(node.coords) for node in project.nodes]
    assert (0.0, 0.0, 4.0) in [tuple(node.coords) for node in project.nodes]  # 4000 mm → 4 m
    assert "Imported 4 member(s)" in mw._console.toPlainText()
    assert "1 CIRCLE" in mw._console.toPlainText()
    assert mw._canvas.selection.nodes  # left selected

    mw._vm.undo_stack.undo()
    assert project.nodes == [] and project.elements == []


@pytest.mark.gui
def test_importing_without_a_section_creates_the_default_one_in_the_same_step(
    qtbot,
    tmp_path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot, sections=False)
    path = _drawing(tmp_path)

    real_init = DxfImportDialog.__init__

    def _init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        real_init(self, *args, **kwargs)
        self.load(path)

    monkeypatch.setattr(DxfImportDialog, "__init__", _init)
    monkeypatch.setattr(DxfImportDialog, "exec", lambda self: int(QDialog.DialogCode.Accepted))

    mw._act_import_dxf.trigger()

    project = mw._vm.project
    assert len(project.sections) == 1
    assert project.sections[0].name == "Default Section"
    assert {element.section_id for element in project.elements} == {project.sections[0].id}

    mw._vm.undo_stack.undo()  # the section goes back with the bars
    assert project.sections == [] and project.elements == []
