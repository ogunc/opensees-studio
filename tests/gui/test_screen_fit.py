"""Dialogs open inside the screen's available area; warnings and refusals stay in sight.

These run on the real screen (not offscreen): the available area is the
desktop without the taskbar, and every audited dialog's frame must lie
inside it right after show. Long case forms scroll instead of growing the
dialog, and the Ground Motions status and warning lines are outside the
scrolling forms, fully visible without moving the window.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QDialog, QWidget

from opensees_studio.core import PathTimeSeries
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs.assign_bearing import AssignElastomericBearingDialog
from opensees_studio.views.dialogs.case_manager import AnalysisCaseManagerDialog
from opensees_studio.views.dialogs.friction_library import FrictionLibraryDialog
from opensees_studio.views.dialogs.generate_excitation import GenerateExcitationDialog
from opensees_studio.views.dialogs.ground_motions import GroundMotionsDialog
from opensees_studio.views.dialogs.section_editor import FiberSectionEditor
from opensees_studio.views.screen_fit import SCREEN_FRACTION, available_geometry
from tests.gui.test_ground_motions_scaling import DT, _open, _values, _write_at2

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _vm(name: str, tmp_path: Path) -> ProjectViewModel:
    target = tmp_path / f"{name}.osmodel"
    shutil.copy(EXAMPLES / f"{name}.osmodel", target)
    if not (tmp_path / "data").exists():
        shutil.copytree(EXAMPLES / "data", tmp_path / "data")
    vm = ProjectViewModel()
    vm.open(target)
    return vm


def _case_manager(example: str, case_type: str) -> Callable[[Path], QDialog]:
    def build(tmp_path: Path) -> QDialog:
        vm = _vm(example, tmp_path)
        dlg = AnalysisCaseManagerDialog(vm)
        dlg._vm_ref = vm  # keep the view model alive with the dialog
        case = next(c for c in vm.project.analyses if c.type == case_type)
        dlg._select_by_id(case.id)
        return dlg

    return build


def _ground_motions(tmp_path: Path) -> QDialog:
    vm = _vm("ex1a_canti2d", tmp_path)
    dlg = GroundMotionsDialog(vm)
    dlg._vm_ref = vm
    return dlg


def _generator(kind: str) -> Callable[[Path], QDialog]:
    def build(tmp_path: Path) -> QDialog:
        vm = _vm("ex1a_canti2d", tmp_path)
        gm = GroundMotionsDialog(vm)
        dlg = GenerateExcitationDialog(gm.view_model)
        dlg._keep = (vm, gm)
        dlg.set_kind(kind)
        return dlg

    return build


def _bearing(kind: str) -> Callable[[Path], QDialog]:
    def build(tmp_path: Path) -> QDialog:
        vm = _vm("isolated_portal2d_fp", tmp_path)
        dlg = AssignElastomericBearingDialog(vm.project, (1, 2))
        dlg._vm_ref = vm
        dlg._type.setCurrentIndex(dlg._type.findData(kind))
        return dlg

    return build


def _friction(tmp_path: Path) -> QDialog:
    vm = _vm("isolated_portal2d_fp", tmp_path)
    dlg = FrictionLibraryDialog(vm)
    dlg._vm_ref = vm
    return dlg


def _fiber(tmp_path: Path) -> QDialog:
    return FiberSectionEditor([1, 2])


AUDITED = {
    "case Transient": _case_manager("ex1a_canti2d", "Transient"),
    "case ResponseSpectrum": _case_manager("space_frame_3d", "ResponseSpectrum"),
    "case Modal": _case_manager("space_frame_3d", "Modal"),
    "case Static": _case_manager("space_frame_3d", "Static"),
    "Ground Motions": _ground_motions,
    "Generate sine-beat": _generator("sine-beat"),
    "Generate sine": _generator("sine"),
    "bearing elastomeric": _bearing("ElastomericBearingPlasticity"),
    "bearing single FP": _bearing("SingleFPBearing"),
    "Friction Models": _friction,
    "Fiber Section Editor": _fiber,
}


def _show(qtbot, dlg: QWidget) -> QRect:  # type: ignore[no-untyped-def]
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    return available_geometry(dlg)


def _fully_visible_in(widget: QWidget, dlg: QWidget) -> bool:
    """``widget`` is shown, unclipped, and lies inside ``dlg``'s own rectangle."""
    top_left = widget.mapTo(dlg, QPoint(0, 0))
    in_dialog = dlg.rect().contains(QRect(top_left, widget.size()))
    unclipped = widget.visibleRegion().boundingRect() == widget.rect()
    return widget.isVisible() and in_dialog and unclipped


@pytest.mark.gui
@pytest.mark.parametrize("name", sorted(AUDITED))
def test_audited_dialog_opens_inside_the_available_screen(qtbot, tmp_path, name) -> None:  # type: ignore[no-untyped-def]
    dlg = AUDITED[name](tmp_path)
    avail = _show(qtbot, dlg)
    frame = dlg.frameGeometry()
    assert avail.contains(frame), f"{name}: frame {frame} outside available {avail}"
    assert frame.width() <= int(avail.width() * SCREEN_FRACTION) + 1
    assert frame.height() <= int(avail.height() * SCREEN_FRACTION) + 1
    assert dlg.minimumWidth() < avail.width() and dlg.maximumHeight() > avail.height()  # resizable
    dlg.close()


@pytest.mark.gui
def test_a_case_form_taller_than_the_dialog_scrolls(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    dlg = _case_manager("ex1a_canti2d", "Transient")(tmp_path)
    avail = _show(qtbot, dlg)
    dlg.resize(dlg.width(), min(420, avail.height()))
    qtbot.wait(50)
    form = dlg._stack.currentWidget()
    viewport = dlg._scroll.viewport()
    assert form.sizeHint().height() > viewport.height()
    bar = dlg._scroll.verticalScrollBar()
    assert bar.maximum() > 0
    # Apply changes and the message line stay outside the scroll area, in sight.
    assert _fully_visible_in(dlg._apply_btn, dlg)
    bar.setValue(bar.maximum())
    assert _fully_visible_in(dlg._apply_btn, dlg)
    dlg.close()


@pytest.mark.gui
def test_case_refusal_is_shown_next_to_apply(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    dlg = _case_manager("ex1a_canti2d", "Transient")(tmp_path)
    _show(qtbot, dlg)
    dlg._stack.currentWidget()._dt.setMinimum(0.0)
    dlg._stack.currentWidget()._dt.setValue(0.0)
    dlg._apply_btn.click()
    assert "Case rejected" in dlg.message_text()
    assert _fully_visible_in(dlg._message, dlg)
    dlg.close()


def _records(dlg, tmp_path, count: int) -> list[int]:  # type: ignore[no-untyped-def]
    for i, peak in enumerate((0.25, 0.40, 0.30)[:count], start=1):
        path = tmp_path / f"rec{i}.AT2"
        _write_at2(path, _values(i, peak))
        assert dlg.import_file(str(path))
    project = dlg._vm.project
    for rec in project.ground_motions:
        project.time_series.append(
            PathTimeSeries(id=rec.id, dt=DT, values=[0.0, 0.0], record_id=rec.id)
        )
    dlg._refresh()
    return [rec.id for rec in project.ground_motions]


@pytest.mark.gui
def test_record_count_warning_is_visible_without_scrolling(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _mw, dlg = _open(qtbot)
    qtbot.waitExposed(dlg)
    ids = _records(dlg, tmp_path, 3)
    assert dlg.set_target_tbdy_site(0.45, 0.117, "ZC", "DD-2")
    dlg.select_records(ids)
    dlg._method.setCurrentIndex(dlg._method.findData("period_range"))
    dlg._t1.setValue(0.8)
    assert dlg.preview_scaling() is not None
    assert "Only 3 records" in dlg.scale_warning_text()
    assert available_geometry(dlg).contains(dlg.frameGeometry())
    assert _fully_visible_in(dlg._scale_warning, dlg)
    assert dlg._scale_warning.level == "warning"
    # scrolling the forms does not move the warning
    bar = dlg._forms_scroll.verticalScrollBar()
    bar.setValue(bar.maximum())
    assert _fully_visible_in(dlg._scale_warning, dlg)


@pytest.mark.gui
def test_tld_refusal_is_visible_inside_the_available_screen(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _mw, dlg = _open(qtbot)
    qtbot.waitExposed(dlg)
    ids = _records(dlg, tmp_path, 1)
    assert dlg.set_target_tbdy(0.585, 0.1755, vertical=True)
    dlg.select_records(ids)
    dlg._method.setCurrentIndex(dlg._method.findData("period_range"))
    dlg._t1.setValue(2.5)
    assert dlg.preview_scaling() is None
    assert "defined only up to TLD = 3 s" in dlg.status_text()
    assert dlg._status.level == "error"
    avail = available_geometry(dlg)
    assert avail.contains(dlg.frameGeometry())
    assert _fully_visible_in(dlg._status, dlg)
    top_left = dlg._status.mapToGlobal(QPoint(0, 0))
    assert avail.contains(QRect(top_left, dlg._status.size()))  # above the taskbar


@pytest.mark.gui
def test_bearing_refusal_stays_next_to_the_buttons(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    dlg = _bearing("ElastomericBearingPlasticity")(tmp_path)
    _show(qtbot, dlg)
    dlg._alpha1.setValue(1.0)
    dlg.accept()
    assert "alpha1" in dlg.error_text()
    assert _fully_visible_in(dlg._error, dlg)
    assert dlg.isVisible()
    dlg.close()
