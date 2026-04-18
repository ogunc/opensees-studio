"""SAP2000-style grid dialog tests — DefineGridSystemDataDialog and friends."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import (  # noqa: E402
    CoordinateGridSystem,
    CoordinateSystem,
    GridLine,
    GridSystem,
    make_grid_lines,
)


# ────────────────────────── Quick Grid Lines ──────────────────────────
@pytest.mark.gui
def test_quick_grid_lines_produces_ordinates(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.quick_grid_lines import QuickGridLinesDialog
    dlg = QuickGridLinesDialog()
    qtbot.addWidget(dlg)
    dlg._x_n.setValue(4); dlg._x_s.setValue(3.0); dlg._x_f.setValue(0.0)
    dlg._y_n.setValue(2); dlg._y_s.setValue(4.0); dlg._y_f.setValue(0.0)
    dlg._z_n.setValue(3); dlg._z_s.setValue(3.0); dlg._z_f.setValue(-3.0)
    xs, ys, zs = dlg.ordinates()
    assert xs == [0.0, 3.0, 6.0, 9.0]
    assert ys == [0.0, 4.0]
    assert zs == [-3.0, 0.0, 3.0]


@pytest.mark.gui
def test_quick_grid_zero_lines_produces_empty(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.quick_grid_lines import QuickGridLinesDialog
    dlg = QuickGridLinesDialog()
    qtbot.addWidget(dlg)
    dlg._x_n.setValue(0)
    dlg._y_n.setValue(0)
    dlg._z_n.setValue(0)
    xs, ys, zs = dlg.ordinates()
    assert xs == [] and ys == [] and zs == []


# ────────────────────── Coord Location + Orientation ──────────────────
@pytest.mark.gui
def test_locate_origin_round_trip(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.locate_origin import (
        CoordSystemLocationOrientationDialog,
    )
    dlg = CoordSystemLocationOrientationDialog(
        origin=(1.5, -2.0, 3.0),
        rotation_deg=(0.0, 0.0, 45.0),
    )
    qtbot.addWidget(dlg)
    origin, rot = dlg.location()
    assert origin == pytest.approx((1.5, -2.0, 3.0))
    assert rot == pytest.approx((0.0, 0.0, 45.0))


# ────────────────────── Define Grid System Data form ──────────────────
@pytest.mark.gui
def test_define_grid_data_round_trip(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Loading an existing system and reading .system() must round-trip."""
    from opensees_studio.views.dialogs.define_grid_data import (
        DefineGridSystemDataDialog,
    )
    cs = CoordinateGridSystem(
        name="Floor2",
        coord=CoordinateSystem(origin=(0, 0, 3.5)),
        grid=GridSystem(
            x_grid_lines=make_grid_lines("X", [0.0, 4.0, 8.0]),
            y_grid_lines=make_grid_lines("Y", [0.0, 6.0]),
            z_grid_lines=make_grid_lines("Z", [0.0]),
            hide_all=False,
            glue_to_grid=True,
            bubble_size=18,
        ),
    )
    dlg = DefineGridSystemDataDialog(existing=cs)
    qtbot.addWidget(dlg)

    result = dlg.system()
    assert result.name == "Floor2"
    assert result.coord.origin == (0.0, 0.0, 3.5)
    assert result.grid.x_lines == [0.0, 4.0, 8.0]
    assert result.grid.y_lines == [0.0, 6.0]
    assert result.grid.z_lines == [0.0]
    assert result.grid.glue_to_grid is True
    assert result.grid.bubble_size == 18


@pytest.mark.gui
def test_define_grid_data_spacing_mode_conversion(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Switching to Spacing mode and back must preserve ordinate values."""
    from opensees_studio.views.dialogs.define_grid_data import (
        DefineGridSystemDataDialog,
    )
    cs = CoordinateGridSystem(
        name="Test",
        grid=GridSystem(x_grid_lines=make_grid_lines("X", [0.0, 3.0, 6.0, 10.0])),
    )
    dlg = DefineGridSystemDataDialog(existing=cs)
    qtbot.addWidget(dlg)

    # Toggle to Spacing mode.
    dlg._rb_spacing.setChecked(True)
    # Then back to Ordinates.
    dlg._rb_ordinates.setChecked(True)
    result = dlg.system()
    assert result.grid.x_lines == pytest.approx([0.0, 3.0, 6.0, 10.0])


@pytest.mark.gui
def test_define_grid_data_global_name_locked(qtbot) -> None:  # type: ignore[no-untyped-def]
    """For the Global system, the Name field is disabled."""
    from opensees_studio.views.dialogs.define_grid_data import (
        DefineGridSystemDataDialog,
    )
    dlg = DefineGridSystemDataDialog(is_global=True)
    qtbot.addWidget(dlg)
    assert dlg._name_edit.text() == "Global"
    assert not dlg._name_edit.isEnabled()
    assert not dlg._btn_locate.isEnabled()


@pytest.mark.gui
def test_define_grid_data_add_and_delete_row(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Add Row / Delete Row buttons modify the X tab table directly."""
    from opensees_studio.views.dialogs.define_grid_data import (
        DefineGridSystemDataDialog,
    )
    dlg = DefineGridSystemDataDialog()
    qtbot.addWidget(dlg)
    # Start with empty X table.
    assert dlg._tab_x._table.rowCount() == 0
    dlg._tab_x._on_add_row()
    dlg._tab_x._on_add_row()
    assert dlg._tab_x._table.rowCount() == 2
    dlg._tab_x._table.selectRow(0)
    dlg._tab_x._on_delete_row()
    assert dlg._tab_x._table.rowCount() == 1


# ────────────────────── GridLine + migration tests ────────────────────
def test_grid_line_defaults() -> None:
    ln = GridLine(id="A", ordinate=3.0)
    assert ln.id == "A"
    assert ln.line_type == "Primary"
    assert ln.visible is True
    assert ln.bubble_loc == "End"
    assert ln.color == "#808080"


def test_grid_system_migrates_flat_x_lines() -> None:
    """Legacy constructor with list[float] must convert to GridLine records."""
    g = GridSystem(x_lines=[0.0, 2.5, 5.0])
    assert len(g.x_grid_lines) == 3
    ids = [ln.id for ln in g.x_grid_lines]
    assert ids == ["X1", "X2", "X3"]
    assert g.x_lines == [0.0, 2.5, 5.0]


def test_grid_system_hide_all_and_glue_persist() -> None:
    g = GridSystem(
        x_grid_lines=make_grid_lines("X", [0.0, 1.0]),
        hide_all=True,
        glue_to_grid=True,
        bubble_size=24,
    )
    d = g.model_dump()
    r = GridSystem.model_validate(d)
    assert r.hide_all is True
    assert r.glue_to_grid is True
    assert r.bubble_size == 24
