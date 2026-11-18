"""The Tcl import dialog previews the project and its unit choice before import."""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import UnitSystem
from opensees_studio.views.dialogs.tcl_import import TclImportDialog


def test_dialog_previews_and_rebuilds_on_a_unit_change(qtbot, tmp_path: Path) -> None:
    path = tmp_path / "cantilever.tcl"
    path.write_text(
        """
model basic -ndm 2 -ndf 3
node 1 0 0
node 2 120 0
fix 1 1 1 1
section Elastic 1 29000 10 100
geomTransf Linear 1
element elasticBeamColumn 1 1 2 10 29000 100 1
pattern Plain 1 Linear { load 2 0 -10 0 }
""",
        encoding="utf-8",
    )
    dialog = TclImportDialog(default_units=UnitSystem.US_IN_KIP)
    qtbot.addWidget(dialog)

    assert dialog.load(path)
    imported = dialog.imported()
    assert imported is not None
    assert imported.project.meta.units is UnitSystem.US_IN_KIP
    assert len(imported.project.elements) == 1

    dialog._units.setCurrentIndex(dialog._units.findData(UnitSystem.SI_M_N.name))
    assert dialog.imported() is not None
    assert dialog.imported().project.meta.units is UnitSystem.SI_M_N
