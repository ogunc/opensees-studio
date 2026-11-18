"""Storeys, mass source, rigid diaphragms and rigid links in the GUI; the Storeys results tab."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from opensees_studio.commands import (
    AddElementsCommand,
    AddNodesCommand,
    AddSectionsCommand,
    DeleteNodesCommand,
    SetStoreysCommand,
)
from opensees_studio.core import (
    CoordinateGridSystem,
    ElasticBeamColumn,
    ElasticSection,
    GridSystem,
    LinearTimeSeries,
    MassSource,
    MassSourcePattern,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    RigidDiaphragm,
    Storey,
    make_grid_lines,
)
from opensees_studio.views.dialogs.buildings import (
    AssignDiaphragmDialog,
    AssignRigidLinkDialog,
    MassSourceDialog,
    StoreysDialog,
)

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "building_3storey_diaphragm.osmodel"
CORNERS = [(0.0, 0.0), (6.0, 0.0), (6.0, 4.0), (0.0, 4.0)]


def _floor_nodes() -> list[Node]:
    nodes = [
        Node(id=i + 1, coords=(x, y, 0.0), restraint=(True,) * 6)
        for i, (x, y) in enumerate(CORNERS)
    ]
    nodes += [Node(id=i + 5, coords=(x, y, 3.0)) for i, (x, y) in enumerate(CORNERS)]
    return nodes


def _floor_project() -> Project:
    return Project(
        storeys=[Storey(id=1, name="Story1", elevation=3.0)],
        nodes=_floor_nodes(),
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="DEAD",
                time_series_id=1,
                self_weight=1.0,
                nodal_loads=[
                    NodalLoad(node_id=n, forces=(0.0, 0.0, -9806.65 * w, 0.0, 0.0, 0.0))
                    for n, w in ((5, 1.0), (6, 3.0), (7, 3.0), (8, 1.0))
                ],
            )
        ],
        mass_source=MassSource(element_self_mass=False, patterns=[MassSourcePattern(pattern_id=1)]),
    )


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    return mw


def _floor_in_window(mw) -> None:  # type: ignore[no-untyped-def]
    vm = mw._vm
    vm.new_project(ndm=3, ndf=6)
    vm.apply_command(AddNodesCommand(vm, _floor_nodes()))
    vm.apply_command(AddSectionsCommand(vm, [ElasticSection(id=1, E=1, A=1, Iz=1, Iy=1, G=1, J=1)]))
    vm.apply_command(
        AddElementsCommand(
            vm,
            [ElasticBeamColumn(id=i + 1, nodes=(i + 1, i + 5), section_id=1) for i in range(4)]
            + [
                ElasticBeamColumn(id=5 + k, nodes=pair, section_id=1)
                for k, pair in enumerate([(5, 6), (6, 7), (7, 8), (8, 5)])
            ],
        )
    )
    vm.apply_command(SetStoreysCommand(vm, [Storey(id=1, name="Story1", elevation=3.0)]))


def _accept(monkeypatch, cls) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(cls, "exec", lambda self: int(QDialog.DialogCode.Accepted))


# ─────────────────────────── dialogs ───────────────────────────
@pytest.mark.gui
def test_storeys_dialog_fills_from_the_z_grid_lines(qtbot) -> None:  # type: ignore[no-untyped-def]
    grid = CoordinateGridSystem(
        name="Global", grid=GridSystem(z_grid_lines=make_grid_lines("Z", [0.0, 3.5, 7.0]))
    )
    dialog = StoreysDialog(Project(coord_systems=[grid]))
    qtbot.addWidget(dialog)
    dialog.from_grid_button.click()
    assert [(s.name, s.elevation) for s in dialog.storeys()] == [("Story1", 3.5), ("Story2", 7.0)]

    dialog.add_button.click()
    assert dialog.storeys()[-1].elevation == 10.0
    dialog.table.item(2, 1).setText("seven")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "not a number" in dialog.message.text()


@pytest.mark.gui
def test_mass_source_dialog_reads_the_patterns_and_warns_about_double_weight(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = MassSourceDialog(_floor_project())
    qtbot.addWidget(dialog)
    source = dialog.mass_source()
    assert source is not None
    assert [(e.pattern_id, e.factor) for e in source.patterns] == [(1, 1.0)]
    assert "Total mass: X 8000" in dialog.total.text()

    dialog.self_mass.setChecked(True)  # DEAD carries self weight too
    assert dialog.message.level == "warning"
    dialog.patterns.item(0, 1).setText("0.3")
    assert dialog.mass_source().patterns[0].factor == 0.3
    dialog.patterns.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert dialog.mass_source().patterns == []
    dialog.group.setChecked(False)
    assert dialog.mass_source() is None


@pytest.mark.gui
def test_diaphragm_dialog_places_a_new_node_at_the_centre_of_mass(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = AssignDiaphragmDialog(_floor_project(), [])
    qtbot.addWidget(dialog)
    assert dialog.by_storey.isChecked()
    diaphragm, node = dialog.diaphragm()
    assert node is not None and node.id == 9
    # Masses 1, 3, 3, 1 t at x = 0, 6, 6, 0: x = 4.5; y = (0*4 + 4*4) / 8 = 2.
    assert node.coords == pytest.approx((4.5, 2.0, 3.0))
    assert (diaphragm.retained_node, diaphragm.storey_id, diaphragm.perp_dirn) == (9, 1, 3)


@pytest.mark.gui
def test_diaphragm_dialog_on_selected_joints_with_an_existing_retained_node(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = AssignDiaphragmDialog(_floor_project(), [5, 6, 7])
    qtbot.addWidget(dialog)
    dialog.by_selection.setChecked(True)
    dialog.retained_existing.setChecked(True)
    diaphragm, node = dialog.diaphragm()
    assert node is None
    assert (diaphragm.retained_node, diaphragm.constrained_nodes) == (5, (6, 7))


@pytest.mark.gui
def test_diaphragm_dialog_refuses_a_joint_out_of_the_plane(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = AssignDiaphragmDialog(_floor_project(), [1, 5, 6])
    qtbot.addWidget(dialog)
    dialog.by_selection.setChecked(True)
    dialog.retained_existing.setChecked(True)  # node 1 is on the ground
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "not in the plane" in dialog.message.text()


@pytest.mark.gui
def test_rigid_link_dialog(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = AssignRigidLinkDialog([3, 8])
    qtbot.addWidget(dialog)
    dialog.kind.setCurrentIndex(1)
    link = dialog.link()
    assert (link.kind, link.retained_node, link.constrained_node) == ("bar", 3, 8)


# ─────────────────────────── main window ───────────────────────────
@pytest.mark.gui
def test_assign_diaphragm_from_the_menu_is_undoable_and_drawn(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    _floor_in_window(mw)
    _accept(monkeypatch, AssignDiaphragmDialog)
    mw._refresh_action_enablement()
    assert mw._act_assign_diaphragm.isEnabled()
    mw._act_assign_diaphragm.trigger()

    project = mw._vm.project
    (diaphragm,) = project.diaphragms
    assert diaphragm.storey_id == 1
    assert project.node(diaphragm.retained_node).coords == pytest.approx((3.0, 2.0, 3.0))
    assert mw._canvas._renderer.DIAPHRAGM_ACTOR in mw._canvas.actors
    assert mw._canvas._renderer.RETAINED_ACTOR in mw._canvas.actors

    mw._vm.undo_stack.undo()
    assert project.diaphragms == []
    assert len(project.nodes) == 8


@pytest.mark.gui
def test_rigid_link_remove_constraints_and_delete_cascade(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    _floor_in_window(mw)
    project = mw._vm.project
    vm = mw._vm
    vm.apply_command(AddNodesCommand(vm, [Node(id=9, coords=(3.0, 2.0, 3.0))]))
    project.diaphragms.append(RigidDiaphragm(id=1, retained_node=9, constrained_nodes=(5, 6, 7, 8)))

    _accept(monkeypatch, AssignRigidLinkDialog)
    mw._canvas.selection.set_selection({5, 7}, set())
    mw._act_assign_rigid_link.trigger()
    assert [(k.retained_node, k.constrained_node) for k in project.rigid_links] == [(5, 7)]
    assert mw._canvas._renderer.RIGID_LINK_ACTOR in mw._canvas.actors

    # Remove Constraints on node 7: the link goes, node 7 leaves the diaphragm.
    mw._canvas.selection.set_selection({7}, set())
    mw._act_remove_constraints.trigger()
    assert project.rigid_links == []
    assert project.diaphragms[0].constrained_nodes == (5, 6, 8)
    vm.undo_stack.undo()
    assert len(project.rigid_links) == 1
    assert project.diaphragms[0].constrained_nodes == (5, 6, 7, 8)

    # Deleting the retained node deletes the diaphragm; undo brings both back.
    vm.apply_command(DeleteNodesCommand(vm, {9}))
    assert project.diaphragms == []
    vm.apply_command(DeleteNodesCommand(vm, {5}))
    assert project.rigid_links == []
    vm.undo_stack.undo()
    vm.undo_stack.undo()
    assert len(project.diaphragms) == 1 and len(project.rigid_links) == 1


@pytest.mark.gui
def test_define_storeys_and_mass_source_from_the_menu(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    _floor_in_window(mw)
    project = mw._vm.project

    _accept(monkeypatch, StoreysDialog)
    monkeypatch.setattr(
        StoreysDialog,
        "storeys",
        lambda self: [
            Storey(id=1, name="L1", elevation=3.0),
            Storey(id=2, name="L2", elevation=6.0),
        ],
    )
    mw._act_storeys.trigger()
    assert [s.name for s in project.storeys] == ["L1", "L2"]

    _accept(monkeypatch, MassSourceDialog)
    monkeypatch.setattr(MassSourceDialog, "mass_source", lambda self: MassSource())
    mw._act_mass_source.trigger()
    assert project.mass_source is not None and project.mass_source.element_self_mass
    mw._vm.undo_stack.undo()
    assert project.mass_source is None


@pytest.mark.gui
def test_duplicates_check_leaves_a_retained_node_on_a_joint_alone(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core.duplicates import find_node_clusters

    project = _floor_project()
    project.nodes.append(Node(id=9, coords=(6.0, 0.0, 3.0)))  # on top of joint 6
    project.diaphragms.append(RigidDiaphragm(id=1, retained_node=9, constrained_nodes=(5, 7, 8)))
    mergeable, exempt = find_node_clusters(project)
    assert mergeable == []
    assert [list(c.ids) for c in exempt] == [[6, 9]]


# ─────────────────────────── results ───────────────────────────
@pytest.mark.gui
def test_results_panel_shows_a_storeys_tab(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.services import load_project
    from opensees_studio.services.results import StaticResults
    from opensees_studio.views.docks.results_panel import ResultsPanel

    project = load_project(EXAMPLE)
    disp = {n.id: np.zeros((1, 6)) for n in project.nodes}
    for k, nid in enumerate((37, 38, 39)):
        disp[nid][0, 0] = 0.01 * (k + 1)
    results = StaticResults(
        case_id=2,
        case_name="EQX",
        n_steps=1,
        node_disp=disp,
        node_reaction={n.id: np.zeros((1, 6)) for n in project.nodes},
        storey_shear={s.id: np.array([[1000.0 * s.id, 0.0, 0.0]]) for s in project.storeys},
    )
    panel = ResultsPanel()
    qtbot.addWidget(panel)
    panel.show_results(results, project)
    names = [panel._tabs.tabText(i) for i in range(panel._tabs.count())]
    assert names[-1] == "Storeys"
    panel._tabs.setCurrentIndex(len(names) - 1)
    (table,) = panel.tables()
    assert [row[0] for row in table.rows] == ["Story3", "Story2", "Story1", "Base"]
    assert table.rows[0][3] == pytest.approx(0.03)
    assert table.rows[0][5] == pytest.approx(0.01 / 3.5)
    assert table.rows[0][7] == 3000.0
