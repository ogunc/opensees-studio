"""Selection state — a small Qt-aware aggregate over selected entities.

Lives in the views layer (it's Qt-aware), but is intentionally view-
agnostic: any view (canvas, model tree, properties dock) can subscribe
to ``selectionChanged`` and stay in sync. The state itself is a plain
holder; no UI logic.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class SelectionState(QObject):
    """Holds the currently selected node and element ids.

    Signals:
        selectionChanged: emitted with (frozenset[int] node_ids,
                                        frozenset[int] element_ids)
            after any change.
    """

    selectionChanged = Signal(frozenset, frozenset)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._nodes: set[int] = set()
        self._elements: set[int] = set()

    # ── read ─────────────────────────────────────────────────────────
    @property
    def nodes(self) -> frozenset[int]:
        return frozenset(self._nodes)

    @property
    def elements(self) -> frozenset[int]:
        return frozenset(self._elements)

    @property
    def is_empty(self) -> bool:
        return not self._nodes and not self._elements

    # ── write ────────────────────────────────────────────────────────
    def clear(self) -> None:
        if self.is_empty:
            return
        self._nodes.clear()
        self._elements.clear()
        self._emit()

    def select_node(self, node_id: int, *, additive: bool = False) -> None:
        if not additive:
            self._nodes.clear()
            self._elements.clear()
        self._nodes.add(node_id)
        self._emit()

    def select_element(self, element_id: int, *, additive: bool = False) -> None:
        if not additive:
            self._nodes.clear()
            self._elements.clear()
        self._elements.add(element_id)
        self._emit()

    def toggle_node(self, node_id: int) -> None:
        if node_id in self._nodes:
            self._nodes.remove(node_id)
        else:
            self._nodes.add(node_id)
        self._emit()

    def toggle_element(self, element_id: int) -> None:
        if element_id in self._elements:
            self._elements.remove(element_id)
        else:
            self._elements.add(element_id)
        self._emit()

    def set_selection(self, nodes: set[int], elements: set[int]) -> None:
        if self._nodes == nodes and self._elements == elements:
            return
        self._nodes = set(nodes)
        self._elements = set(elements)
        self._emit()

    def _emit(self) -> None:
        self.selectionChanged.emit(self.nodes, self.elements)
