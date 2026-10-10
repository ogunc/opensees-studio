"""A force diagram over a model of faces must not take the application down.

Reproduces the crash of 2026-10-06: a project with shells was solved, Display →
Show Force Diagram was opened, and the renderer unpacked the shell's four nodes
into ``n_i, n_j`` inside a Qt slot. An exception raised there is caught by
nothing — the event loop unwinds and the process dies, with no dialog.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.commands import AddElementsCommand, AddNodesCommand, AddSectionsCommand
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    Node,
    ShellMITC4Element,
)
from opensees_studio.services.results import StaticResults

NODES = [
    (0.0, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (2.0, 0.0, 0.0),
    (2.0, 1.0, 0.0),
    (1.0, 1.0, 0.0),
]


def _window(qtbot, *, with_beam: bool = True):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=3, ndf=6)
    mw._vm.apply_command(
        AddNodesCommand(mw._vm, [Node(id=i + 1, coords=c) for i, c in enumerate(NODES)])
    )
    mw._vm.apply_command(
        AddSectionsCommand(
            mw._vm,
            [
                ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6),
                ElasticMembranePlateSection(id=2, E=30e9, nu=0.2, h=0.2, rho=2500.0),
            ],
        )
    )
    elements = [ShellMITC4Element(id=20, nodes=(2, 3, 4, 5), section_id=2)]
    if with_beam:
        elements.insert(0, ElasticBeamColumn(id=10, nodes=(1, 2), section_id=1))
    mw._vm.apply_command(AddElementsCommand(mw._vm, elements))
    return mw


def _results() -> StaticResults:
    """What a real solve returns: 12 components for the beam, 24 for the shell."""
    beam = np.zeros((1, 12))
    beam[0, 5] = 9.0
    shell = np.arange(24, dtype=float).reshape(1, 24)
    return StaticResults(case_id=1, case_name="t", n_steps=1, element_forces={10: beam, 20: shell})


@pytest.mark.gui
def test_force_diagram_over_a_shell_model_does_not_crash(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._latest_results = _results()

    mw._on_show_force_diagram()  # would raise ValueError before the fix

    assert mw._post_dock is not None
    assert mw._diagram_renderer is not None
    assert mw._diagram_renderer._actor is not None  # the beam is drawn


@pytest.mark.gui
def test_a_model_of_faces_only_says_so_instead_of_failing(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot, with_beam=False)
    mw._latest_results = _results()

    mw._on_show_force_diagram()

    assert mw._post_dock is not None
    assert "Nothing to draw" in mw._console.toPlainText()
    assert mw._diagram_renderer._actor is None
