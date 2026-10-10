"""The portal frame wizard, from the menu down to the model.

The geometry itself is pinned in ``tests/unit/test_frames.py``; what is checked
here is the wiring: that the fields reach the core builder, that the frame
arrives as one undoable step, that a project without sections still works, and
that the frame comes out selected so the next step — copying it — is one
keystroke away.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog, QMessageBox

from opensees_studio.commands import AddNodesCommand, AddSectionsCommand
from opensees_studio.core import (
    ElasticMembranePlateSection,
    ElasticSection,
    Node,
    RoofType,
    SupportCondition,
)
from opensees_studio.views.dialogs import FrameWizard
from opensees_studio.views.dialogs.replicate import ReplicateDialog


def _section(sid: int, name: str = "S") -> ElasticSection:
    return ElasticSection(id=sid, name=name, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6)


def _window(qtbot, *, ndm: int = 3, ndf: int = 6, sections: bool = True):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=ndm, ndf=ndf)
    if sections:
        mw._vm.apply_command(AddSectionsCommand(mw._vm, [_section(1, "Col"), _section(2, "Beam")]))
    return mw


def _accept_wizard(monkeypatch, **fields: object):  # type: ignore[no-untyped-def]
    """Fill the wizard the way a user would and press Finish."""

    def _fake_exec(self: FrameWizard) -> int:
        for name, value in fields.items():
            if name.endswith("_index"):  # a combo: pick an entry, not a value
                getattr(self, name.removesuffix("_index")).setCurrentIndex(value)
                continue
            widget = getattr(self, name)
            widget.setValue(value)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(FrameWizard, "exec", _fake_exec)


# ──────────────────────────── the dialog ────────────────────────────
@pytest.mark.gui
def test_the_defaults_are_a_one_bay_gable_portal(qtbot) -> None:  # type: ignore[no-untyped-def]
    wizard = FrameWizard([_section(3), _section(4)], ndm=3, ndf=6)
    qtbot.addWidget(wizard)

    spec = wizard.spec(column_section_id=3, rafter_section_id=4)
    assert (spec.n_bays, spec.bay_width, spec.eave_height) == (1, 6.0, 4.0)
    assert spec.roof is RoofType.GABLE
    assert spec.slope == pytest.approx(0.10)
    assert spec.support is SupportCondition.FIXED
    assert spec.plane == "XZ"
    assert spec.restrain_out_of_plane is True
    assert (spec.column_section_id, spec.rafter_section_id) == (3, 4)


@pytest.mark.gui
def test_an_empty_section_list_asks_the_caller_for_the_default(qtbot) -> None:  # type: ignore[no-untyped-def]
    wizard = FrameWizard([], ndm=3, ndf=6)
    qtbot.addWidget(wizard)

    assert wizard.section_choice() == (None, None)


@pytest.mark.gui
def test_the_flat_choice_forces_a_zero_slope(qtbot) -> None:  # type: ignore[no-untyped-def]
    wizard = FrameWizard([], ndm=3, ndf=6)
    qtbot.addWidget(wizard)
    wizard._slope.setValue(25.0)
    wizard._roof.setCurrentIndex(2)  # "Flat (no slope)"

    spec = wizard.spec(column_section_id=1, rafter_section_id=1)
    assert spec.roof is RoofType.MONO_PITCH
    assert spec.slope == 0.0
    assert spec.ridge_height == pytest.approx(spec.eave_height)


@pytest.mark.gui
def test_a_2d_project_is_locked_to_the_xy_plane(qtbot) -> None:  # type: ignore[no-untyped-def]
    wizard = FrameWizard([], ndm=2, ndf=3)
    qtbot.addWidget(wizard)

    assert not wizard._plane.isEnabled()
    assert wizard.spec(column_section_id=1, rafter_section_id=1).plane == "XY"
    assert not wizard._restrain_out_of_plane.isEnabled()


@pytest.mark.gui
def test_the_next_button_needs_numbers_that_describe_a_frame(qtbot) -> None:  # type: ignore[no-untyped-def]
    wizard = FrameWizard([], ndm=3, ndf=6)
    qtbot.addWidget(wizard)
    assert wizard.page(0).isComplete()

    wizard._bay_width.setValue(0.0)
    assert not wizard.page(0).isComplete()
    assert "bay width must be positive" in wizard._geometry_summary.text()

    wizard._bay_width.setValue(6.0)
    assert wizard.page(0).isComplete()


# ──────────────────── File → New 2D Frame ────────────────────
def _fresh_window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=3, ndf=6)  # something to replace, and clean (no prompt)
    return mw


@pytest.mark.gui
def test_new_2d_frame_opens_the_wizard_and_builds_in_the_xy_plane(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`New 2D Frame` is an empty canvas on its own: the wizard is the frame."""
    mw = _fresh_window(qtbot)
    _accept_wizard(monkeypatch, _n_bays=1, _bay_width=5.0, _eave_height=3.0)

    mw._act_new_2d.trigger()

    assert (mw._vm.project.ndm, mw._vm.project.ndf) == (2, 3)
    # ... and the grid it drew the frame on comes with it, in the same undo step.
    grids = [cs for cs in mw._vm.project.coord_systems if cs.name == "Portal Frame"]
    assert len(grids) == 1
    assert [line.ordinate for line in grids[0].grid.x_grid_lines] == [0.0, 2.5, 5.0]
    assert [line.ordinate for line in grids[0].grid.y_grid_lines] == [0.0, 3.0, 3.25]
    assert "Grid 'Portal Frame' created" in mw._console.toPlainText()
    # A 2D project has one plane, and the wizard uses it without asking.
    assert [node.coords for node in mw._vm.project.nodes] == [
        (0.0, 0.0, 0.0),
        (0.0, 3.0, 0.0),
        (5.0, 0.0, 0.0),
        (5.0, 3.0, 0.0),
        (2.5, 3.25, 0.0),
    ]
    assert len(mw._vm.project.elements) == 4
    assert "New 2D frame project" in mw._console.toPlainText()

    # Frame and grid are one undo step.
    mw._vm.undo_stack.undo()
    assert mw._vm.project.nodes == []
    assert [cs.name for cs in mw._vm.project.coord_systems] == ["Global"]


@pytest.mark.gui
def test_cancelling_the_wizard_leaves_the_empty_2d_project(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _fresh_window(qtbot)
    monkeypatch.setattr(FrameWizard, "exec", lambda self: int(QDialog.DialogCode.Rejected))

    mw._act_new_2d.trigger()

    assert (mw._vm.project.ndm, mw._vm.project.ndf) == (2, 3)
    assert mw._vm.project.nodes == []
    assert mw._vm.project.elements == []
    assert [cs.name for cs in mw._vm.project.coord_systems] == ["Global"]  # no stray grid


@pytest.mark.gui
def test_new_2d_frame_keeps_the_model_when_the_discard_is_refused(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._vm.apply_command(
        AddNodesCommand(
            mw._vm,
            [Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(1.0, 0.0, 0.0))],
        )
    )
    before = mw._vm.project.model_dump()
    monkeypatch.setattr(mw, "_confirm_discard_changes", lambda _action: False)
    monkeypatch.setattr(
        FrameWizard,
        "exec",
        lambda self: pytest.fail("the wizard must not open when the discard was refused"),
    )

    mw._act_new_2d.trigger()

    assert mw._vm.project.model_dump() == before  # the model the user chose to keep


# ──────────────────────────── through the menu ────────────────────────────
@pytest.mark.gui
def test_create_portal_frame_does_not_add_a_grid(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The grid belongs to `New 2D Frame`; Define → Create Portal Frame leaves
    the coordinate systems where they were."""
    mw = _window(qtbot)
    _accept_wizard(monkeypatch, _n_bays=1, _bay_width=6.0, _eave_height=4.0)

    mw._act_frame_wizard.trigger()

    assert len(mw._vm.project.nodes) == 5  # the frame is there...
    assert [cs.name for cs in mw._vm.project.coord_systems] == ["Global"]  # ...without a grid
    assert "Grid" not in mw._console.toPlainText()


@pytest.mark.gui
def test_the_menu_builds_the_frame_in_one_undo_step(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.StandardButton.Ok)
    _accept_wizard(
        monkeypatch,
        _n_bays=1,
        _bay_width=6.0,
        _eave_height=4.0,
        _rafter_section_index=1,  # "Beam", the second section
    )

    assert mw._act_frame_wizard.isEnabled()
    mw._act_frame_wizard.trigger()

    project = mw._vm.project
    assert [n.coords for n in project.nodes] == [
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 4.0),
        (6.0, 0.0, 0.0),
        (6.0, 0.0, 4.0),
        (3.0, 0.0, pytest.approx(4.3)),
    ]
    assert [el.nodes for el in project.elements] == [(1, 2), (3, 4), (2, 5), (5, 4)]
    assert {el.section_id for el in project.elements[:2]} == {1}  # columns
    assert {el.section_id for el in project.elements[2:]} == {2}  # rafters
    # The bases are fixed, the frame is a 2D one.
    assert project.nodes[0].restraint == (True,) * 6
    assert project.nodes[1].restraint == (False, True, False, True, False, True)

    # Everything is selected, ready for Replicate.
    assert mw._canvas.selection.nodes == {1, 2, 3, 4, 5}

    mw._vm.undo_stack.undo()
    assert project.nodes == [] and project.elements == []
    assert len(project.sections) == 2  # the user's own sections stay


@pytest.mark.gui
def test_a_project_without_sections_gets_the_default_one_inside_the_same_macro(
    qtbot,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot, sections=False)
    _accept_wizard(monkeypatch)

    mw._act_frame_wizard.trigger()

    project = mw._vm.project
    assert len(project.sections) == 1
    assert project.sections[0].name == "Default Section"
    assert {el.section_id for el in project.elements} == {project.sections[0].id}

    mw._vm.undo_stack.undo()
    assert project.nodes == [] and project.elements == [] and project.sections == []


@pytest.mark.gui
def test_a_truss_project_is_refused_with_an_explanation(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot, ndm=2, ndf=2, sections=False)
    seen: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda _p, _t, text, *a, **k: seen.append(text))

    mw._act_frame_wizard.trigger()

    assert mw._vm.project.nodes == []
    assert seen and "ndm = 2, ndf = 2" in seen[0]


@pytest.mark.gui
def test_a_2d_project_gets_a_frame_in_the_xy_plane(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot, ndm=2, ndf=3)
    _accept_wizard(monkeypatch)

    mw._act_frame_wizard.trigger()

    project = mw._vm.project
    assert [n.coords for n in project.nodes[:2]] == [(0.0, 0.0, 0.0), (0.0, 4.0, 0.0)]
    # (ndm, ndf) = (2, 3): Ux, Uy and Rz live at positions 0, 1 and 5.
    assert project.nodes[0].restraint == (True, True, False, False, False, True)
    assert project.nodes[1].restraint == (False, False, False, False, False, False)


@pytest.mark.gui
def test_plate_sections_are_not_offered_for_the_members(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._vm.apply_command(
        AddSectionsCommand(
            mw._vm,
            [ElasticMembranePlateSection(id=9, name="Slab", E=30e9, nu=0.2, h=0.2, rho=2500.0)],
        )
    )
    seen: list[list[str]] = []

    def _fake_exec(self: FrameWizard) -> int:
        seen.append([s.name for s in self._sections])
        return int(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(FrameWizard, "exec", _fake_exec)
    mw._act_frame_wizard.trigger()

    assert seen == [["Col", "Beam"]]  # the plate section is not a frame member


@pytest.mark.gui
def test_the_frame_can_be_replicated_along_the_ridge_direction(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The workflow the wizard exists for: build one portal, copy it in 3D."""
    mw = _window(qtbot)
    _accept_wizard(monkeypatch)
    mw._act_frame_wizard.trigger()

    def _fake_replicate(self: ReplicateDialog) -> int:
        self._dy.setValue(5.0)
        self._dz.setValue(0.0)  # the dialog starts at dz = 3
        self._n.setValue(2)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(ReplicateDialog, "exec", _fake_replicate)
    mw._act_replicate.trigger()

    project = mw._vm.project
    assert len(project.nodes) == 15  # 5 + 2 copies of 5
    assert len(project.elements) == 12  # 4 + 2 copies of 4
    copies = [tuple(n.coords) for n in project.nodes]
    assert (6.0, 5.0, 4.0) in copies  # first copy: the far column top
    assert (6.0, 10.0, 4.0) in copies  # second copy

    mw._vm.undo_stack.undo()
    assert len(project.nodes) == 5 and len(project.elements) == 4
