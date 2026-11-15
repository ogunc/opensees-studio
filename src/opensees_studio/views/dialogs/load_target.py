"""Where a load goes and what it does to the loads already there.

Every Assign → … Load dialog embeds a :class:`LoadTargetBox`: the Plain load
pattern the load belongs to (DEAD, LIVE, …) and whether it is **added** to the
loads the selection already has in that pattern, **replaces** them, or
**deletes** them. Replace and delete act on the same kind of load only (a
uniform load replaces uniform loads, not point loads) and leave the other
patterns alone. The pattern last chosen is offered first next time, so a run
of LIVE assignments does not need it picked again.
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel, QWidget

from opensees_studio.core.units import UnitSystem, labels_for

ADD = "add"
REPLACE = "replace"
DELETE = "delete"

#: The pattern chosen last in this session, offered first by the next dialog.
_last_pattern_id: int | None = None


def last_pattern_id() -> int | None:
    """The pattern the last load dialog used, None before the first one."""
    return _last_pattern_id


def remember_pattern(pattern_id: int | None) -> None:
    """Offer ``pattern_id`` first in the next load dialog."""
    global _last_pattern_id
    _last_pattern_id = pattern_id


def plain_patterns(project: object) -> list[tuple[int, str]]:
    """``(id, name)`` of every Plain pattern of ``project``, the targets a load can have."""
    from opensees_studio.core import PlainLoadPattern

    return [
        (p.id, p.name)
        for p in getattr(project, "load_patterns", [])
        if isinstance(p, PlainLoadPattern)
    ]


def force_units(project: object, per_length: bool = False) -> str:
    """``N``, ``kip``, … or ``N/m``, ``kip/ft``, … in the project's units; "" if unknown."""
    meta = getattr(project, "meta", None)
    units = getattr(meta, "units", None)
    if not isinstance(units, UnitSystem):
        return ""
    labels = labels_for(units)
    return f"{labels.force}/{labels.length}" if per_length else labels.force


class LoadTargetBox(QGroupBox):
    """The pattern and the add / replace / delete mode of one load assignment."""

    def __init__(self, patterns: list[tuple[int, str]], parent: QWidget | None = None) -> None:
        super().__init__("Load pattern", parent)
        form = QFormLayout(self)
        self._pattern = QComboBox()
        for pid, name in patterns:
            self._pattern.addItem(name or f"#{pid}", pid)
        if not patterns:
            self._pattern.addItem("(a default pattern is created)", None)
            self._pattern.setEnabled(False)
        elif _last_pattern_id is not None:
            index = self._pattern.findData(_last_pattern_id)
            if index >= 0:
                self._pattern.setCurrentIndex(index)
        form.addRow("Pattern:", self._pattern)
        self._mode = QComboBox()
        self._mode.addItem("Add to existing loads", ADD)
        self._mode.addItem("Replace existing loads", REPLACE)
        self._mode.addItem("Delete existing loads", DELETE)
        self._mode.setToolTip(
            "Add: the load is summed with the ones the selection already has in this "
            "pattern. Replace: those loads are removed first. Delete: they are removed "
            "and nothing is added. Only loads of this kind in this pattern are touched."
        )
        form.addRow("Existing loads:", self._mode)
        self._hint = QLabel()
        self._hint.setWordWrap(True)
        form.addRow(self._hint)
        self._mode.currentIndexChanged.connect(self._sync_hint)
        self._sync_hint()

    def _sync_hint(self) -> None:
        self._hint.setText(
            "<i>The values below are not used: the selection's loads of this kind in "
            "this pattern are removed.</i>"
            if self.mode() == DELETE
            else ""
        )
        self._hint.setVisible(self.mode() == DELETE)

    @property
    def mode_combo(self) -> QComboBox:
        """The mode selector, for the host dialog to follow its changes."""
        return self._mode

    def pattern_id(self) -> int | None:
        """The chosen pattern, or None when the project has none yet."""
        data = self._pattern.currentData()
        return None if data is None else int(data)

    def pattern_text(self) -> str:
        """The chosen pattern's name, for the log."""
        return self._pattern.currentText()

    def mode(self) -> str:
        """``ADD``, ``REPLACE`` or ``DELETE``."""
        return str(self._mode.currentData())

    def set_pattern(self, pattern_id: int) -> None:
        index = self._pattern.findData(pattern_id)
        if index >= 0:
            self._pattern.setCurrentIndex(index)

    def set_mode(self, mode: str) -> None:
        self._mode.setCurrentIndex(self._mode.findData(mode))

    def remember(self) -> None:
        """Offer this pattern first in the next load dialog (call on OK)."""
        if self.pattern_id() is not None:
            remember_pattern(self.pattern_id())
