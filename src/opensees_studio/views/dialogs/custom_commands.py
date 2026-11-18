"""Define → Custom OpenSees Commands: blocks of OpenSeesPy calls run during the build.

The list holds the blocks (name, stage, enabled); the editor below shows the
selected block's code. OK hands back the edited list (``blocks()``); the main
window applies it as one undo step.
"""

from __future__ import annotations

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import CustomCommandBlock, Project
from opensees_studio.core.custom_commands import STAGE_LABELS, block_tag_base
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

EXAMPLE = """# OpenSeesPy calls; ops, project, ndm, ndf and tag (this block's first free tag)
# are defined. Example: a viscous damper between joints 3 and 7.
# ops.uniaxialMaterial("ViscousDamper", tag, 1e8, 1e5, 0.35)
# ops.element("twoNodeLink", tag, 3, 7, "-mat", tag, "-dir", 1)
"""


class CustomCommandsDialog(FittedDialog):
    """Add, edit, enable or remove custom command blocks."""

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Custom OpenSees Commands")
        self.resize(820, 620)
        self._blocks = [b.model_copy() for b in project.custom_commands]
        self._current = -1
        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                "OpenSeesPy calls for what the application has no form for. Each enabled "
                "block runs while the model is built, in this order. <b>The code runs on "
                "this computer</b>: only enable blocks you wrote or trust."
            )
        )
        row = QHBoxLayout()
        self.listing = QListWidget()
        self.listing.currentRowChanged.connect(self._on_select)
        row.addWidget(self.listing, 1)
        buttons = QVBoxLayout()
        self.add_button = QPushButton("Add block")
        self.add_button.clicked.connect(self._on_add)
        self.remove_button = QPushButton("Remove block")
        self.remove_button.clicked.connect(self._on_remove)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        row.addLayout(buttons)
        root.addLayout(row)

        form = QFormLayout()
        self.name = QLineEdit()
        self.stage = QComboBox()
        for key, label in STAGE_LABELS.items():
            self.stage.addItem(label, key)
        self.enabled = QCheckBox("Enabled")
        self.tag_label = QLabel()
        form.addRow("Name:", self.name)
        form.addRow("Runs:", self.stage)
        form.addRow(self.enabled, self.tag_label)
        root.addLayout(form)
        self.code = QPlainTextEdit()
        self.code.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        root.addWidget(self.code, 2)
        self.message = MessageArea()
        root.addWidget(self.message)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        for block in self._blocks:
            self.listing.addItem(self._label(block))
        self._set_editor_enabled(False)
        if self._blocks:
            self.listing.setCurrentRow(0)

    @staticmethod
    def _label(block: CustomCommandBlock) -> str:
        state = "" if block.enabled else "  (disabled)"
        return f"{block.name or block.id}  [{block.stage}]{state}"

    def _set_editor_enabled(self, on: bool) -> None:
        for widget in (self.name, self.stage, self.enabled, self.code):
            widget.setEnabled(on)

    def _store(self) -> None:
        """Write the editor back into the current block."""
        if not 0 <= self._current < len(self._blocks):
            return
        block = self._blocks[self._current].model_copy(
            update={
                "name": self.name.text().strip(),
                "stage": self.stage.currentData(),
                "enabled": self.enabled.isChecked(),
                "code": self.code.toPlainText(),
            }
        )
        self._blocks[self._current] = block
        item = self.listing.item(self._current)
        if item is not None:
            item.setText(self._label(block))

    def _on_select(self, row: int) -> None:
        self._store()
        self._current = row
        if not 0 <= row < len(self._blocks):
            self._set_editor_enabled(False)
            return
        block = self._blocks[row]
        self._set_editor_enabled(True)
        self.name.setText(block.name)
        self.stage.setCurrentIndex(self.stage.findData(block.stage))
        self.enabled.setChecked(block.enabled)
        self.code.setPlainText(block.code)
        self.tag_label.setText(f"<i>tag = {block_tag_base(row)} … {block_tag_base(row) + 999}</i>")

    def _on_add(self) -> None:
        self._store()
        block_id = max((b.id for b in self._blocks), default=0) + 1
        block = CustomCommandBlock(id=block_id, name=f"Block {block_id}", code=EXAMPLE)
        self._blocks.append(block)
        self.listing.addItem(self._label(block))
        self.listing.setCurrentRow(len(self._blocks) - 1)

    def _on_remove(self) -> None:
        row = self.listing.currentRow()
        if not 0 <= row < len(self._blocks):
            return
        self._current = -1
        del self._blocks[row]
        self.listing.takeItem(row)

    def blocks(self) -> list[CustomCommandBlock]:
        """The blocks as edited (raises ``SyntaxError`` naming a block that does not compile)."""
        self._store()
        for block in self._blocks:
            compile(block.code, f"<custom block {block.name or block.id}>", "exec")
        return list(self._blocks)

    def accept(self) -> None:
        try:
            self.blocks()
        except SyntaxError as exc:
            self.message.show_message(f"{exc.filename}, line {exc.lineno}: {exc.msg}", "error")
            return
        super().accept()
