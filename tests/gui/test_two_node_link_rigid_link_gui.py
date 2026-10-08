"""A project with a twoNodeLink and a rigid link opens, draws, shows its
properties and saves in the desktop GUI. Neither kind has an editor."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QLabel, QMessageBox

from opensees_studio.core import (
    ElasticUniaxial,
    Node,
    Project,
    RigidLinkConstraint,
    TwoNodeLinkElement,
)
from opensees_studio.services import load_project, save_project
from opensees_studio.views.main_window import MainWindow

pytestmark = pytest.mark.gui


def _project() -> Project:
    return Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(id=2, coords=(0, 0, 0.2)),
            Node(id=3, coords=(0.3, 0.0, 0.2)),
        ],
        materials=[ElasticUniaxial(id=1, E=100.0)],
        elements=[
            TwoNodeLinkElement(
                id=5,
                nodes=(1, 2),
                material_ids=(1, 1),
                dofs=(1, 2),
                orient_y=(1, 0, 0),
                shear_dist=(0.5, 0.5),
            )
        ],
        mp_constraints=[RigidLinkConstraint(retained_node=2, constrained_node=3)],
    )


def test_open_draw_inspect_and_save(qtbot, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    failures: list[str] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: failures.append(str(a)))
    path = save_project(_project(), tmp_path / "link.osmodel")
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project(path)
    project = window._vm.project
    assert isinstance(project.elements[0], TwoNodeLinkElement)

    renderer = window._canvas._renderer
    assert 5 in renderer._frame_ids_ordered  # drawn as a line between its nodes

    window._props.update_for_selection(frozenset(), frozenset({5}))
    texts = [w.text() for w in window._props.findChildren(QLabel)]
    assert "TwoNodeLink" in texts
    assert "1, 2" in texts

    out = tmp_path / "again.osmodel"
    window._vm.save(out)
    assert failures == []
    assert load_project(out) == project
