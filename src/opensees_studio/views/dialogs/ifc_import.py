"""Import an IFC file: see what it holds, choose which model to build from, then import.

The file has been read once (``inspect_ifc``) before this opens, so the dialog
starts from facts — "12 curve members, 3 load cases; physical model: 8 beams,
8 columns" — and offers only the model the file actually has. The options that
do not apply to the chosen model are disabled rather than hidden, so what each
one means is still visible.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import UnitSystem
from opensees_studio.services.ifc_import import IfcImportOptions, IfcInventory
from opensees_studio.views.screen_fit import FittedDialog, MessageArea


class IfcImportDialog(FittedDialog):
    """Choose the analytical or the physical model of an IFC file, and how to read it."""

    def __init__(self, inventory: IfcInventory, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._inventory = inventory
        self.setWindowTitle(f"Import IFC — {inventory.path.name}")
        self.setProperty(TOPIC_PROPERTY, "file.import_ifc")
        self._build_ui()

    def _build_ui(self) -> None:
        inv = self._inventory
        layout = QVBoxLayout(self)
        summary = QLabel(inv.summary())
        summary.setWordWrap(True)
        layout.addWidget(summary)

        source_box = QGroupBox("Build the model from")
        source_layout = QVBoxLayout(source_box)
        self._analytical = QRadioButton(
            f"Analytical model — {inv.analytical_members} member(s), "
            f"{inv.analytical_surfaces} surface(s), {inv.supports} support(s), "
            f"{inv.load_cases} load case(s)"
        )
        self._physical = QRadioButton(
            f"Physical model — {inv.physical_frames} column/beam/member(s), "
            f"{inv.physical_shells} slab/wall/plate(s); axes are joined, no supports or loads"
        )
        self._analytical.setEnabled(inv.has_analytical)
        self._physical.setEnabled(inv.physical_frames + inv.physical_shells > 0)
        group = QButtonGroup(self)
        group.addButton(self._analytical)
        group.addButton(self._physical)
        (self._analytical if inv.default_source() == "analytical" else self._physical).setChecked(
            True
        )
        source_layout.addWidget(self._analytical)
        source_layout.addWidget(self._physical)
        layout.addWidget(source_box)

        form = QFormLayout()
        self._units = QComboBox()
        for system in UnitSystem:
            self._units.addItem(system.value, system)
        self._units.setCurrentIndex(list(UnitSystem).index(inv.suggested_units))
        self._units.setToolTip(
            "Every value is converted from the file's units to this system. The default is the "
            "system nearest the file's length unit."
        )
        form.addRow("Project units:", self._units)
        layout.addLayout(form)

        self._shells = QCheckBox("Import slabs, walls and surface members as shells")
        self._shells.setChecked(True)
        self._loads = QCheckBox("Import load cases and combinations")
        self._loads.setChecked(True)
        self._bases = QCheckBox("Fix the bottom of the columns at the lowest level")
        self._bases.setChecked(True)
        self._bases.setToolTip(
            "The physical model carries no supports; without them the model is a rigid body."
        )
        for box in (self._shells, self._loads, self._bases):
            layout.addWidget(box)

        self._note = MessageArea()
        layout.addWidget(self._note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._analytical.toggled.connect(self._source_changed)
        self._source_changed()

    def _source_changed(self) -> None:
        analytical = self._analytical.isChecked()
        self._loads.setEnabled(analytical)
        self._bases.setEnabled(not analytical)
        if analytical:
            self._note.show_message(
                "Nodes, supports, members, releases and loads come from the analysis model as "
                "written. A profile named after an AISC shape takes the library's properties."
            )
        else:
            self._note.show_message(
                "Members drawn to their faces are joined to the axes they stop at, and split "
                "where another member lands. Check the connections, the supports and add loads "
                "before running.",
                "warning",
            )

    def options(self) -> IfcImportOptions:
        """What to import, as chosen."""
        return IfcImportOptions(
            source="analytical" if self._analytical.isChecked() else "physical",
            # Qt hands a str-enum back as its text.
            units=UnitSystem(self._units.currentData()),
            include_shells=self._shells.isChecked(),
            include_loads=self._loads.isChecked(),
            fix_column_bases=self._bases.isChecked(),
        )
