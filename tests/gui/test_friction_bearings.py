"""Friction models and sliding bearings through the GUI: library dialog, bearing dialog,
rendering, undo, refusal with the dialog kept open, deletion of a used model refused."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog, QMessageBox

from opensees_studio.commands import (
    AddElementsCommand,
    AddFrictionModelsCommand,
    AddMaterialsCommand,
    AddNodesCommand,
    DeleteFrictionModelsCommand,
)
from opensees_studio.core import (
    CoulombFriction,
    ElasticUniaxial,
    FlatSliderBearingElement,
    Node,
    Project,
    SingleFPBearingElement,
    UnitSystem,
    VelDependentFriction,
    gravity,
)
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs.assign_bearing import AssignElastomericBearingDialog
from opensees_studio.views.dialogs.friction_library import FrictionLibraryDialog

MU, W, K_INIT, R_EFF = 0.1, 100.0, 1000.0, 2.0


def _project(ndm: int = 2, friction: bool = True) -> Project:
    return Project(
        ndm=ndm,
        ndf=3 if ndm == 2 else 6,
        nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(0, 0, 0))],
        materials=[ElasticUniaxial(id=1, name="P", E=1e7), ElasticUniaxial(id=2, name="M", E=1e6)],
        friction_models=[CoulombFriction(id=1, name="PTFE", mu=MU)] if friction else [],
    )


def _vm(project: Project) -> ProjectViewModel:
    vm = ProjectViewModel()
    vm._project = project
    vm.projectChanged.emit(project)
    return vm


def _bearing(kind: str, friction_model_id: int = 1):  # type: ignore[no-untyped-def]
    common = dict(
        id=9,
        nodes=(1, 2),
        friction_model_id=friction_model_id,
        k_init=K_INIT,
        p_material_id=1,
        mz_material_id=2,
    )
    if kind == "SingleFPBearing":
        return SingleFPBearingElement(**common, r_eff=R_EFF)
    return FlatSliderBearingElement(**common)


@pytest.mark.gui
def test_friction_library_adds_edits_and_refuses_deleting_a_used_model(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    vm = _vm(_project(friction=False))
    dlg = FrictionLibraryDialog(vm)
    qtbot.addWidget(dlg)
    assert dlg._list.count() == 0

    coulomb = dlg.add_model("Coulomb")
    assert isinstance(coulomb, CoulombFriction) and coulomb.id == 1
    assert [fm.type for fm in vm.project.friction_models] == ["Coulomb"]
    # edit through the form: the Apply button runs an UpdateFrictionModelCommand
    form = dlg._stack.currentWidget()
    form._mu.setValue(0.08)
    form._name_edit.setText("edited")
    dlg._on_apply()
    assert vm.project.friction_models[0].mu == 0.08
    assert vm.project.friction_models[0].name == "edited"
    vel = dlg.add_model("VelDependent")
    assert isinstance(vel, VelDependentFriction) and vel.id == 2
    assert dlg._list.count() == 2

    # a bearing uses model 1: deleting it is refused, the model stays
    vm.apply_command(AddElementsCommand(vm, [_bearing("FlatSliderBearing", friction_model_id=1)]))
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *a, **k: warnings.append(str(a[2])) or QMessageBox.StandardButton.Ok,
    )
    assert dlg.delete_model(1) is False
    assert [fm.id for fm in vm.project.friction_models] == [1, 2]
    assert warnings and "used by bearing element(s) 9" in warnings[0]
    with pytest.raises(ValueError, match="used by bearing element"):
        DeleteFrictionModelsCommand(vm, {1}).redo()
    # the unused model can go, and undo brings it back
    assert dlg.delete_model(2) is True
    assert [fm.id for fm in vm.project.friction_models] == [1]
    vm.undo_stack.undo()
    assert [fm.id for fm in vm.project.friction_models] == [1, 2]


def _dialog(qtbot, project: Project, kind: str) -> AssignElastomericBearingDialog:  # type: ignore[no-untyped-def]
    dlg = AssignElastomericBearingDialog(project, (1, 2))
    qtbot.addWidget(dlg)
    dlg._type.setCurrentIndex(dlg._type.findData(kind))
    dlg._k_init.setValue(K_INIT)
    dlg._weight.setValue(W)
    return dlg


@pytest.mark.gui
def test_dialog_builds_both_sliding_bearings_with_helpers(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _project()
    dlg = _dialog(qtbot, project, "FlatSliderBearing")
    assert dlg.is_sliding()
    assert dlg._friction.currentData() == 1
    assert not dlg._qd.isVisibleTo(dlg) and not dlg._r_eff.isVisibleTo(dlg)
    assert dlg._friction.isVisibleTo(dlg) and dlg._weight.isVisibleTo(dlg)
    assert f"{MU * W / K_INIT:.6g}" in dlg.derived_text()  # slip displacement mu W / Kinit
    flat = dlg.build_element(7)
    assert isinstance(flat, FlatSliderBearingElement)
    assert (flat.id, flat.nodes, flat.friction_model_id, flat.k_init) == (7, (1, 2), 1, K_INIT)
    assert (flat.p_material_id, flat.mz_material_id, flat.max_iter, flat.tol) == (1, 1, 25, 1e-12)

    dlg._type.setCurrentIndex(dlg._type.findData("SingleFPBearing"))
    assert dlg._r_eff.isVisibleTo(dlg)
    dlg._r_eff.setValue(R_EFF)
    dlg._max_iter.setValue(40)
    text = dlg.derived_text()
    assert f"{W / R_EFF:.6g}" in text  # restoring stiffness W / Reff
    period = 2.0 * 3.141592653589793 * (R_EFF / gravity(UnitSystem.SI_M_N)) ** 0.5
    assert f"{period:.6g} s" in text  # isolated period in project units (SI: g = 9.80665)
    pendulum = dlg.build_element(8)
    assert isinstance(pendulum, SingleFPBearingElement)
    assert (pendulum.r_eff, pendulum.max_iter) == (R_EFF, 40)

    # back to an elastomeric type: the sliding rows hide again
    dlg._type.setCurrentIndex(dlg._type.findData("ElastomericBearingPlasticity"))
    assert dlg._qd.isVisibleTo(dlg) and not dlg._friction.isVisibleTo(dlg)


@pytest.mark.gui
def test_dialog_without_friction_models_refuses_sliding_bearings(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = _dialog(qtbot, _project(friction=False), "SingleFPBearing")
    assert not dlg._friction.isEnabled()
    assert "no friction model" in dlg.derived_text()
    with pytest.raises(ValueError, match="Define a friction model first"):
        dlg.build_element(1)


@pytest.mark.gui
def test_invalid_reff_is_refused_and_keeps_the_dialog_open(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = _dialog(qtbot, _project(), "SingleFPBearing")
    dlg._r_eff.setValue(0.0)  # Reff must be positive (a zero radius makes OpenSees fail with NaN)
    with pytest.raises(ValueError, match="r_eff"):
        dlg.build_element(1)
    dlg.accept()
    assert dlg.result() != QDialog.DialogCode.Accepted
    assert "r_eff" in dlg.error_text()
    dlg._r_eff.setValue(R_EFF)
    dlg.accept()
    assert dlg.result() == QDialog.DialogCode.Accepted and dlg.error_text() == ""


@pytest.mark.gui
def test_main_window_creates_renders_and_undoes_sliding_bearings(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    mw._vm.apply_command(
        AddNodesCommand(
            mw._vm,
            [Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6), Node(id=2, coords=(0, 0.3, 0))],
        )
    )
    mw._vm.apply_command(AddMaterialsCommand(mw._vm, [ElasticUniaxial(id=1, name="P", E=1e7)]))
    mw._vm.apply_command(AddFrictionModelsCommand(mw._vm, [CoulombFriction(id=1, mu=MU)]))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.StandardButton.Ok)
    assert mw._act_friction_library.text() == "&Friction Models…"
    mw._canvas.selection.select_node(1)
    mw._canvas.selection.select_node(2, additive=True)
    mw._refresh_action_enablement()
    assert mw._act_assign_bearing.isEnabled()

    kinds = iter(("FlatSliderBearing", "SingleFPBearing"))

    def _fake_exec(self: AssignElastomericBearingDialog) -> int:
        self._type.setCurrentIndex(self._type.findData(next(kinds)))
        self._k_init.setValue(K_INIT)
        self._r_eff.setValue(R_EFF)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(AssignElastomericBearingDialog, "exec", _fake_exec)
    mw._act_assign_bearing.trigger()
    project = mw._vm.project
    assert [el.type for el in project.elements] == ["FlatSliderBearing"]
    flat = project.elements[0]
    assert flat.nodes == (1, 2) and flat.friction_model_id == 1
    renderer = mw._canvas._renderer
    assert renderer._frame_pd is not None and flat.id in renderer._frame_ids_ordered
    tip = mw.element_tooltip(flat.id)
    assert tip is not None and "friction model #1 (Coulomb)" in tip and "Reff" not in tip

    mw._canvas.selection.select_node(1)
    mw._canvas.selection.select_node(2, additive=True)
    mw._act_assign_bearing.trigger()
    assert [el.type for el in project.elements] == ["FlatSliderBearing", "SingleFPBearing"]
    pendulum = project.elements[1]
    tip = mw.element_tooltip(pendulum.id)
    assert tip is not None and "Reff = 2" in tip and "T = 2 pi sqrt(Reff / g)" in tip
    assert len(renderer._frame_ids_ordered) == 2

    # property editor rows for the pendulum: Reff and the isolated period
    mw._canvas.selection.select_element(pendulum.id)
    labels = [w.text() for w in mw._props.findChildren(type(mw._props._layout.itemAt(0).widget()))]
    assert "Reff:" in labels and any(t.endswith(" s") for t in labels)

    mw._vm.undo_stack.undo()
    assert [el.type for el in project.elements] == ["FlatSliderBearing"]
    mw._vm.undo_stack.undo()
    assert project.elements == []
    assert renderer._frame_pd is None or len(renderer._frame_ids_ordered) == 0
    # the friction model is still there and the library dialog can delete it now
    assert [fm.id for fm in project.friction_models] == [1]
    lib = FrictionLibraryDialog(mw._vm, mw)
    qtbot.addWidget(lib)
    assert lib.delete_model(1) is True
    assert project.friction_models == []
