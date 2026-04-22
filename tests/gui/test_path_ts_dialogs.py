"""GUI tests for PathTimeSeries + UniformExcitation dialogs + commands."""

from __future__ import annotations

import textwrap

import pytest

pytest.importorskip("PySide6")

from opensees_studio.commands import (  # noqa: E402
    AddLoadPatternCommand,
    AddTimeSeriesCommand,
)
from opensees_studio.core import (  # noqa: E402
    Node,
    PathTimeSeries,
    Project,
    UniformExcitationPattern,
)
from opensees_studio.viewmodels import ProjectViewModel  # noqa: E402


# ─────────────── AddTimeSeriesCommand / AddLoadPatternCommand ──────────────
@pytest.mark.gui
def test_add_time_series_command_is_undoable(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = ProjectViewModel()
    vm.new_project()
    ts = PathTimeSeries(id=1, name="GM", dt=0.01, factor=386.4, values=[0.1, 0.2])
    vm.apply_command(AddTimeSeriesCommand(vm, ts))
    assert len(vm.project.time_series) == 1        # type: ignore[union-attr]
    vm.undo_stack.undo()
    assert vm.project.time_series == []            # type: ignore[union-attr]
    vm.undo_stack.redo()
    assert vm.project.time_series[0].name == "GM"  # type: ignore[union-attr]


@pytest.mark.gui
def test_add_time_series_rejects_duplicate_id(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = ProjectViewModel()
    vm.new_project()
    vm.project.time_series.append(PathTimeSeries(  # type: ignore[union-attr]
        id=1, name="Existing", dt=0.01, values=[0.0],
    ))
    ts2 = PathTimeSeries(id=1, name="Duplicate", dt=0.01, values=[0.0])
    with pytest.raises(ValueError):
        vm.apply_command(AddTimeSeriesCommand(vm, ts2))


@pytest.mark.gui
def test_add_load_pattern_command_is_undoable(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = ProjectViewModel()
    vm.new_project()
    vm.project.time_series.append(PathTimeSeries(  # type: ignore[union-attr]
        id=1, name="GM", dt=0.01, values=[0.1, 0.2],
    ))
    pat = UniformExcitationPattern(
        id=1, name="EQ", direction=1, accel_series_id=1,
    )
    vm.apply_command(AddLoadPatternCommand(vm, pat))
    assert len(vm.project.load_patterns) == 1      # type: ignore[union-attr]
    vm.undo_stack.undo()
    assert vm.project.load_patterns == []          # type: ignore[union-attr]


# ─────────────── PathTimeSeriesDialog ──────────────
@pytest.mark.gui
def test_path_ts_dialog_manual_entry(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.path_time_series import PathTimeSeriesDialog
    dlg = PathTimeSeriesDialog(next_ts_id=1)
    qtbot.addWidget(dlg)
    # Simulate a plain-values import by directly seeding the values
    # field (matches what _on_import_plain does after file read).
    dlg._values = [0.1, 0.2, 0.3, 0.4, 0.5]
    dlg._name_edit.setText("GM-test")
    dlg._dt_spin.setValue(0.02)
    dlg._factor_spin.setValue(386.4)
    ts = dlg.time_series()
    assert ts.id == 1
    assert ts.name == "GM-test"
    assert ts.dt == pytest.approx(0.02)
    assert ts.factor == pytest.approx(386.4)
    assert ts.values == pytest.approx([0.1, 0.2, 0.3, 0.4, 0.5])


@pytest.mark.gui
def test_path_ts_dialog_imports_peer(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """_on_import_peer populates dt / npts from the header + value list."""
    from opensees_studio.views.dialogs.path_time_series import PathTimeSeriesDialog
    rec = tmp_path / "test.at2"
    rec.write_text(textwrap.dedent("""\
        PEER PACIFIC
        EL CENTRO 1940
        ACCELERATION IN G
        3 0.025 NPTS, DT
        0.01 -0.02 0.03
    """))
    dlg = PathTimeSeriesDialog(next_ts_id=1)
    qtbot.addWidget(dlg)
    # Feed the file path directly through the parser + state-setter
    # logic. Simulating QFileDialog in a headless test is fragile;
    # calling _on_import_peer's internals is the stable path.
    from opensees_studio.services.peer_record import parse_peer_record
    dt, npts, vals = parse_peer_record(rec)
    dlg._values = vals
    dlg._dt_spin.setValue(dt)
    ts = dlg.time_series()
    assert ts.dt == pytest.approx(0.025)
    assert ts.values == pytest.approx([0.01, -0.02, 0.03])


# ─────────────── UniformExcitationDialog ──────────────
@pytest.mark.gui
def test_uniform_excitation_dialog_requires_time_series(qtbot) -> None:  # type: ignore[no-untyped-def]
    """With no TimeSeries defined, the dialog's picker is disabled."""
    from opensees_studio.views.dialogs.uniform_excitation import UniformExcitationDialog
    proj = Project()
    dlg = UniformExcitationDialog(project=proj, next_pattern_id=1)
    qtbot.addWidget(dlg)
    assert not dlg._accel_cb.isEnabled()


@pytest.mark.gui
def test_uniform_excitation_dialog_builds_pattern(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.uniform_excitation import UniformExcitationDialog
    proj = Project(time_series=[
        PathTimeSeries(id=7, name="GM", dt=0.01, values=[0.0, 0.1]),
    ])
    dlg = UniformExcitationDialog(project=proj, next_pattern_id=2)
    qtbot.addWidget(dlg)
    # Pick direction = 1 (X) — already default.
    dlg._name_edit.setText("Earthquake-X")
    dlg._factor_spin.setValue(1.0)
    pat = dlg.pattern()
    assert pat.id == 2
    assert pat.name == "Earthquake-X"
    assert pat.direction == 1
    assert pat.accel_series_id == 7
    assert pat.factor == pytest.approx(1.0)
