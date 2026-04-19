"""Unit tests for the Assign Zero-Length Section dialog."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import (  # noqa: E402
    ElasticSection,
    Node,
    Project,
)
from opensees_studio.views.dialogs.assign_zls import (  # noqa: E402
    AssignZeroLengthSectionDialog,
)


def _project_with_section() -> Project:
    return Project(
        ndm=2, ndf=3,
        nodes=[
            Node(id=1, coords=(0, 0, 0)),
            Node(id=2, coords=(0, 0, 0)),
        ],
        sections=[ElasticSection(
            id=3, name="MK", E=30000, A=200, Iz=6667, Iy=6667,
            G=12000, J=100,
        )],
    )


@pytest.mark.gui
def test_dialog_lists_project_sections(qtbot) -> None:  # type: ignore[no-untyped-def]
    p = _project_with_section()
    dlg = AssignZeroLengthSectionDialog(p, (1, 2))
    qtbot.addWidget(dlg)
    assert dlg._section_cb.count() == 1
    assert dlg._section_cb.itemData(0) == 3
    assert dlg.section_id() == 3


@pytest.mark.gui
def test_dialog_disabled_when_no_sections(qtbot) -> None:  # type: ignore[no-untyped-def]
    p = Project(
        ndm=2, ndf=3,
        nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(0, 0, 0))],
    )
    dlg = AssignZeroLengthSectionDialog(p, (1, 2))
    qtbot.addWidget(dlg)
    assert not dlg._section_cb.isEnabled()
    assert dlg.section_id() is None
