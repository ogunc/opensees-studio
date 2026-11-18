"""The OpenSees-coverage dialogs from the window: series, support motion, links, shells,
RC templates, custom commands (with the trust prompt) and the transient integrator rows."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QMessageBox

from opensees_studio.commands import AddMaterialsCommand, AddNodesCommand, AddTimeSeriesCommand
from opensees_studio.core import (
    CoulombFriction,
    CustomCommandBlock,
    ElasticIsotropic,
    ElasticUniaxial,
    LinearTimeSeries,
    Node,
    PlateFiberMaterial,
    TransientCase,
)
from opensees_studio.services.persistence import save_project


def _window(qtbot, ndm=3, ndf=6):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=ndm, ndf=ndf)
    return mw


def _accept(monkeypatch, cls, fill=None):  # type: ignore[no-untyped-def]
    def _exec(self) -> int:  # type: ignore[no-untyped-def]
        if fill is not None:
            fill(self)
        return 1

    monkeypatch.setattr(cls, "exec", _exec)


@pytest.mark.gui
def test_add_a_pulse_series(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.function_time_series import FunctionTimeSeriesDialog

    mw = _window(qtbot)

    def fill(d: FunctionTimeSeriesDialog) -> None:
        d.type_combo.setCurrentText("Pulse")
        d.fields["period"].setValue(2.0)

    _accept(monkeypatch, FunctionTimeSeriesDialog, fill)
    mw._on_add_function_ts()
    (ts,) = mw._vm.project.time_series
    assert (ts.type, ts.period, ts.width) == ("Pulse", 2.0, 0.5)


@pytest.mark.gui
def test_multi_support_motion_needs_restrained_supports(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.uniform_excitation import MultiSupportExcitationDialog

    mw = _window(qtbot)
    vm = mw._vm
    vm.apply_command(
        AddNodesCommand(
            vm,
            [
                Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
                Node(id=2, coords=(5.0, 0.0, 0.0)),
            ],
        )
    )
    vm.apply_command(AddTimeSeriesCommand(vm, LinearTimeSeries(id=1)))
    d = MultiSupportExcitationDialog(vm.project, 1, [1, 2])
    qtbot.addWidget(d)
    with pytest.raises(ValueError, match=r"\[2\]"):
        d.pattern()
    mw._canvas.selection.set_selection({1}, set())
    _accept(monkeypatch, MultiSupportExcitationDialog)
    mw._on_add_multi_support()
    (pattern,) = vm.project.load_patterns
    assert (pattern.type, pattern.node_ids) == ("ImposedSupportMotion", [1])


@pytest.mark.gui
def test_link_dialog_builds_a_two_node_link_and_a_tfp(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.assign_link import AssignLinkDialog

    mw = _window(qtbot)
    vm = mw._vm
    vm.apply_command(AddNodesCommand(vm, [Node(id=i, coords=(0.0, 0.0, 0.0)) for i in (1, 2)]))
    vm.apply_command(AddMaterialsCommand(vm, [ElasticUniaxial(id=1, E=1.0)]))
    vm.project.friction_models.append(CoulombFriction(id=1, mu=0.05))
    mw._canvas.selection.set_selection({1, 2}, set())
    mw._refresh_action_enablement()
    assert mw._act_assign_link.isEnabled()
    _accept(monkeypatch, AssignLinkDialog)
    mw._on_assign_link()
    link = vm.project.elements[-1]
    assert (link.type, link.dirs, link.orient) == (
        "TwoNodeLink",
        (1,),
        (0.0, 0.0, 1.0, 1.0, 0.0, 0.0),
    )

    d = AssignLinkDialog(vm.project, (1, 2))
    qtbot.addWidget(d)
    d.kind.setCurrentIndex(d.kind.findData("TripleFrictionPendulum"))
    assert d.build_element(9).type == "TripleFrictionPendulum"


@pytest.mark.gui
def test_shell_section_forms_list_plate_materials(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.section_forms import FORM_REGISTRY, make_form

    mw = _window(qtbot)
    project = mw._vm.project
    project.materials += [
        ElasticIsotropic(id=1, E=3e10, nu=0.2),
        PlateFiberMaterial(id=2, material_id=1),
    ]
    form = make_form(FORM_REGISTRY["LayeredShell"], project)
    qtbot.addWidget(form)
    form._section_id = 4
    section = form.read()
    assert [layer.material_id for layer in section.layers] == [2, 2, 2]
    assert section.h == pytest.approx(0.2)


@pytest.mark.gui
def test_rc_template_fills_the_fibre_editor(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.section_editor import FiberSectionEditor

    editor = FiberSectionEditor([1, 2, 3])
    qtbot.addWidget(editor)
    editor._rc_side.setValue(0)
    editor._on_add_rc()
    assert len(editor._patches) == 5 and sum(lay.n_bars for lay in editor._layers) == 6
    editor._rc_kind.setCurrentIndex(1)
    editor._on_add_rc()
    assert len(editor._patches) == 7


@pytest.mark.gui
def test_custom_commands_dialog_and_the_trust_prompt(qtbot, monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.custom_commands import CustomCommandsDialog

    mw = _window(qtbot)

    def fill(d: CustomCommandsDialog) -> None:
        d._on_add()
        d.code.setPlainText("def broken(:\n")
        with pytest.raises(SyntaxError):
            d.blocks()
        d.code.setPlainText("x = tag + 1\n")

    _accept(monkeypatch, CustomCommandsDialog, fill)
    mw._on_custom_commands()
    (block,) = mw._vm.project.custom_commands
    assert block.enabled and block.code == "x = tag + 1\n"

    path = tmp_path / "custom.osmodel"
    project = mw._vm.project.model_copy(deep=True)
    project.custom_commands = [CustomCommandBlock(id=1, name="foreign", code="pass")]
    save_project(project, path)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.No)
    mw.open_project(path)
    assert [b.enabled for b in mw._vm.project.custom_commands] == [False]


@pytest.mark.gui
def test_transient_integrator_rows_follow_the_integrator(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.case_forms import TransientCaseForm

    form = TransientCaseForm([], [])
    qtbot.addWidget(form)
    form._integrator.setCurrentText("GeneralizedAlpha")
    assert (form._gamma.value(), form._beta.value()) == (1.0, 0.8)
    assert "αM" in form._layout.labelForField(form._gamma).text()
    form._integrator.setCurrentText("TRBDF2")
    assert form._gamma.isHidden() and form._beta.isHidden()
    form.populate(
        TransientCase(
            id=1,
            name="t",
            pattern_ids=[1],
            dt=0.01,
            n_steps=1,
            integrator="HHT",
            integrator_params=(0.9, 0.25),
        )
    )
    assert form._gamma.value() == 0.9  # populate keeps the stored values
