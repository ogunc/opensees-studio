"""Assign → Area → Shell Formulation, and Create Shell from three nodes."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.core import (
    ElasticMembranePlateSection,
    Node,
    Project,
    ShellDKGQElement,
    ShellDKGTElement,
    ShellMITC4Element,
)

SQUARE = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0), (3.0, 1.0)]


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.adopt(
        Project(
            ndm=3,
            ndf=6,
            nodes=[Node(id=i, coords=(x, y, 0.0)) for i, (x, y) in enumerate(SQUARE, 1)],
            sections=[ElasticMembranePlateSection(id=1, E=30e9, nu=0.2, h=0.2)],
            elements=[ShellMITC4Element(id=1, nodes=(1, 2, 3, 4), section_id=1)],
        )
    )
    return window


@pytest.mark.gui
def test_the_formulation_changes_and_undoes(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QInputDialog

    window = _window(qtbot)
    window._canvas.selection.select_element(1)
    monkeypatch.setattr(
        QInputDialog,
        "getItem",
        lambda *a, **k: (a[3][1], True),  # the DKGQ / DKGT pair
    )
    window._on_shell_formulation()
    assert type(window._vm.project.elements[0]) is ShellDKGQElement
    window._vm.undo_stack.undo()
    assert type(window._vm.project.elements[0]) is ShellMITC4Element


@pytest.mark.gui
def test_three_selected_nodes_make_a_triangle(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(qtbot)
    for nid in (2, 5, 3):
        window._canvas.selection.select_node(nid, additive=True)
    window._on_create_shell()
    tri = window._vm.project.elements[-1]
    assert isinstance(tri, ShellDKGTElement)
    assert set(tri.nodes) == {2, 3, 5}
