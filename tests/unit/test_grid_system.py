"""Unit tests for the SAP2000-style grid system (pure logic, no Qt platform).

The dialog, command and snap tests that need a QApplication live in
``tests/gui/test_grid_system_gui.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opensees_studio.core import (
    CoordinateGridSystem,
    CoordinateSystem,
    GridSystem,
    Node,
    Project,
    default_global_system,
)
from opensees_studio.services import load_project, save_project


def test_empty_grid_default() -> None:
    g = GridSystem()
    assert g.x_lines == [] and g.y_lines == [] and g.z_lines == []
    assert g.visible is True


def test_grid_sorts_and_dedupes() -> None:
    g = GridSystem(x_lines=[3.0, 1.0, 2.0, 1.0 + 1e-12, 2.0])
    assert g.x_lines == [1.0, 2.0, 3.0]


def test_grid_bounds() -> None:
    g = GridSystem(x_lines=[0, 4, 8], y_lines=[-1, 1], z_lines=[])
    (xmin, xmax), (ymin, ymax), (zmin, zmax) = g.bounds()
    assert (xmin, xmax) == (0, 8)
    assert (ymin, ymax) == (-1, 1)
    assert (zmin, zmax) == (0, 0)


def test_project_default_has_empty_grid() -> None:
    p = Project()
    assert isinstance(p.grid_system, GridSystem)
    assert p.grid_system.x_lines == []


def test_grid_round_trips(tmp_path: Path) -> None:
    p = Project(
        nodes=[Node(id=1, coords=(0, 0, 0))],
        grid_system=GridSystem(
            x_lines=[0.0, 3.0, 6.0, 9.0],
            y_lines=[0.0, 4.0, 8.0],
            z_lines=[0.0, 3.0],
            visible=False,
        ),
    )
    path = tmp_path / "with_grid.osmodel"
    save_project(p, path)
    r = load_project(path)
    assert r.grid_system.x_lines == [0.0, 3.0, 6.0, 9.0]
    assert r.grid_system.y_lines == [0.0, 4.0, 8.0]
    assert r.grid_system.z_lines == [0.0, 3.0]
    assert r.grid_system.visible is False


def test_dialog_parse_spacings_formats() -> None:
    """Dialog parsers accept all three accepted forms."""
    from opensees_studio.views.dialogs.grid_system import (
        _coords_from_spacings,
        _parse_spacings,
    )

    # Blank → no lines.
    assert _parse_spacings("") == []
    # Single integer → N-1 unit spacings.
    assert _parse_spacings("4") == [1.0, 1.0, 1.0]
    # n@d syntax.
    assert _parse_spacings("3@2.5") == [2.5, 2.5, 2.5]
    # Comma list.
    assert _parse_spacings("1, 2, 3") == [1.0, 2.0, 3.0]

    # Spacings → absolute coordinates.
    assert _coords_from_spacings([2.5, 2.5, 2.5]) == [0.0, 2.5, 5.0, 7.5]


# ══════════════════════════ SAP2000-style coord systems ══════════════════
def test_default_project_has_global_system() -> None:
    p = Project()
    assert len(p.coord_systems) == 1
    assert p.coord_systems[0].name == "Global"
    assert p.coord_systems[0].is_global() is True


def test_global_is_auto_inserted_if_missing() -> None:
    # Construct a project whose only coord_system is named 'Floor2' —
    # the model validator must prepend a Global entry.
    p = Project(
        coord_systems=[
            CoordinateGridSystem(
                name="Floor2",
                coord=CoordinateSystem(origin=(0, 0, 3)),
            ),
        ],
    )
    names = [cs.name for cs in p.coord_systems]
    assert names[0] == "Global"
    assert "Floor2" in names


def test_coord_system_rotation_matrix_identity() -> None:
    cs = CoordinateSystem()
    m = cs.rotation_matrix()
    assert m[0] == [1.0, 0.0, 0.0]
    assert m[1] == [0.0, 1.0, 0.0]
    assert m[2] == [0.0, 0.0, 1.0]


def test_coord_system_z_rotation() -> None:
    cs = CoordinateSystem(rotation_deg=(0, 0, 90))
    wx = cs.local_to_world((1.0, 0.0, 0.0))
    assert wx[0] == pytest.approx(0.0, abs=1e-9)
    assert wx[1] == pytest.approx(1.0, abs=1e-9)


def test_coord_system_round_trip_world_local() -> None:
    cs = CoordinateSystem(origin=(2, 3, 5), rotation_deg=(10, 20, 30))
    p_local = (1.5, -0.5, 2.0)
    p_world = cs.local_to_world(p_local)
    p_back = cs.world_to_local(p_world)
    for a, b in zip(p_local, p_back, strict=True):
        assert a == pytest.approx(b, abs=1e-9)


def test_legacy_grid_system_field_migrates() -> None:
    """An .osmodel written with the old schema must still load correctly."""
    raw = {
        "nodes": [],
        "materials": [],
        "sections": [],
        "elements": [],
        "time_series": [],
        "load_patterns": [],
        "spectra": [],
        "analyses": [],
        "grid_system": {
            "x_lines": [0.0, 3.0, 6.0],
            "y_lines": [0.0, 4.0],
            "z_lines": [],
            "visible": True,
        },
    }
    p = Project.model_validate(raw)
    assert p.coord_systems[0].name == "Global"
    assert p.coord_systems[0].grid.x_lines == [0.0, 3.0, 6.0]
    # The property proxy still works.
    assert p.grid_system.x_lines == [0.0, 3.0, 6.0]


def test_multiple_coord_systems_round_trip(tmp_path: Path) -> None:
    p = Project(
        coord_systems=[
            default_global_system(),
            CoordinateGridSystem(
                name="Floor2",
                coord=CoordinateSystem(
                    origin=(0, 0, 3.5),
                    rotation_deg=(0, 0, 30),
                ),
                grid=GridSystem(x_lines=[0.0, 6.0], y_lines=[0.0, 4.0]),
            ),
        ],
    )
    path = tmp_path / "multi.osmodel"
    save_project(p, path)
    r = load_project(path)
    assert [cs.name for cs in r.coord_systems] == ["Global", "Floor2"]
    floor2 = r.coord_systems[1]
    assert floor2.coord.origin == (0.0, 0.0, 3.5)
    assert floor2.coord.rotation_deg == (0.0, 0.0, 30.0)
    assert floor2.grid.x_lines == [0.0, 6.0]
