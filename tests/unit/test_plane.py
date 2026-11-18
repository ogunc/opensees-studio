"""Z is the elevation axis: a 2D model lives in the X-Z plane (core.plane)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opensees_studio.core import NodalLoad, Node, PlainLoadPattern, Project
from opensees_studio.core.plane import (
    dof_indices,
    dof_labels,
    dof_signs,
    force_labels,
    from_solver_dofs,
    from_solver_vector3,
    migrate_2d_payload_to_xz,
    to_solver_coords,
    to_solver_dofs,
    to_solver_vector3,
    translation_from_dofs,
)
from opensees_studio.services.persistence import SCHEMA_VERSION, load_project


def test_a_2d_model_is_x_z_with_ux_uz_ry() -> None:
    assert dof_indices(2, 3) == (0, 2, 4)
    assert dof_indices(2, 2) == (0, 2)
    assert dof_labels(2, 3) == ("Ux", "Uz", "Ry")
    assert force_labels(2, 3) == ("Fx", "Fz", "My")
    assert dof_labels(3, 6) == ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")


def test_only_the_2d_rotation_changes_sign_on_the_way_to_opensees() -> None:
    # OpenSees' rz turns x toward y, i.e. X toward Z: a rotation about -Y.
    assert dof_signs(2, 3) == (1.0, 1.0, -1.0)
    assert dof_signs(2, 2) == (1.0, 1.0)
    assert dof_signs(3, 6) == (1.0,) * 6


def test_coordinates_and_vectors_reach_opensees_as_x_z() -> None:
    assert to_solver_coords((3.0, 0.0, 4.0), 2) == (3.0, 4.0)
    assert to_solver_coords((3.0, 1.0, 4.0), 3) == (3.0, 1.0, 4.0)
    # OpenSees' 2D (x, y, z) are the global X, Z and -Y.
    assert to_solver_vector3((1.0, 2.0, 3.0), 2) == (1.0, 3.0, -2.0)
    assert from_solver_vector3(to_solver_vector3((1.0, 2.0, 3.0), 2), 2) == (1.0, 2.0, 3.0)


def test_loads_and_results_round_trip_through_the_solver_dofs() -> None:
    load = (10.0, 0.0, -5.0, 0.0, 7.0, 0.0)  # Fx, Fz and My of a 2D frame
    assert to_solver_dofs(load, 2, 3) == (10.0, -5.0, -7.0)
    assert from_solver_dofs((10.0, -5.0, -7.0), 2, 3) == load
    assert list(translation_from_dofs((0.1, -0.2, 0.3), 2, 3)) == [0.1, 0.0, -0.2]


def _legacy_2d_payload() -> dict:
    """A schema 2 2D portal: X-Y plane, Y up, as files were written before Z-up."""
    return {
        "schema_version": 2,
        "ndm": 2,
        "ndf": 3,
        "coord_systems": [
            {
                "name": "Global",
                "coord": {"origin": [1.0, 2.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]},
                "grid": {
                    "x_grid_lines": [{"id": "X1", "ordinate": 0.0}, {"id": "X2", "ordinate": 6.0}],
                    "y_grid_lines": [{"id": "Y1", "ordinate": 0.0}, {"id": "Y2", "ordinate": 3.0}],
                    "z_grid_lines": [{"id": "Z1", "ordinate": 0.0}],
                },
            }
        ],
        "nodes": [
            {
                "id": 1,
                "coords": [0.0, 0.0, 0.0],
                "restraint": [True, True, False, False, False, True],
            },
            {
                "id": 2,
                "coords": [0.0, 3.0, 0.0],
                "mass": [5.0, 5.0, 0.0, 0.0, 0.0, 0.25],
            },
        ],
        "time_series": [{"id": 1, "type": "Linear"}],
        "load_patterns": [
            {
                "id": 1,
                "type": "Plain",
                "time_series_id": 1,
                "nodal_loads": [{"node_id": 2, "forces": [10.0, -20.0, 0.0, 0.0, 0.0, 3.0]}],
            }
        ],
    }


def test_a_legacy_2d_payload_turns_into_the_x_z_plane() -> None:
    payload = _legacy_2d_payload()
    assert migrate_2d_payload_to_xz(payload)
    n1, n2 = payload["nodes"]
    assert n2["coords"] == [0.0, 0.0, 3.0]
    # Restraints and masses follow their axes: Uy -> Uz, Rz -> Ry.
    assert n1["restraint"] == [True, False, True, False, True, False]
    assert n2["mass"] == [5.0, 0.0, 5.0, 0.0, 0.25, 0.0]
    # The same physical load: Fy -> Fz, and Mz -> My = -Mz.
    assert payload["load_patterns"][0]["nodal_loads"][0]["forces"] == [
        10.0,
        0.0,
        -20.0,
        0.0,
        -3.0,
        0.0,
    ]
    grid = payload["coord_systems"][0]["grid"]
    assert [(g["id"], g["ordinate"]) for g in grid["z_grid_lines"]] == [("Z1", 0.0), ("Z2", 3.0)]
    assert [(g["id"], g["ordinate"]) for g in grid["y_grid_lines"]] == [("Y1", 0.0)]
    assert payload["coord_systems"][0]["coord"]["origin"] == [1.0, 0.0, 2.0]


def test_a_migrated_payload_is_a_valid_project_and_migrates_once() -> None:
    payload = _legacy_2d_payload()
    migrate_2d_payload_to_xz(payload)
    project = Project.model_validate(payload)
    project.validate_references()
    assert payload["schema_version"] == 3
    assert not migrate_2d_payload_to_xz(payload)


def test_3d_payloads_are_left_alone() -> None:
    payload = {"schema_version": 2, "ndm": 3, "ndf": 6, "nodes": [{"id": 1, "coords": [1, 2, 3]}]}
    assert not migrate_2d_payload_to_xz(payload)
    assert payload["nodes"][0]["coords"] == [1, 2, 3]


def test_opening_a_legacy_2d_file_says_so_and_saving_writes_schema_3(tmp_path: Path) -> None:
    path = tmp_path / "legacy.osmodel"
    path.write_text(json.dumps(_legacy_2d_payload()), encoding="utf-8")
    notices: list[str] = []
    project = load_project(path, on_notice=notices.append)
    assert project.nodes[1].coords == (0.0, 0.0, 3.0)
    assert any("X-Z plane" in n for n in notices)
    assert SCHEMA_VERSION == 3 and project.schema_version == 3


def test_a_2d_node_off_the_x_z_plane_is_refused_before_a_run() -> None:
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(0.0, 3.0, 0.0))],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0))],
            )
        ],
    )
    with pytest.raises(ValueError, match="X-Z plane"):
        project.validate_references()
