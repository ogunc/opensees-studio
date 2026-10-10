"""Elastomeric bearing definition through the dialog, rendering, undo, refusal."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog, QMessageBox

from opensees_studio.commands import AddMaterialsCommand, AddNodesCommand
from opensees_studio.core import (
    ElasticUniaxial,
    ElastomericBearingBoucWenElement,
    ElastomericBearingPlasticityElement,
    Node,
    Project,
)
from opensees_studio.views.dialogs.assign_bearing import AssignElastomericBearingDialog

K_INIT, QD, ALPHA1 = 1000.0, 10.0, 0.1
U_Y = QD / (K_INIT * (1.0 - ALPHA1))


def _project(ndm: int = 2) -> Project:
    return Project(
        ndm=ndm,
        ndf=3 if ndm == 2 else 6,
        nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(0, 0, 0))],
        materials=[ElasticUniaxial(id=1, name="P", E=1e7), ElasticUniaxial(id=2, name="M", E=1e6)],
    )


def _dialog(qtbot, project: Project) -> AssignElastomericBearingDialog:  # type: ignore[no-untyped-def]
    dlg = AssignElastomericBearingDialog(project, (1, 2))
    qtbot.addWidget(dlg)
    dlg._k_init.setValue(K_INIT)
    dlg._qd.setValue(QD)
    dlg._alpha1.setValue(ALPHA1)
    return dlg


@pytest.mark.gui
def test_dialog_builds_both_bearings_with_derived_helpers(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = _dialog(qtbot, _project())
    assert dlg._p_mat.count() == 2 and dlg._mz_mat.currentData() == 1
    assert not dlg._t_mat.isVisibleTo(dlg) and not dlg._my_mat.isVisibleTo(dlg)
    dlg._mz_mat.setCurrentIndex(1)
    # derived helpers: u_y, F_y and K_eff at the given displacement
    dlg._u_eff.setValue(4.0 * U_Y)
    assert f"{U_Y:.6g}" in dlg.derived_text()
    assert f"{QD / (1.0 - ALPHA1):.6g}" in dlg.derived_text()
    k_eff = (QD + ALPHA1 * K_INIT * 4.0 * U_Y) / (4.0 * U_Y)
    assert f"{k_eff:.6g}" in dlg.derived_text()

    plasticity = dlg.build_element(7)
    assert isinstance(plasticity, ElastomericBearingPlasticityElement)
    assert (
        plasticity.id,
        plasticity.nodes,
        plasticity.p_material_id,
        plasticity.mz_material_id,
    ) == (
        7,
        (1, 2),
        1,
        2,
    )
    assert not dlg._eta.isEnabled()

    dlg._type.setCurrentIndex(dlg._type.findData("ElastomericBearingBoucWen"))
    assert dlg._eta.isEnabled()
    dlg._eta.setValue(10.0)
    dlg._do_rayleigh.setChecked(True)
    dlg._mass.setValue(0.5)
    bouc_wen = dlg.build_element(8)
    assert isinstance(bouc_wen, ElastomericBearingBoucWenElement)
    assert (bouc_wen.eta, bouc_wen.do_rayleigh, bouc_wen.mass) == (10.0, True, 0.5)


@pytest.mark.gui
def test_dialog_3d_needs_t_and_my_materials(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = _dialog(qtbot, _project(ndm=3))
    assert dlg._t_mat.isVisibleTo(dlg) and dlg._my_mat.isVisibleTo(dlg)
    el = dlg.build_element(3)
    assert (el.t_material_id, el.my_material_id) == (1, 1)


@pytest.mark.gui
def test_invalid_alpha_is_refused_and_keeps_the_dialog_open(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = _dialog(qtbot, _project())
    dlg._alpha1.setValue(1.0)  # alpha1 must be < 1
    with pytest.raises(ValueError, match="alpha1"):
        dlg.build_element(1)
    dlg.accept()
    assert dlg.result() != QDialog.DialogCode.Accepted
    assert "alpha1" in dlg.error_text()
    dlg._alpha1.setValue(0.1)
    dlg.accept()
    assert dlg.result() == QDialog.DialogCode.Accepted and dlg.error_text() == ""


@pytest.mark.gui
def test_main_window_creates_renders_and_undoes_bearings(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    mw._vm.apply_command(
        AddNodesCommand(
            mw._vm,
            [
                Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
                Node(id=2, coords=(0, 0.3, 0)),
            ],
        )
    )
    mw._vm.apply_command(AddMaterialsCommand(mw._vm, [ElasticUniaxial(id=1, name="P", E=1e7)]))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.StandardButton.Ok)
    mw._canvas.selection.select_node(1)
    mw._canvas.selection.select_node(2, additive=True)
    mw._refresh_action_enablement()
    assert mw._act_assign_bearing.isEnabled()

    created: dict[str, AssignElastomericBearingDialog] = {}

    def _fake_exec(self: AssignElastomericBearingDialog) -> int:
        self._k_init.setValue(K_INIT)
        self._qd.setValue(QD)
        self._alpha1.setValue(ALPHA1)
        if created:
            self._type.setCurrentIndex(self._type.findData("ElastomericBearingBoucWen"))
        created[self.bearing_type()] = self
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(AssignElastomericBearingDialog, "exec", _fake_exec)
    mw._act_assign_bearing.trigger()
    project = mw._vm.project
    assert [el.type for el in project.elements] == ["ElastomericBearingPlasticity"]
    first = project.elements[0]
    assert first.nodes == (1, 2) and first.k_init == K_INIT

    # rendered like the other line elements: the frame polydata carries its id
    renderer = mw._canvas._renderer
    assert renderer._frame_pd is not None and first.id in renderer._frame_ids_ordered
    # the tooltip provider describes the bearing, nothing for a missing element
    tip = mw.element_tooltip(first.id)
    assert tip is not None and "Kinit = 1000" in tip and f"u_y = {U_Y:.6g}" in tip
    assert mw.element_tooltip(999) is None
    assert mw._canvas.element_tooltip == mw.element_tooltip

    # the property editor shows the derived yield values for the selection
    mw._canvas.selection.select_element(first.id)
    labels = [w.text() for w in mw._props.findChildren(type(mw._props._layout.itemAt(0).widget()))]
    assert any(f"{U_Y:.6g}" == t for t in labels)

    # second bearing: Bouc-Wen
    mw._canvas.selection.select_node(1)
    mw._canvas.selection.select_node(2, additive=True)
    mw._act_assign_bearing.trigger()
    assert [el.type for el in project.elements] == [
        "ElastomericBearingPlasticity",
        "ElastomericBearingBoucWen",
    ]
    assert len(renderer._frame_ids_ordered) == 2

    # undo removes them again, one per step, and the render follows
    mw._vm.undo_stack.undo()
    assert [el.type for el in project.elements] == ["ElastomericBearingPlasticity"]
    mw._vm.undo_stack.undo()
    assert project.elements == []
    assert renderer._frame_pd is None or len(renderer._frame_ids_ordered) == 0


@pytest.mark.gui
def test_canvas_hover_resolves_the_bearing_for_the_tooltip(qtbot) -> None:  # type: ignore[no-untyped-def]
    import numpy as np

    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw.show()
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6), Node(id=2, coords=(0, 0.3, 0))],
        materials=[ElasticUniaxial(id=1, E=1e7)],
        elements=[
            ElastomericBearingPlasticityElement(
                id=5,
                nodes=(1, 2),
                k_init=K_INIT,
                qd=QD,
                alpha1=ALPHA1,
                p_material_id=1,
                mz_material_id=1,
            )
        ],
    )
    mw._vm._project = project  # direct load: the tests need no undo history here
    mw._vm.projectChanged.emit(project)
    canvas = mw._canvas
    canvas.render()
    mid = canvas._project_world_to_screen(np.array([[0.0, 0.15, 0.0]]), canvas.renderer)
    assert mid is not None and len(mid) == 1
    dpr = float(canvas.devicePixelRatioF())
    qt_x, qt_y = mid[0][0] / dpr, canvas.height() - mid[0][1] / dpr
    assert canvas.frame_element_at(qt_x, qt_y) == 5
    assert canvas.frame_element_at(qt_x + 500.0, qt_y + 500.0) is None
    seen: list[tuple[str, str]] = []
    canvas.element_tooltip = lambda eid: f"bearing {eid}" if eid == 5 else None
    from PySide6.QtWidgets import QToolTip

    original = QToolTip.showText
    QToolTip.showText = staticmethod(lambda pos, text, *a: seen.append(("show", text)))  # type: ignore[method-assign]
    try:
        canvas._update_element_tooltip(qt_x, qt_y)
        canvas._update_element_tooltip(qt_x, qt_y)  # same element: shown once
        canvas._update_element_tooltip(qt_x + 500.0, qt_y + 500.0)
    finally:
        QToolTip.showText = original  # type: ignore[method-assign]
    assert seen == [("show", "bearing 5")]
    assert canvas._tooltip_element is None
