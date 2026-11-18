"""Design → Member Classification: physical members, their role and unbraced lengths.

Lists every physical member the steel check sees (a chain of collinear elements
of one section, :mod:`core.design.members`): its elements, its role, its length
and the unbraced lengths Lx, Ly and Lb the bracing points give. The role can be
set by hand; the lengths are entered as overrides in the Steel Frame Check when
the automatic ones do not fit.

Nothing runs here and nothing changes until OK: the window stores the roles with
one undoable command.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.design.members import ROLE_LABELS
from opensees_studio.core.design.settings import DesignSettings, SteelMemberDesign
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import labels_for
from opensees_studio.services.steel_design import MemberLengths, member_lengths
from opensees_studio.views.dialogs.design_basis import _ok_cancel
from opensees_studio.views.screen_fit import FittedDialog

_COLUMNS = ["Member", "Elements", "Role", "Length", "Lx", "Ly", "Lb"]


class MemberClassificationDialog(FittedDialog):
    """One row per physical member: role (editable) and automatic unbraced lengths."""

    def __init__(self, project: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._base = project.design or DesignSettings()
        self.setWindowTitle("Member Classification")
        self.setProperty(TOPIC_PROPERTY, "design.member_classification")
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Collinear elements of one section form one member. Lx and Ly run between the "
            "joints that hold the member along each axis (a member framing in, a support, "
            "a diaphragm, a slab); Lb is the minor-axis one. The largest value over the "
            "member's elements is shown. Change the role where the direction misleads; "
            "enter other lengths as overrides in the Steel Frame Check."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        rows: dict[int, list[MemberLengths]] = {}
        for item in member_lengths(project, self._base):
            rows.setdefault(item.member_id, []).append(item)
        self._members = rows
        unit = labels_for(project.meta.units).length
        self._table = QTableWidget(len(rows), len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(
            [c if c in ("Member", "Elements", "Role") else f"{c} [{unit}]" for c in _COLUMNS]
        )
        self._roles: dict[int, QComboBox] = {}
        for row, (member_id, items) in enumerate(rows.items()):
            first = items[0]
            combo = QComboBox()
            auto = next((i.role for i in items if not i.role_from_user), first.role)
            combo.addItem(f"Auto ({ROLE_LABELS.get(auto, auto).lower()})", None)
            for key, label in ROLE_LABELS.items():
                combo.addItem(label, key)
            if any(i.role_from_user for i in items):
                combo.setCurrentIndex(combo.findData(first.role))
            self._roles[member_id] = combo
            values = [
                str(member_id),
                " ".join(str(e) for e in first.element_ids),
                None,
                f"{first.length:.4g}",
                *(f"{max(i.unbraced[k] for i in items):.4g}" for k in range(3)),
            ]
            for col, text in enumerate(values):
                if text is None:
                    self._table.setCellWidget(row, col, combo)
                else:
                    self._table.setItem(row, col, QTableWidgetItem(text))
        self._table.resizeColumnsToContents()
        layout.addWidget(self._table)
        layout.addWidget(_ok_cancel(self))

    def member_count(self) -> int:
        return len(self._members)

    def set_role(self, member_id: int, role: str | None) -> None:
        combo = self._roles[member_id]
        combo.setCurrentIndex(combo.findData(role))

    def settings(self) -> DesignSettings:
        """The design settings with the chosen roles on every element of each member."""
        by_element = {m.element_id: m for m in self._base.members}
        for member_id, combo in self._roles.items():
            role = combo.currentData()
            for element_id in self._members[member_id][0].element_ids:
                current = by_element.get(element_id, SteelMemberDesign(element_id=element_id))
                by_element[element_id] = current.model_copy(update={"role": role})
        members = [
            m
            for _, m in sorted(by_element.items())
            if m != SteelMemberDesign(element_id=m.element_id)
        ]
        return self._base.model_copy(update={"members": members})
