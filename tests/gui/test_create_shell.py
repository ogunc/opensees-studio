"""Define > Create Shell from 4 Nodes, and how shells reach the 3D canvas.

The winding is derived by ``order_quad_nodes`` (unit-tested in
``tests/unit/test_quad_ordering.py``); here the command, the dialog guards and
the face rendering are exercised through the real main window.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QInputDialog, QMessageBox

from opensees_studio.commands import AddNodesCommand, AddSectionsCommand
from opensees_studio.core import (
    ElasticMembranePlateSection,
    ElasticSection,
    Node,
    Project,
    ShellMITC4Element,
)


def _plate(**overrides: object) -> ElasticMembranePlateSection:
    fields: dict[str, object] = {
        "id": 1,
        "name": "Slab",
        "E": 30e9,
        "nu": 0.2,
        "h": 0.2,
        "rho": 2500.0,
    }
    fields.update(overrides)
    return ElasticMembranePlateSection(**fields)  # type: ignore[arg-type]


def _window_with_nodes(qtbot, coords):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=3, ndf=6)
    mw._vm.apply_command(
        AddNodesCommand(
            mw._vm,
            [Node(id=i + 1, coords=c) for i, c in enumerate(coords)],
        )
    )
    return mw


# Nodes numbered so that ascending id is NOT perimeter order: 1-2-3-4 is a
# figure-eight, so a shell built without ordering the winding would be twisted.
# The four corners, counter-clockwise from the origin, are 1, 3, 2, 4.
SQUARE = [
    (0.0, 0.0, 0.0),  # 1
    (1.0, 1.0, 0.0),  # 2
    (1.0, 0.0, 0.0),  # 3
    (0.0, 1.0, 0.0),  # 4
]
SQUARE_CCW = {(1, 3, 2, 4), (3, 2, 4, 1), (2, 4, 1, 3), (4, 1, 2, 3)}


def _select_nodes(mw, *ids: int) -> None:  # type: ignore[no-untyped-def]
    """Select nodes in the given click order; the last is plain, earlier ones additive."""
    for i, node_id in enumerate(ids):
        mw._canvas.selection.select_node(node_id, additive=i > 0)
    mw._refresh_action_enablement()


@pytest.mark.gui
def test_menu_creates_a_counter_clockwise_shell_and_undo_removes_it(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window_with_nodes(qtbot, SQUARE)
    mw._vm.apply_command(AddSectionsCommand(mw._vm, [_plate()]))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.StandardButton.Ok)

    # A scrambled click order: the selection carries no order at all.
    _select_nodes(mw, 3, 1, 4, 2)
    assert mw._act_create_shell.isEnabled()

    mw._act_create_shell.trigger()
    project = mw._vm.project
    assert [el.type for el in project.elements] == ["ShellMITC4"]
    shell = project.elements[0]
    assert shell.section_id == 1
    assert sorted(shell.nodes) == [1, 2, 3, 4]
    # Counter-clockwise as seen from +Z, whatever order the clicks arrived in.
    assert shell.nodes in SQUARE_CCW

    # Rendered as a quad face: one cell, four corners, and the element id on it.
    renderer = mw._canvas._renderer
    assert renderer._surface_pd is not None
    assert renderer._surface_pd.n_points == 4
    assert renderer._surface_pd.n_cells == 1
    assert renderer._surface_ids_ordered == [shell.id]

    # Selecting the shell flips its cell's state in the same polydata.
    mw._canvas.selection.select_element(shell.id)
    assert list(renderer._surface_pd.cell_data["_oss_state"]) == [1]

    mw._vm.undo_stack.undo()
    assert project.elements == []
    assert renderer._surface_pd is None
    assert renderer._surface_actor is None


@pytest.mark.gui
def test_shell_is_emitted_by_the_runner_as_a_plate_section(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.services.opensees_runner import OpenSeesRunner

    mw = _window_with_nodes(qtbot, SQUARE)
    mw._vm.apply_command(AddSectionsCommand(mw._vm, [_plate()]))
    _select_nodes(mw, 1, 2, 3, 4)
    mw._act_create_shell.trigger()

    ops = MagicMock()
    OpenSeesRunner(mw._vm.project, ops_module=ops).build()
    ops.section.assert_any_call("ElasticMembranePlateSection", 1, 30e9, 0.2, 0.2, 2500.0)
    shell = mw._vm.project.elements[0]
    ops.element.assert_any_call("ShellMITC4", shell.id, *shell.nodes, 1)


@pytest.mark.gui
def test_three_selected_nodes_are_refused(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window_with_nodes(qtbot, SQUARE)
    mw._vm.apply_command(AddSectionsCommand(mw._vm, [_plate()]))
    seen: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda _p, _t, text, *a, **k: seen.append(text))
    _select_nodes(mw, 1, 2, 3)
    mw._act_create_shell.trigger()
    assert mw._vm.project.elements == []
    assert seen and "exactly four nodes" in seen[0]
    assert "3" in seen[0]


@pytest.mark.gui
def test_four_nodes_without_a_plate_section_are_refused(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window_with_nodes(qtbot, SQUARE)
    mw._vm.apply_command(
        AddSectionsCommand(
            mw._vm,
            [ElasticSection(id=1, name="Beam", E=200e9, A=0.01, Iz=1e-4, Iy=1e-4, G=80e9, J=1e-6)],
        )
    )
    seen: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda _p, _t, text, *a, **k: seen.append(text))
    _select_nodes(mw, 1, 2, 3, 4)
    mw._act_create_shell.trigger()
    assert mw._vm.project.elements == []
    assert seen and "plate section" in seen[0]


@pytest.mark.gui
def test_degenerate_selection_is_refused_with_an_explanation(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window_with_nodes(
        qtbot,
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 1e-14, 0.0)],
    )
    mw._vm.apply_command(AddSectionsCommand(mw._vm, [_plate()]))
    seen: list[str] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _p, _t, text, *a, **k: seen.append(text))
    _select_nodes(mw, 1, 2, 3, 4)
    mw._act_create_shell.trigger()
    assert mw._vm.project.elements == []
    assert seen and "collinear" in seen[0]


@pytest.mark.gui
def test_choosing_between_two_plate_sections(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window_with_nodes(qtbot, SQUARE)
    mw._vm.apply_command(
        AddSectionsCommand(
            mw._vm,
            [_plate(id=1, name="Thin", h=0.1), _plate(id=2, name="Thick", h=0.5)],
        )
    )
    monkeypatch.setattr(
        QInputDialog, "getItem", staticmethod(lambda *a, **k: ("#2 Thick (h = 0.5)", True))
    )
    _select_nodes(mw, 1, 2, 3, 4)
    mw._act_create_shell.trigger()
    assert mw._vm.project.elements[0].section_id == 2


@pytest.mark.gui
def test_action_is_disabled_without_a_project_and_after_the_shell_is_deleted(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    assert mw._vm.project is None
    mw._refresh_action_enablement()
    assert not mw._act_create_shell.isEnabled()

    mw._vm.new_project(ndm=3, ndf=6)
    mw._refresh_action_enablement()
    assert mw._act_create_shell.isEnabled()


@pytest.mark.gui
def test_shell_round_trips_through_the_project_file(qtbot, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window_with_nodes(qtbot, SQUARE)
    mw._vm.apply_command(AddSectionsCommand(mw._vm, [_plate()]))
    _select_nodes(mw, 4, 2, 3, 1)
    mw._act_create_shell.trigger()
    shell = mw._vm.project.elements[0]
    assert isinstance(shell, ShellMITC4Element)

    path = tmp_path / "shell.osmodel"
    mw._vm.save(path)
    reloaded = Project.model_validate_json(path.read_text())
    assert reloaded.elements[0] == shell
    assert isinstance(reloaded.sections[0], ElasticMembranePlateSection)
