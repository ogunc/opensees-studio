"""The project dock: tree, entity table and contextual help."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.commands import AddElementsCommand, AddNodesCommand
from opensees_studio.core import ElasticBeamColumn, ElasticSection, Node
from opensees_studio.views.main_window import MainWindow


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    win = MainWindow()
    qtbot.addWidget(win)
    win._vm.new_project(ndm=3, ndf=6)
    win._vm.apply_command(
        AddNodesCommand(
            win._vm,
            [Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(6.0, 0.0, 0.0))],
        )
    )
    win._vm.apply_command(
        AddSectionsCommand_stub(win),
    )
    win._vm.apply_command(
        AddElementsCommand(
            win._vm,
            [ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        )
    )
    return win


def AddSectionsCommand_stub(win: MainWindow):  # type: ignore[no-untyped-def]
    from opensees_studio.commands import AddSectionsCommand

    return AddSectionsCommand(
        win._vm,
        [ElasticSection(id=1, name="W12X40", E=200e9, A=0.0094, Iz=1.21e-4)],
    )


def test_the_dock_has_tree_edit_and_help(window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    tabs = window._project_dock._tabs

    assert [tabs.tabText(i) for i in range(tabs.count())] == ["Tree", "Edit", "Help"]


def test_the_tree_lists_the_categories_with_counts(window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    tree = window._project_dock._tree

    labels = {tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())}

    assert "Nudos" in labels
    assert "Elementos" in labels
    nodes = next(
        tree.topLevelItem(i)
        for i in range(tree.topLevelItemCount())
        if tree.topLevelItem(i).text(0) == "Nudos"
    )
    assert nodes.childCount() == 2


def test_the_edit_table_shows_the_selected_category(window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    dock = window._project_dock
    dock._select_category("nodes")

    assert dock._rows.rowCount() == 2
    assert dock._rows.item(0, 0).text() == "1"


def test_the_help_tab_shows_a_page(window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    dock = window._project_dock
    dock.show_topic("analyze.cases")

    assert "Analysis" in dock._help.toHtml() or "analysis" in dock._help.toHtml().lower()
