"""AISC 358-22 RBS connections: geometry limits, Z_RBS and the project entity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opensees_studio.core import Project, UnitSystem
from opensees_studio.core.design.connections import (
    RbsConnection,
    rbs_flexure_ratio,
    rbs_geometry,
    rbs_limits,
    rbs_mf,
    rbs_mpe,
    rbs_mpr,
    rbs_protected_zone,
    rbs_radius,
)
from opensees_studio.services import load_project, save_project
from opensees_studio.services.steel_design import shape_in_units


def _beam():  # type: ignore[no-untyped-def]
    return shape_in_units("W18X50", UnitSystem.US_IN_KIP)


def _connection(**kw: float) -> RbsConnection:
    values = {"id": 1, "beam_element_id": 2, "column_element_id": 1}
    values.update({"a": 4.5, "b": 13.0, "c": 1.0})
    values.update(kw)
    return RbsConnection(**values)  # type: ignore[arg-type]


def test_rbs_limits_follow_5_7_1_to_5_7_3() -> None:
    shape = _beam()
    limits = rbs_limits(shape)
    assert limits["a"] == pytest.approx((0.5 * shape.bf, 0.75 * shape.bf))
    assert limits["b"] == pytest.approx((0.65 * shape.d, 0.85 * shape.d))
    assert limits["c"] == pytest.approx((0.1 * shape.bf, 0.25 * shape.bf))


def test_rbs_geometry_computes_z_rbs_and_sh() -> None:
    shape = _beam()
    geometry = rbs_geometry(_connection(), shape)
    assert geometry.sh == pytest.approx(4.5 + 13.0 / 2.0)
    assert geometry.z_rbs == pytest.approx(shape.Zx - 2.0 * 1.0 * shape.tf * (shape.d - shape.tf))
    assert geometry.z_rbs < shape.Zx


def test_rbs_mpr_mf_radius_and_protected_zone() -> None:
    shape = _beam()
    geometry = rbs_geometry(_connection(), shape)
    probable = rbs_mpr(geometry, ry=1.1, fy=50.0, fu=65.0)
    assert probable == pytest.approx(1.15 * 1.1 * 50.0 * geometry.z_rbs)
    assert rbs_mf(geometry, probable, 40.0) == pytest.approx(probable + 40.0 * geometry.sh)
    assert rbs_radius(geometry) == pytest.approx((4.0 * 1.0**2 + 13.0**2) / 8.0)
    assert rbs_protected_zone(geometry) == (0.0, pytest.approx(4.5 + 13.0))


@pytest.mark.parametrize(
    ("field", "value"),
    [("a", 1.0), ("b", 5.0), ("c", 3.0)],
)
def test_an_out_of_limit_cut_is_refused(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=f"RBS {field}"):
        rbs_geometry(_connection(**{field: value}), _beam())


def test_the_entity_round_trips_with_the_project(tmp_path: Path) -> None:
    project = Project()
    project.connections = [
        RbsConnection(
            id=3, name="RBS-1", beam_element_id=2, column_element_id=1, a=4.5, b=13.0, c=1.0
        )
    ]
    path = save_project(project, tmp_path / "rbs.osmodel")
    saved = json.loads(path.read_text(encoding="utf-8"))["connections"]
    assert saved[0]["name"] == "RBS-1" and saved[0]["a"] == 4.5
    assert load_project(path).connections == project.connections


def test_a_project_without_connections_saves_without_the_field(tmp_path: Path) -> None:
    path = save_project(Project(), tmp_path / "plain.osmodel")
    assert "connections" not in json.loads(path.read_text(encoding="utf-8"))


def test_next_connection_id_and_reference_validation() -> None:
    project = Project()
    project.connections = [
        RbsConnection(id=1, beam_element_id=2, column_element_id=1, a=4.5, b=13.0, c=1.0)
    ]
    assert project.next_connection_id() == 2
    with pytest.raises(ValueError, match="beam element 2 does not exist"):
        project.validate_references()


def test_mpe_and_the_flexure_ratio() -> None:
    assert rbs_mpe(1.1, 50.0, 100.0) == pytest.approx(5500.0)
    assert rbs_flexure_ratio(5000.0, 5500.0) == pytest.approx(5000.0 / 5500.0)
    assert rbs_flexure_ratio(5000.0, 5500.0, method="ASD") == pytest.approx(5000.0 / (5500.0 / 1.5))
