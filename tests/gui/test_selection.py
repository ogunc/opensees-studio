"""Unit tests for the SelectionState QObject."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.views.canvas3d import SelectionState  # noqa: E402


@pytest.mark.gui
def test_initial_state_is_empty(qtbot) -> None:  # type: ignore[no-untyped-def]
    s = SelectionState()
    assert s.is_empty
    assert s.nodes == frozenset()
    assert s.elements == frozenset()


@pytest.mark.gui
def test_select_node_emits_signal(qtbot) -> None:  # type: ignore[no-untyped-def]
    s = SelectionState()
    with qtbot.waitSignal(s.selectionChanged, timeout=500) as blocker:
        s.select_node(7)
    assert blocker.args[0] == frozenset({7})
    assert blocker.args[1] == frozenset()


@pytest.mark.gui
def test_replacing_selection_clears_other_kind(qtbot) -> None:  # type: ignore[no-untyped-def]
    s = SelectionState()
    s.select_node(1)
    s.select_element(5)
    assert s.nodes == frozenset()
    assert s.elements == frozenset({5})


@pytest.mark.gui
def test_additive_selection_keeps_both(qtbot) -> None:  # type: ignore[no-untyped-def]
    s = SelectionState()
    s.select_node(1)
    s.select_node(2, additive=True)
    assert s.nodes == frozenset({1, 2})


@pytest.mark.gui
def test_toggle_node(qtbot) -> None:  # type: ignore[no-untyped-def]
    s = SelectionState()
    s.toggle_node(3)
    assert 3 in s.nodes
    s.toggle_node(3)
    assert 3 not in s.nodes


@pytest.mark.gui
def test_clear_no_op_when_empty_does_not_emit(qtbot) -> None:  # type: ignore[no-untyped-def]
    s = SelectionState()
    received: list[tuple] = []
    s.selectionChanged.connect(lambda n, e: received.append((n, e)))
    s.clear()
    assert received == []


@pytest.mark.gui
def test_clear_emits_when_non_empty(qtbot) -> None:  # type: ignore[no-untyped-def]
    s = SelectionState()
    s.select_node(1)
    with qtbot.waitSignal(s.selectionChanged, timeout=500):
        s.clear()
    assert s.is_empty
