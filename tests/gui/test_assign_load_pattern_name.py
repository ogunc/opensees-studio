"""AssignLoadDialog lets the user pick or name a load pattern."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.commands import AddNodalLoadsCommand  # noqa: E402
from opensees_studio.core import (  # noqa: E402
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    Project,
)
from opensees_studio.viewmodels import ProjectViewModel  # noqa: E402
from opensees_studio.views.dialogs.assign_load import AssignLoadDialog  # noqa: E402


@pytest.mark.gui
def test_dialog_defaults_to_new_when_no_patterns(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = AssignLoadDialog(n_selected=1, existing_patterns=[])
    qtbot.addWidget(dlg)
    # Only one row, the "<New pattern…>" sentinel.
    assert dlg._pattern_cb.count() == 1
    assert dlg.selected_pattern_id() is None
    assert dlg._new_name_edit.isEnabled()


@pytest.mark.gui
def test_dialog_lists_existing_patterns(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = AssignLoadDialog(
        n_selected=2,
        existing_patterns=[(1, "Gravity"), (2, "RefMoment")],
    )
    qtbot.addWidget(dlg)
    # 2 existing + 1 new sentinel.
    assert dlg._pattern_cb.count() == 3
    assert dlg._pattern_cb.currentIndex() == 0
    assert dlg.selected_pattern_id() == 1
    # Switch to RefMoment.
    dlg._pattern_cb.setCurrentIndex(1)
    assert dlg.selected_pattern_id() == 2
    # The new-name field is disabled for existing picks.
    assert not dlg._new_name_edit.isEnabled()


@pytest.mark.gui
def test_dialog_enables_name_field_for_new_pattern(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = AssignLoadDialog(
        n_selected=1, existing_patterns=[(1, "Gravity")],
    )
    qtbot.addWidget(dlg)
    dlg._pattern_cb.setCurrentIndex(1)   # "<New pattern…>"
    assert dlg.selected_pattern_id() is None
    assert dlg._new_name_edit.isEnabled()
    dlg._new_name_edit.setText("RefMoment")
    assert dlg.new_pattern_name() == "RefMoment"


@pytest.mark.gui
def test_command_creates_named_pattern(qtbot) -> None:  # type: ignore[no-untyped-def]
    """AddNodalLoadsCommand with new_pattern_name must create a fresh
    PlainLoadPattern with that name, rather than reusing a default."""
    vm = ProjectViewModel()
    vm.new_project(ndm=2, ndf=3)
    vm.project.nodes.append(Node(id=1, coords=(0, 0, 0)))
    # Pre-existing 'Gravity' pattern — must NOT be reused when the user
    # asks for a new one named 'RefMoment'.
    vm.project.time_series.append(LinearTimeSeries(id=1, name="Gravity"))
    vm.project.load_patterns.append(PlainLoadPattern(
        id=1, name="Gravity", time_series_id=1,
    ))

    vm.apply_command(AddNodalLoadsCommand(
        vm, {1}, (0, 0, 0, 0, 0, 1.0),
        pattern_id=None, new_pattern_name="RefMoment",
    ))
    # Two patterns now: Gravity (id=1) and RefMoment (id=2).
    names = [p.name for p in vm.project.load_patterns]
    assert "Gravity" in names and "RefMoment" in names
    ref = next(p for p in vm.project.load_patterns if p.name == "RefMoment")
    assert ref.id == 2
    assert ref.nodal_loads[0].forces[5] == pytest.approx(1.0)


@pytest.mark.gui
def test_command_reuses_existing_pattern_by_id(qtbot) -> None:  # type: ignore[no-untyped-def]
    """pattern_id=1 reuses the existing pattern — doesn't create new."""
    vm = ProjectViewModel()
    vm.new_project(ndm=2, ndf=3)
    vm.project.nodes.append(Node(id=1, coords=(0, 0, 0)))
    vm.project.time_series.append(LinearTimeSeries(id=1, name="Existing"))
    vm.project.load_patterns.append(PlainLoadPattern(
        id=1, name="Existing", time_series_id=1,
    ))
    vm.apply_command(AddNodalLoadsCommand(
        vm, {1}, (0, 0, 0, 0, 0, 5.0), pattern_id=1,
    ))
    assert len(vm.project.load_patterns) == 1
    assert len(vm.project.load_patterns[0].nodal_loads) == 1
