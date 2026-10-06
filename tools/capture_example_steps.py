"""Replay an official builder in visible production dialogs, outside CI.

Usage: python tools/capture_example_steps.py 07 --out E:/osv-docs/structural/07
The read-back of every dialog must equal the builder input. Library dialogs
apply their own commands; other dialogs return values to the builder command.
Drawing has no modal dialog: its canvas/Properties step is captured as well.
Settings and the final byte-comparison model live in a cleaned temporary folder
inside the output directory. Existing unrelated output files are never removed.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QLocale, QSettings, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QScrollArea

from opensees_studio import commands as cmd
from opensees_studio import core as c
from opensees_studio.services import save_project
from opensees_studio.views.dialogs.add_node import AddNodeDialog
from opensees_studio.views.dialogs.assign_equal_dof import AssignEqualDOFDialog
from opensees_studio.views.dialogs.assign_load import AssignLoadDialog
from opensees_studio.views.dialogs.assign_masses import AssignMassesDialog
from opensees_studio.views.dialogs.assign_property import (
    AssignBeamIntegrationDialog,
    AssignGeomTransfDialog,
    AssignMaterialDialog,
    AssignSectionDialog,
)
from opensees_studio.views.dialogs.assign_support import AssignSupportDialog
from opensees_studio.views.dialogs.assign_zls import AssignZeroLengthSectionDialog
from opensees_studio.views.dialogs.case_manager import AnalysisCaseManagerDialog
from opensees_studio.views.dialogs.constant_time_series import ConstantTimeSeriesDialog
from opensees_studio.views.dialogs.linear_time_series import LinearTimeSeriesDialog
from opensees_studio.views.dialogs.material_library import MaterialLibraryDialog
from opensees_studio.views.dialogs.plain_pattern import PlainPatternDialog
from opensees_studio.views.dialogs.section_editor import FiberSectionEditor
from opensees_studio.views.dialogs.section_library import SectionLibraryDialog
from opensees_studio.views.float_field import FloatField, format_float
from opensees_studio.views.main_window import MainWindow

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def serial(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [serial(v) for v in value]
    return value


def type_number(field, value):
    """Enter decimal-point text through the production numeric widget."""
    field.lineEdit().setText(format_float(value))
    field.interpretText()
    assert field.value() == value, (field.value(), value)


def choose(combo, value):
    index = combo.findData(value)
    assert index >= 0, value
    combo.setCurrentIndex(index)


class Replay:
    def __init__(self, window, output):
        self.window = window
        self.output = output
        self.steps = []
        self.dialog_count = 0

    def capture(self, widget, menu, values, *, dialog=True, close=True):
        widget.show()
        widget.raise_()
        QTest.qWait(60)
        assert widget.isVisible()
        number = len(self.steps) + 1
        name = f"{number:03d}.png"
        assert widget.grab().save(str(self.output / name), "PNG")
        self.steps.append((name, menu, serial(values)))
        self.dialog_count += int(dialog)
        if close:
            widget.accept()
            widget.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def finish_dialog(self, dialog, menu, value, actual):
        assert actual == value, (menu, serial(actual), serial(value))
        self.capture(dialog, menu, value)

    def library(self, vm, value, cls, menu):
        dialog = cls(vm, self.window)
        dialog.show()
        failures = []

        def pick_type():
            picker = QApplication.activeModalWidget()
            try:
                assert isinstance(picker, QInputDialog)
                picker.setTextValue(value.type)
                self.capture(picker, menu + " > Add > Type", value.type, close=False)
            except Exception as exc:
                failures.append(exc)
            finally:
                picker.accept()

        QTimer.singleShot(30, pick_type)
        dialog._on_add()
        if failures:
            raise failures[0]
        form = dialog._stack.currentWidget()
        form.populate(value)
        # Re-enter numeric fields as the exact text an owner can type.
        for field in form.findChildren(FloatField):
            type_number(field, field.value())
        actual = form.read()
        if isinstance(value, c.ElasticSection) and vm.project.ndm == 2:
            # Preserve omitted 3D metadata, unused by the 2D solver.
            actual = actual.model_copy(
                update={key: None for key in ("Iy", "G", "J") if getattr(value, key) is None}
            )
        assert actual == value, (menu, actual, value)
        self.capture(dialog, menu + " > Apply changes", value, close=False)
        if isinstance(value, c.ElasticSection):
            vm.apply_command(cmd.UpdateSectionCommand(vm, actual))
        else:
            dialog._on_apply()
        dialog.accept()
        dialog.deleteLater()
        return True

    def fiber(self, vm, section, template):
        dialog = FiberSectionEditor([m.id for m in vm.project.materials], parent=self.window)
        dialog._section_id, dialog._section_name = section.id, section.name
        menu = "Define > Section Library > New Fiber"
        if template:
            choose(dialog._w_mat, section.patches[0].material_id)
            for key in ("d", "bf", "tf", "tw"):
                type_number(getattr(dialog, "_w_" + key), template[key])
            dialog._w_nfw.setValue(template["n_web"])
            dialog._w_nff.setValue(template["n_flange"])
            dialog._add_template_btn.click()
            self.capture(dialog, menu + " > Add W-shape", template, close=False)
        else:
            dialog.show()
            scroll = dialog.findChild(QScrollArea)
            for patch in section.patches:
                choose(dialog._patch_mat, patch.material_id)
                for key, attr in (("yi", "y_i"), ("zi", "z_i"), ("yj", "y_j"), ("zj", "z_j")):
                    type_number(getattr(dialog, "_rect_" + key), getattr(patch, attr))
                dialog._rect_ny.setValue(patch.n_fib_y)
                dialog._rect_nz.setValue(patch.n_fib_z)
                dialog._add_patch_btn.click()
                scroll.ensureWidgetVisible(dialog._rect_yi)
                self.capture(dialog, menu + " > Add patch", patch, close=False)
            for layer in section.layers:
                choose(dialog._layer_mat, layer.material_id)
                dialog._layer_nbars.setValue(layer.n_bars)
                for key, attr in (
                    ("area", "bar_area"),
                    ("ys", "y_start"),
                    ("zs", "z_start"),
                    ("ye", "y_end"),
                    ("ze", "z_end"),
                ):
                    type_number(getattr(dialog, "_layer_" + key), getattr(layer, attr))
                dialog._add_layer_btn.click()
                scroll.ensureWidgetVisible(dialog._layer_nbars)
                self.capture(dialog, menu + " > Add layer", layer, close=False)
        self.finish_dialog(dialog, menu + " > OK", section, dialog.result_section())

    def __call__(self, vm, kind, value):
        p, parent = vm.project, self.window
        if kind == "node":
            d = AddNodeDialog(value.id, p.grid_system, ndm=p.ndm, parent=parent)
            d._snap_cb.setChecked(False)
            for field, number in zip((d._x, d._y, d._z), value.coords, strict=True):
                type_number(field, number)
            self.finish_dialog(d, "Define > Add Node", value, d.node())
        elif kind == "support":
            ids, restraint = value
            d = AssignSupportDialog(len(ids), parent)
            d._preset_buttons["Custom"].setChecked(True)
            for box, checked in zip(d._dof_boxes, restraint, strict=True):
                box.setChecked(checked)
            assert d.restraint() == restraint
            self.capture(d, "Assign > Joint > Restraints", value)
        elif kind == "mass":
            _nid, vector = value
            d = AssignMassesDialog(1, ndf=p.ndf, ndm=p.ndm, parent=parent)
            for name, number in zip(
                ("_mx", "_my", "_mz", "_mxx", "_myy", "_mzz"), vector, strict=True
            ):
                type_number(getattr(d, name), number)
            assert d.mass_vector() == vector
            self.capture(d, "Assign > Joint > Masses", value)
        elif kind == "material":
            return self.library(vm, value, MaterialLibraryDialog, "Define > Material Library")
        elif kind == "section":
            section, template = value
            if isinstance(section, c.FiberSection):
                self.fiber(vm, section, template)
            else:
                return self.library(vm, section, SectionLibraryDialog, "Define > Section Library")
        elif kind == "equal":
            d = AssignEqualDOFDialog([value.retained_node, value.constrained_node], p.ndf, parent)
            for index, box in enumerate(d._dof_boxes, 1):
                box.setChecked(index in value.dofs)
            self.finish_dialog(d, "Assign > Joint > EqualDOF", value, d.constraint())
        elif kind == "series":
            if isinstance(value, c.ConstantTimeSeries):
                d = ConstantTimeSeriesDialog(vm, parent)
                d._name.setText(value.name)
                type_number(d._factor, value.factor)
                assert d._entity(value.id) == value
                self.capture(d, "Define > Time Series > Constant", value, close=False)
                d._add()
                d.accept()
                d.deleteLater()
                return True
            d = LinearTimeSeriesDialog(value.id, parent)
            d._name_edit.setText(value.name)
            type_number(d._factor_spin, value.factor)
            self.finish_dialog(d, "Define > Time Series > Linear", value, d.time_series())
        elif kind == "pattern":
            d = PlainPatternDialog(p, value.id, parent)
            d._name_edit.setText(value.name)
            choose(d._ts_cb, value.time_series_id)
            self.finish_dialog(d, "Define > Add Plain Load Pattern", value, d.pattern())
        elif kind == "load":
            pid, ids, forces = value
            d = AssignLoadDialog(len(ids), [(p.id, p.name) for p in p.load_patterns], parent)
            choose(d._pattern_cb, pid)
            for field, number in zip(d._spinboxes.values(), forces, strict=True):
                type_number(field, number)
            assert d.forces() == forces and d.selected_pattern_id() == pid
            self.capture(d, "Assign > Joint > Point Loads", value)
        elif kind == "case":
            d = AnalysisCaseManagerDialog(vm, parent)
            d._draft_case = value
            d._refresh_list()
            d._select_by_id(value.id)
            form = d._stack.currentWidget()
            for field in form.findChildren(FloatField):
                type_number(field, field.value())
            assert form.read() == value, (form.read(), value)
            self.capture(d, "Analyze > Cases > Add > Apply changes", value, close=False)
            d._scroll.verticalScrollBar().setValue(d._scroll.verticalScrollBar().maximum())
            if d._scroll.verticalScrollBar().maximum():
                self.capture(d, "Analyze > Cases > Solver settings", value, close=False)
            d._on_apply()
            assert next(a for a in p.analyses if a.id == value.id) == value
            d.accept()
            d.deleteLater()
            return True
        elif kind == "element":
            return self.element(vm, value)
        else:
            raise ValueError(kind)
        return False

    def element(self, vm, element):
        p, parent = vm.project, self.window
        if isinstance(element, c.ZeroLengthSectionElement):
            d = AssignZeroLengthSectionDialog(p, element.nodes, parent)
            choose(d._section_cb, element.section_id)
            assert d.section_id() == element.section_id
            self.capture(d, "Assign > Joint > Zero-Length Section", element)
            return False
        # Draw Frame/Truss use canvas picks, not a modal editor. Reuse their
        # AddElementsCommand and show the actual selection-aware Properties dock.
        vm.apply_command(cmd.AddElementsCommand(vm, [element]))
        parent._canvas.selection.clear()
        parent._canvas.selection.select_element(element.id)
        parent._canvas.view_xy()
        parent._canvas.reset_camera()
        self.capture(
            parent,
            "Draw Frame/Truss toolbar (F2/F3) > Properties",
            element,
            dialog=False,
            close=False,
        )
        if hasattr(element, "material_id"):
            d = AssignMaterialDialog(p.materials, 1, parent)
            choose(d._combo, element.material_id)
            assert d.material_id() == element.material_id
            self.capture(
                d,
                "Assign > Frame > Material",
                {"element": element.id, "material": element.material_id},
            )
        else:
            d = AssignSectionDialog(p.sections, 1, parent)
            choose(d._combo, element.section_id)
            assert d.section_id() == element.section_id
            self.capture(
                d,
                "Assign > Frame > Section",
                {"element": element.id, "section": element.section_id},
            )
            d = AssignGeomTransfDialog(1, 2, element.geom_transf, parent)
            assert d.transf_type() == element.geom_transf
            self.capture(d, "Assign > Frame > Geometric Transformation", element.geom_transf)
            if hasattr(element, "integration_points"):
                d = AssignBeamIntegrationDialog(
                    1, element.integration, element.integration_points, parent
                )
                assert (d.rule(), d.points()) == (
                    element.integration,
                    element.integration_points,
                )
                self.capture(
                    d, "Assign > Frame > Beam Integration", {"rule": d.rule(), "points": d.points()}
                )
        return True

    def write_steps(self, stem):
        lines = [
            f"# {stem}",
            "",
            "Visible production dialogs. Numeric inputs use a decimal point.",
            "Drawing steps also show the canvas and Properties dock. Input values below",
            "retain full precision; display units are inch and kip. A section preview",
            "may retain its generic SI label: do not convert the published numbers.",
            "Elastic section Iy, G and J are unused in 2D; omitted metadata is preserved.",
            "",
        ]
        for index, (png, menu, values) in enumerate(self.steps, 1):
            lines += [
                f"## {index}. {menu}",
                "",
                "Values entered/selected:",
                "",
                "```json",
                json.dumps(values, ensure_ascii=False, indent=2),
                "```",
                "",
                f"![Step {index}]({png})",
                "",
            ]
        lines += [
            f"{len(self.steps)} PNGs, including {self.dialog_count} dialog captures.",
            "",
            "Final replayed model matches the committed .osmodel byte for byte.",
            "",
        ]
        (self.output / "steps.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("example", choices=[f"{i:02}" for i in range(1, 8)])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source = next((ROOT / "examples/official").glob(args.example + "_*.py"))
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    if app.platformName() in {"offscreen", "minimal"}:
        raise RuntimeError("A visible desktop Qt session is required.")
    QLocale.setDefault(QLocale.c())
    QCoreApplication.setOrganizationName("OpenSeesStudioDocumentation")
    QCoreApplication.setApplicationName("ExampleSteps")
    with tempfile.TemporaryDirectory(prefix=".capture-", dir=args.out) as scratch:
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, scratch)
        window = MainWindow()
        window._recovery_timer.stop()
        window.show()
        replay = Replay(window, args.out)
        try:
            module = importlib.import_module("examples.official." + source.stem)
            builder = next(value for key, value in vars(module).items() if key.startswith("build_"))
            project = builder(replay=replay, vm=window._vm)
            saved = save_project(project, Path(scratch) / "replayed.osmodel")
            assert saved.read_bytes() == source.with_suffix(".osmodel").read_bytes()
            replay.write_steps(source.stem)
            print(
                json.dumps(
                    {
                        "example": args.example,
                        "pngs": len(replay.steps),
                        "dialogs": replay.dialog_count,
                        "folder": str(args.out.resolve()),
                    }
                )
            )
        finally:
            window._vm.undo_stack.setClean()
            for widget in app.topLevelWidgets():
                if widget is not window:
                    widget.hide()
                    widget.deleteLater()
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()


if __name__ == "__main__":
    main()
