"""Assign → Frame → Releases / End Offsets / Insertion Point / Property Modifiers / Trapezoidal Load.

The solved numbers are pinned in ``tests/integration/test_frame_member_options.py``;
here the wiring: the menu actions, the dialogs' validation, undo, the
Properties dock, and that meshing keeps releases at the member's ends and
splits a trapezoidal load over the pieces.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog, QMessageBox

from opensees_studio.commands import (
    AddElementsCommand,
    AddNodesCommand,
    AddSectionsCommand,
    AddTrapezoidalElementLoadsCommand,
    MeshCommand,
)
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    EndRelease,
    FrameEndOffsets,
    FrameInsertion,
    FrameModifiers,
    FrameReleases,
    Node,
    PlainLoadPattern,
    TrapezoidalElementLoad,
    TrussElement,
)
from opensees_studio.core.help import ACTION_TOPICS, TOPICS
from opensees_studio.core.mesh import mesh_bars
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs import (
    FrameEndOffsetsDialog,
    FrameInsertionDialog,
    FrameModifiersDialog,
    FrameReleasesDialog,
    TrapezoidalLoadDialog,
)

LENGTH = 10.0


def _populate(vm: ProjectViewModel, ndm: int = 2) -> None:
    vm.new_project(ndm=ndm, ndf=3 if ndm == 2 else 6)
    vm.apply_command(
        AddNodesCommand(
            vm,
            [
                Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
                Node(id=2, coords=(LENGTH, 0.0, 0.0), restraint=(True,) * 6),
                Node(id=3, coords=(0.0, 0.0, 4.0)),  # Z up (a 2D model is the X-Z plane)
            ],
        )
    )
    vm.apply_command(
        AddSectionsCommand(
            vm, [ElasticSection(id=1, E=2e8, A=0.01, Iz=1e-4, Iy=1e-4, G=8e7, J=1e-4)]
        )
    )
    vm.apply_command(
        AddElementsCommand(
            vm,
            [
                ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
                TrussElement(id=2, nodes=(1, 3), area=1.0, material_id=1),
            ],
        )
    )


def _window(qtbot, ndm: int = 2):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    _populate(mw._vm, ndm)
    mw._canvas.selection.set_selection(set(), {1, 2})
    mw._refresh_action_enablement()
    return mw


def _accept_with(monkeypatch, cls, fill):  # type: ignore[no-untyped-def]
    def _fake_exec(self) -> int:  # type: ignore[no-untyped-def]
        fill(self)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(cls, "exec", _fake_exec)


def _distributed(vm: ProjectViewModel) -> list[TrapezoidalElementLoad]:
    return [
        load
        for pattern in vm.project.load_patterns
        if isinstance(pattern, PlainLoadPattern)
        for load in pattern.distributed_loads
    ]


# ──────────────────────────── menu actions ────────────────────────────
@pytest.mark.gui
def test_releases_from_the_menu_and_undo(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    assert mw._act_assign_releases.isEnabled()
    _accept_with(
        monkeypatch,
        FrameReleasesDialog,
        lambda d: d.set_release("j", "M3", True, spring=50.0),
    )

    mw._act_assign_releases.trigger()

    expected = FrameReleases(j=EndRelease(released=("M3",), springs={"M3": 50.0}))
    assert mw._vm.project.element(1).releases == expected
    mw._vm.undo_stack.undo()
    assert mw._vm.project.element(1).releases == FrameReleases()


@pytest.mark.gui
def test_a_2d_frame_offers_only_m3(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = FrameReleasesDialog(1, ndm=2)
    qtbot.addWidget(dialog)
    assert not dialog._release[("i", "T")].isEnabled()
    assert not dialog._release[("i", "M2")].isEnabled()
    assert dialog._release[("i", "M3")].isEnabled()


@pytest.mark.gui
def test_torsion_at_both_ends_is_refused_in_the_dialog(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    dialog = FrameReleasesDialog(1, ndm=3)
    qtbot.addWidget(dialog)
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    dialog.set_release("i", "T", True)
    dialog.set_release("j", "T", True)

    dialog._on_accept()

    assert shown and "spin" in shown[0]
    assert dialog.result() != QDialog.DialogCode.Accepted


@pytest.mark.gui
def test_end_offsets_insertion_and_modifiers_from_the_menu(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)

    def _offsets(d: FrameEndOffsetsDialog) -> None:
        d._length_i.setValue(0.3)
        d._factor.setValue(0.5)

    _accept_with(monkeypatch, FrameEndOffsetsDialog, _offsets)
    _accept_with(monkeypatch, FrameInsertionDialog, lambda d: d.set_cardinal_point(8))
    _accept_with(monkeypatch, FrameModifiersDialog, lambda d: d.set_value("i33", 0.35))

    mw._act_assign_end_offsets.trigger()
    mw._act_assign_insertion.trigger()
    mw._act_assign_modifiers.trigger()

    beam = mw._vm.project.element(1)
    assert beam.end_offsets == FrameEndOffsets(length_i=0.3, rigid_factor=0.5)
    assert beam.insertion == FrameInsertion(cardinal_point=8)
    assert beam.modifiers == FrameModifiers(i33=0.35)
    # The truss in the selection is left alone.
    assert "end_offsets" not in type(mw._vm.project.element(2)).model_fields


@pytest.mark.gui
def test_automatic_end_offsets_come_from_the_framing_members(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    vm = mw._vm
    # Joint 1 meets a truss, not a frame: the beam gets no offset; add a 0.5 m column on joint 2.
    vm.apply_command(AddNodesCommand(vm, [Node(id=4, coords=(LENGTH, 0.0, 3.0))]))
    vm.apply_command(
        AddSectionsCommand(
            vm,
            [ElasticSection(id=2, E=2e8, A=0.25, Iz=0.25**2 / 12, Iy=0.25**2 / 12, G=8e7, J=1e-3)],
        )
    )
    vm.apply_command(AddElementsCommand(vm, [ElasticBeamColumn(id=5, nodes=(2, 4), section_id=2)]))
    mw._canvas.selection.set_selection(set(), {1})
    mw._refresh_action_enablement()

    def _fill(d: FrameEndOffsetsDialog) -> None:
        d.set_automatic(True)
        d._factor.setValue(0.75)

    _accept_with(monkeypatch, FrameEndOffsetsDialog, _fill)
    mw._act_assign_end_offsets.trigger()
    offsets = vm.project.element(1).end_offsets
    assert offsets.length_i == 0.0
    assert offsets.length_j == pytest.approx(0.25)
    assert offsets.rigid_factor == 0.75
    vm.undo_stack.undo()
    assert vm.project.element(1).end_offsets == FrameEndOffsets()


@pytest.mark.gui
def test_a_trapezoidal_load_from_the_menu(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)

    def _fill(d: TrapezoidalLoadDialog) -> None:
        d.set_load("wy", -1.0, -3.0)
        d.set_span(0.2, 0.8)

    _accept_with(monkeypatch, TrapezoidalLoadDialog, _fill)

    mw._act_assign_trapezoidal_load.trigger()

    assert _distributed(mw._vm) == [
        TrapezoidalElementLoad(element_id=1, x_start=0.2, x_end=0.8, wy_start=-1.0, wy_end=-3.0)
    ]
    mw._vm.undo_stack.undo()
    assert _distributed(mw._vm) == []


@pytest.mark.gui
def test_a_trapezoidal_load_needs_a_frame(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = ProjectViewModel()
    _populate(vm)
    command = AddTrapezoidalElementLoadsCommand(vm, {2}, {"wy_start": -1.0})
    with pytest.raises(ValueError, match="not one: 2"):
        command.redo()


@pytest.mark.gui
def test_every_new_action_has_help() -> None:
    for action in (
        "_act_assign_releases",
        "_act_assign_end_offsets",
        "_act_assign_insertion",
        "_act_assign_modifiers",
        "_act_assign_trapezoidal_load",
    ):
        assert ACTION_TOPICS[action] in TOPICS


# ──────────────────────────── properties dock ────────────────────────────
@pytest.mark.gui
def test_the_properties_dock_edits_the_offsets(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._canvas.selection.set_selection(set(), {1})
    props = mw._props
    props.update_for_selection(frozenset(), frozenset({1}))

    props._frame_offset_fields["length_j"].setValue(0.4)
    props._frame_offset_fields["length_j"].editingFinished.emit()

    assert mw._vm.project.element(1).end_offsets == FrameEndOffsets(length_j=0.4)

    props.update_for_selection(frozenset(), frozenset({1}))
    props._cardinal_point.setCurrentIndex(props._cardinal_point.findData(2))
    assert mw._vm.project.element(1).insertion.cardinal_point == 2


# ──────────────────────────── meshing ────────────────────────────
@pytest.mark.gui
def test_meshing_keeps_releases_at_the_ends_and_splits_the_load(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = ProjectViewModel()
    _populate(vm)
    releases = FrameReleases(i=EndRelease(released=("M3",)), j=EndRelease(released=("M3",)))
    vm.project.elements[0] = vm.project.element(1).model_copy(update={"releases": releases})
    vm.apply_command(
        AddTrapezoidalElementLoadsCommand(
            vm, {1}, {"x_start": 0.0, "x_end": 1.0, "wy_start": 0.0, "wy_end": -4.0}
        )
    )

    vm.apply_command(MeshCommand(vm, mesh_bars(vm.project, {1}, target_size=5.0)))

    pieces = sorted(
        (el for el in vm.project.elements if isinstance(el, ElasticBeamColumn)),
        key=lambda el: vm.project.node(el.nodes[0]).coords[0],
    )
    assert [p.releases.i.released for p in pieces] == [("M3",), ()]
    assert [p.releases.j.released for p in pieces] == [(), ("M3",)]
    loads = sorted(_distributed(vm), key=lambda load: load.wy_start, reverse=True)
    assert [(load.wy_start, load.wy_end) for load in loads] == [(0.0, -2.0), (-2.0, -4.0)]
    assert all((load.x_start, load.x_end) == (0.0, 1.0) for load in loads)
