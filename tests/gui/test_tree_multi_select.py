"""Model Tree supports Ctrl+click multi-selection — regression guard."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QTreeWidget  # noqa: E402

from opensees_studio.core import Node  # noqa: E402


@pytest.mark.gui
def test_tree_is_in_extended_selection_mode(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Default QTreeWidget is single-select; we need ExtendedSelection."""
    from opensees_studio.views.main_window import MainWindow
    mw = MainWindow()
    qtbot.addWidget(mw)
    assert mw._tree.selectionMode() == QTreeWidget.SelectionMode.ExtendedSelection


@pytest.mark.gui
def test_tree_multi_select_syncs_canvas(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Selecting two node rows in the tree must populate the canvas
    selection with both ids — the precondition for the Zero-Length
    Section dialog (exactly 2 joints)."""
    from opensees_studio.views.main_window import MainWindow
    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=2, ndf=3)
    mw._vm.project.nodes.extend([
        Node(id=1, coords=(0, 0, 0)),
        Node(id=2, coords=(0, 0, 0)),
        Node(id=3, coords=(1, 0, 0)),
    ])
    mw._refresh_tree(mw._vm.project)

    nodes_cat = mw._tree_categories["Nodes"]
    nodes_cat.setExpanded(True)
    # Find the three child items and select rows 0 + 1.
    items = [nodes_cat.child(i) for i in range(nodes_cat.childCount())]
    assert len(items) == 3
    items[0].setSelected(True)
    items[1].setSelected(True)

    assert mw._canvas.selection.nodes == frozenset({1, 2})
    assert mw._canvas.selection.elements == frozenset()

    # Adding a third selection (row 2) keeps all three.
    items[2].setSelected(True)
    assert mw._canvas.selection.nodes == frozenset({1, 2, 3})

    # Deselecting row 0 leaves rows 1 + 2.
    items[0].setSelected(False)
    assert mw._canvas.selection.nodes == frozenset({2, 3})
