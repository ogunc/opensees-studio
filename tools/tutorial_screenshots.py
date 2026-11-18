"""Regenerate the dialog screenshots of the tutorials (``docs/tutorials/img``).

The dialogs are plain Qt widgets, so they render without a GPU: this runs with
``QT_QPA_PLATFORM=offscreen`` in a headless container as well as on a desktop.
The models are the bundled examples, solved here with the same runner the
application uses, so a screenshot always shows what the current code computes.

Usage (from the repository root, with the ``gui`` and ``opensees`` extras)::

    QT_QPA_PLATFORM=offscreen python tools/tutorial_screenshots.py

The 3D viewport needs OpenGL and is not captured here; the tutorials use the
repository's own main-window screenshot for it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "tutorials" / "img"


def _solve(project):  # type: ignore[no-untyped-def]
    from opensees_studio.services.opensees_runner import OpenSeesRunner

    return {case.id: OpenSeesRunner(project).run(case) for case in project.analyses}


def _save(widget, name: str, width: int, height: int) -> Path:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QApplication

    widget.resize(width, height)
    widget.show()
    for _ in range(10):
        QApplication.processEvents()
    path = OUT / name
    widget.grab().save(str(path))
    widget.close()
    print(f"Wrote {path.relative_to(REPO)}")
    return path


def steel_check() -> None:
    from opensees_studio.services import load_project
    from opensees_studio.views.dialogs import SteelDesignDialog

    project = load_project(REPO / "examples" / "steel_frame_design.osmodel")
    dialog = SteelDesignDialog(project, _solve(project))
    dialog.run_check()
    _save(dialog, "steel-check.png", 1100, 760)


def drift_check() -> None:
    from opensees_studio.services import load_project
    from opensees_studio.views.dialogs import DriftCheckDialog

    project = load_project(REPO / "examples" / "steel_frame_design.osmodel")
    dialog = DriftCheckDialog(project, _solve(project))
    dialog._preset.setCurrentIndex(1)  # ASCE 7-22, risk category I/II
    dialog._amplification.setValue(5.5)  # Cd / Ie of a special steel moment frame
    dialog.run_check()
    _save(dialog, "drift-check.png", 760, 520)


def building_drift() -> None:
    from opensees_studio.services import load_project
    from opensees_studio.views.dialogs import DriftCheckDialog

    project = load_project(REPO / "examples" / "building_3storey_diaphragm.osmodel")
    dialog = DriftCheckDialog(project, _solve(project))
    dialog._preset.setCurrentIndex(4)  # NCh433, 0.002 h
    dialog.run_check()
    _save(dialog, "building-drift.png", 760, 560)


def portico_import() -> None:
    from opensees_studio.views.dialogs import S3dImportDialog

    free = {"ux": 0, "uy": 0, "uz": 0, "rx": 0, "ry": 0, "rz": 0}
    nodes = []
    for k, (x, y) in enumerate([(0, 0), (6, 0), (6, 6), (0, 6)], start=1):
        nodes.append({"id": k, "x": x, "y": y, "z": 3.0, "restraints": free})
        nodes.append({"id": k + 4, "x": x, "y": y, "z": 0.0, "restraints": dict.fromkeys(free, 1)})
    model = {
        "version": "1.0",
        "units": "kN-m",
        "mode": "3D",
        "nodes": nodes,
        "elements": [{"id": k, "n1": k + 4, "n2": k, "matId": 1, "secId": 1} for k in range(1, 5)],
        "areas": [
            {"id": 1, "nodes": [1, 2, 3, 4], "matId": 1, "thickness": 0.15, "behavior": "plate"}
        ],
        "materials": [{"id": 1, "name": "G30", "E": 2.87e7, "G": 1.19e7, "nu": 0.2, "rho": 2.5}],
        "sections": [
            {
                "id": 1,
                "name": "Col 40x40",
                "A": 0.16,
                "Iz": 2.13e-3,
                "Iy": 2.13e-3,
                "J": 3.6e-3,
                "Avy": 0.133,
                "Avz": 0.133,
            }
        ],
        "diaphragms": [{"id": 1, "name": "Roof", "z": 3.0, "nodes": [1, 2, 3, 4]}],
        "loadCases": [
            {"id": 1, "name": "PP", "type": "static", "selfWeight": True, "loads": []},
            {"id": 2, "name": "Sismo X", "type": "spectrum", "specDir": "X", "loads": []},
        ],
        "combinations": [],
    }
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "one-storey.s3d"
        path.write_text(json.dumps(model), encoding="utf-8")
        dialog = S3dImportDialog()
        dialog.load(path)
        _save(dialog, "portico-import.png", 760, 460)


def main() -> int:
    from PySide6.QtWidgets import QApplication

    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    for make in (steel_check, drift_check, building_drift, portico_import):
        make()
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
