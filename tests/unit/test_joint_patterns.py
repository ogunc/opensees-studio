"""Joint patterns and the surface loads that vary by them.

What is pinned here:

* the values: ``A·x + B·y + C·z + D``, hydrostatic ``w·(Z₀ - z) + q``, the
  restrictions and the add / replace / delete merge, as SAP2000 defines them;
* the load: a pressure by joint pattern reaches the nodes as consistent forces
  whose resultant *and* point of application are exact (a hydrostatic wall puts
  its resultant at a third of the depth), and a pattern of ones is the uniform
  load;
* the file: a project without joint patterns, and a uniform surface load, save
  byte-identical to before; a missing pattern is a reference error;
* SAP2000 text: ``JOINT PATTERN DEFINITIONS``/``ASSIGNMENTS``, ``AREA LOADS -
  UNIFORM`` and ``AREA LOADS - SURFACE PRESSURE`` (``Face``, ``Pressure``,
  ``JtPattern``) are read and written, written by hand here from the table
  format, and a model goes out and back with the same nodal forces;
* IFC: a pressure by pattern is a ``DISCRETE`` planar action with its corner
  values, valid against the IFC4 schema.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from opensees_studio.core import (
    ElasticMembranePlateSection,
    JointPattern,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    Project,
    ShellMITC4Element,
    SurfaceLoad,
)
from opensees_studio.core.area_loads import (
    quad_shape_products,
    surface_corner_pressures,
    surface_nodal_loads,
)
from opensees_studio.core.joint_patterns import (
    assign,
    copy_to_new_nodes,
    follow_merged_nodes,
    hydrostatic_values,
    interpolate_new_nodes,
    interpolate_on_quad,
    plane_values,
    prune_joint_patterns,
    restrict,
)
from opensees_studio.core.self_weight import quad_tributary_areas
from opensees_studio.core.units import UnitSystem

FIXED = (True,) * 6
WATER = 9810.0  # N/m³
HEIGHT, WIDTH = 3.0, 2.0


def _wall(*, pattern_values: dict[int, float] | None = None, value: float = 1.0) -> Project:
    """A 2 m wide, 3 m tall wall in the X-Z plane, normal along -Y (nodes 1-2-3-4)."""
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=FIXED),
        Node(id=2, coords=(WIDTH, 0.0, 0.0), restraint=FIXED),
        Node(id=3, coords=(WIDTH, 0.0, HEIGHT)),
        Node(id=4, coords=(0.0, 0.0, HEIGHT)),
    ]
    if pattern_values is None:
        pattern_values = hydrostatic_values({n.id: n.coords for n in nodes}, HEIGHT, WATER)
    return Project(
        nodes=nodes,
        sections=[ElasticMembranePlateSection(id=1, name="Wall", E=3e10, nu=0.2, h=0.2)],
        elements=[ShellMITC4Element(id=1, nodes=(1, 2, 3, 4), section_id=1)],
        # Through assign(), as the dialog does: a zero is not stored.
        joint_patterns=[assign(JointPattern(id=1, name="WATER"), pattern_values, "replace")],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="HYDRO",
                time_series_id=1,
                surface_loads=[
                    SurfaceLoad(element_id=1, value=value, direction="normal", joint_pattern_id=1)
                ],
            )
        ],
    )


# ──────────────────────────── values ────────────────────────────
def test_plane_values_are_a_linear_function_of_the_coordinates() -> None:
    values = plane_values({1: (1.0, 2.0, 3.0), 2: (0.0, 0.0, 0.0)}, 1.0, 10.0, 100.0, 0.5)
    assert values == {1: 321.5, 2: 0.5}


def test_hydrostatic_values_grow_with_depth_below_the_free_surface() -> None:
    values = hydrostatic_values({1: (0, 0, 0.0), 2: (0, 0, 1.0), 3: (0, 0, 4.0)}, 3.0, WATER, 100.0)
    assert values == {1: 3 * WATER + 100.0, 2: 2 * WATER + 100.0, 3: -WATER + 100.0}


def test_restrictions_zero_the_negative_or_the_positive_values() -> None:
    values = {1: -2.0, 2: 0.0, 3: 5.0}
    assert restrict(values, "all") == values
    assert restrict(values, "zero_negative") == {1: 0.0, 2: 0.0, 3: 5.0}
    assert restrict(values, "zero_positive") == {1: -2.0, 2: 0.0, 3: 0.0}


def test_assign_adds_replaces_and_deletes_and_never_stores_a_zero() -> None:
    pattern = JointPattern(id=1, name="P", values={1: 1.0, 2: 2.0})

    assert assign(pattern, {2: 3.0, 3: 4.0}, "add").values == {1: 1.0, 2: 5.0, 3: 4.0}
    assert assign(pattern, {2: 3.0}, "replace").values == {1: 1.0, 2: 3.0}
    assert assign(pattern, {2: 99.0}, "delete").values == {1: 1.0}
    assert assign(pattern, {1: -1.0}, "add").values == {2: 2.0}  # 1 - 1 = 0: gone
    assert pattern.values == {1: 1.0, 2: 2.0}  # the original is untouched
    assert pattern.value(42) == 0.0


# ──────────────────────────── the load ────────────────────────────
def test_shape_products_sum_to_the_tributary_areas_on_a_warped_quad() -> None:
    points = np.array([[0, 0, 0], [3, 0, 0.2], [3.5, 0.1, 2], [0.2, 0, 2.5]], dtype=float)
    assert np.allclose(quad_shape_products(points).sum(axis=1), quad_tributary_areas(points))


def test_a_hydrostatic_wall_carries_the_exact_resultant_at_a_third_of_the_depth() -> None:
    project = _wall()
    forces = surface_nodal_loads(project, project.load_patterns[0].surface_loads)

    total = sum(forces.values())
    resultant = 0.5 * WATER * HEIGHT**2 * WIDTH  # triangle of pressure, times the width
    assert total == pytest.approx(np.array([0.0, -resultant, 0.0]))  # along the normal, -Y
    z = {n.id: n.coords[2] for n in project.nodes}
    lever = sum(float(f[1]) * z[n] for n, f in forces.items()) / float(total[1])
    assert lever == pytest.approx(HEIGHT / 3)


def test_the_deep_corners_take_two_thirds_of_a_hydrostatic_load() -> None:
    project = _wall()
    forces = surface_nodal_loads(project, project.load_patterns[0].surface_loads)
    resultant = 0.5 * WATER * HEIGHT**2 * WIDTH
    assert -float(forces[1][1] + forces[2][1]) == pytest.approx(2 / 3 * resultant)
    assert -float(forces[3][1] + forces[4][1]) == pytest.approx(1 / 3 * resultant)


def test_a_pattern_of_ones_is_the_uniform_load_and_the_multiplier_scales_it() -> None:
    by_pattern = _wall(pattern_values={1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0}, value=-5.0)
    uniform = _wall(value=-5.0)
    uniform.load_patterns[0].surface_loads[0] = SurfaceLoad(
        element_id=1, value=-5.0, direction="normal"
    )
    a = surface_nodal_loads(by_pattern, by_pattern.load_patterns[0].surface_loads)
    b = surface_nodal_loads(uniform, uniform.load_patterns[0].surface_loads)
    assert all(np.allclose(a[n], b[n]) for n in a)


def test_corner_pressures_are_the_multiplier_times_the_values_and_zero_where_none() -> None:
    project = _wall(pattern_values={1: 2.0, 2: 3.0}, value=10.0)
    load = project.load_patterns[0].surface_loads[0]
    assert surface_corner_pressures(project, load).tolist() == [20.0, 30.0, 0.0, 0.0]


# ──────────────────────────── the file ────────────────────────────
def test_no_pattern_and_a_uniform_load_save_as_before() -> None:
    project = Project()
    assert "joint_patterns" not in project.model_dump_json()
    assert SurfaceLoad(element_id=1, value=2.0).model_dump() == {
        "element_id": 1,
        "value": 2.0,
        "direction": "Z",
    }


def test_a_project_with_a_pattern_round_trips_through_json() -> None:
    project = _wall()
    again = Project.model_validate_json(project.model_dump_json())
    assert again.joint_patterns == project.joint_patterns
    assert again.load_patterns[0].surface_loads[0].joint_pattern_id == 1
    assert json.loads(project.model_dump_json())["joint_patterns"][0]["values"][
        "1"
    ] == pytest.approx(3 * WATER)


def test_a_load_on_a_missing_pattern_is_a_reference_error() -> None:
    project = _wall()
    project.joint_patterns.clear()
    with pytest.raises(ValueError, match="missing joint pattern 1"):
        project.validate_references()


def test_two_patterns_with_the_same_id_are_refused() -> None:
    with pytest.raises(ValueError, match="Duplicate joint pattern ids"):
        Project(joint_patterns=[JointPattern(id=1), JointPattern(id=1)])


# ──────────────────────────── keeping in step with the nodes ────────────────────────────
def test_pruning_drops_the_values_of_deleted_nodes() -> None:
    project = _wall()
    project.nodes[:] = [n for n in project.nodes if n.id != 2]
    assert prune_joint_patterns(project)
    assert 2 not in project.joint_patterns[0].values
    assert not prune_joint_patterns(project)


def test_a_merged_node_s_value_goes_to_its_keeper_unless_the_keeper_has_one() -> None:
    project = _wall(pattern_values={1: 5.0, 2: 7.0, 3: 9.0})
    follow_merged_nodes(project, {2: 1, 3: 4})
    assert project.joint_patterns[0].values == {1: 5.0, 4: 9.0}


def test_copied_nodes_take_their_source_s_value() -> None:
    project = _wall(pattern_values={1: 5.0})
    copy_to_new_nodes(project, {1: 11, 2: 12})
    assert project.joint_patterns[0].values == {1: 5.0, 11: 5.0}


def test_new_nodes_inside_a_shell_get_the_interpolated_value() -> None:
    project = _wall()
    corners = np.array([n.coords for n in project.nodes], dtype=float)
    middle = np.array([1.0, 0.0, 1.5])
    added = interpolate_new_nodes(project, {9: (corners, (1, 2, 3, 4))}, {9: middle})

    assert added == 1
    assert project.joint_patterns[0].value(9) == pytest.approx(WATER * 1.5)


def test_interpolation_finds_a_point_on_a_skewed_quad() -> None:
    corners = np.array([[0, 0, 0], [4, 0, 0], [5, 0, 3], [1, 0, 3]], dtype=float)
    # Field f = z: bilinear reproduces it exactly.
    assert interpolate_on_quad(corners, [0, 0, 3, 3], np.array([2.6, 0.0, 1.2])) == pytest.approx(
        1.2
    )


# ──────────────────────────── SAP2000 text ────────────────────────────
_TANK_WALL = """\
TABLE:  "PROGRAM CONTROL"
   ProgramName=SAP2000   CurrUnits="KN, m, C"
TABLE:  "JOINT COORDINATES"
   Joint=1   CoordSys=GLOBAL   CoordType=Cartesian   XorR=0   Y=0   Z=0
   Joint=2   CoordSys=GLOBAL   CoordType=Cartesian   XorR=2   Y=0   Z=0
   Joint=3   CoordSys=GLOBAL   CoordType=Cartesian   XorR=2   Y=0   Z=3
   Joint=4   CoordSys=GLOBAL   CoordType=Cartesian   XorR=0   Y=0   Z=3
TABLE:  "JOINT RESTRAINT ASSIGNMENTS"
   Joint=1   U1=Yes   U2=Yes   U3=Yes   R1=Yes   R2=Yes   R3=Yes
   Joint=2   U1=Yes   U2=Yes   U3=Yes   R1=Yes   R2=Yes   R3=Yes
TABLE:  "MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES"
   Material=C   UnitWeight=0   UnitMass=0   E1=30000000   G12=12500000   U12=0.2
TABLE:  "AREA SECTION PROPERTIES"
   Section=W   Material=C   AreaType=Shell   Type=Shell-Thin   Thickness=0.2   BendThick=0.2
TABLE:  "CONNECTIVITY - AREA"
   Area=1   NumJoints=4   Joint1=1   Joint2=2   Joint3=3   Joint4=4
TABLE:  "AREA SECTION ASSIGNMENTS"
   Area=1   Section=W   MatProp=Default
TABLE:  "LOAD PATTERN DEFINITIONS"
   LoadPat=HYDRO   DesignType=Other   SelfWtMult=0
   LoadPat=OTHER   DesignType=Other   SelfWtMult=0
TABLE:  "JOINT PATTERN DEFINITIONS"
   Pattern=Default
   Pattern=WATER
TABLE:  "JOINT PATTERN ASSIGNMENTS"
   Joint=1   Pattern=WATER   Value=29.43
   Joint=2   Pattern=WATER   Value=29.43
   Joint=3   Pattern=WATER   Value=0
   Joint=4   Pattern=WATER   Value=0
TABLE:  "AREA LOADS - SURFACE PRESSURE"
   Area=1   LoadPat=HYDRO   Face=Top   Pressure=1   JtPattern=WATER
   Area=1   LoadPat=OTHER   Face=Bottom   Pressure=2
TABLE:  "AREA LOADS - UNIFORM"
   Area=1   LoadPat=OTHER   CoordSys=GLOBAL   Dir=Gravity   UnifLoad=3
   Area=1   LoadPat=OTHER   CoordSys=GLOBAL   Dir=X   UnifLoad=4
   Area=1   LoadPat=OTHER   CoordSys=Local   Dir=3   UnifLoad=5
   Area=1   LoadPat=OTHER   CoordSys=Local   Dir=1   UnifLoad=6
END TABLE DATA
"""


@pytest.fixture
def tank_wall(tmp_path: Path) -> Path:
    path = tmp_path / "wall.s2k"
    path.write_text(_TANK_WALL, encoding="utf-8")
    return path


def test_sap2000_joint_patterns_and_area_loads_are_read(tank_wall: Path) -> None:
    from opensees_studio.services.sap2000_text import import_s2k

    imported = import_s2k(tank_wall)
    project = imported.project
    assert project.meta.units is UnitSystem.SI_M_N
    (water,) = project.joint_patterns  # "Default" has no value and no load: left out
    assert water.name == "WATER"
    assert water.values == {1: 29.43, 2: 29.43}  # zeros are what no value means

    hydro = next(p for p in project.load_patterns if p.name == "HYDRO")
    (pressure,) = hydro.surface_loads
    # A pressure on the Top face (+3 side) pushes along -3; kN/m² → N/m².
    assert (pressure.direction, pressure.value, pressure.joint_pattern_id) == (
        "normal",
        -1000.0,
        water.id,
    )

    other = next(p for p in project.load_patterns if p.name == "OTHER")
    loads = [(s.direction, s.value, s.joint_pattern_id) for s in other.surface_loads]
    assert ("normal", 2000.0, None) in loads  # Bottom face pushes along +3, by element
    assert ("Z", -3000.0, None) in loads  # gravity is -Z
    assert ("X", 4000.0, None) in loads
    assert ("normal", 5000.0, None) in loads  # local 3
    assert imported.dropped["area uniform load along 1 (Local)"] == 1
    assert "AREA LOADS" not in imported.summary()  # the tables are read now


def test_sap2000_out_and_back_gives_the_same_nodal_forces(tank_wall: Path, tmp_path: Path) -> None:
    from opensees_studio.services.sap2000_text import export_s2k, import_s2k

    first = import_s2k(tank_wall).project
    report = export_s2k(first, tmp_path / "again.s2k")
    assert report.written["joint pattern(s)"] == 1
    second = import_s2k(tmp_path / "again.s2k").project

    assert second.joint_patterns[0].values == first.joint_patterns[0].values
    for a, b in zip(first.load_patterns, second.load_patterns, strict=True):
        fa = surface_nodal_loads(first, a.surface_loads)
        fb = surface_nodal_loads(second, b.surface_loads)
        assert fa.keys() == fb.keys()
        assert all(np.allclose(fa[n], fb[n]) for n in fa), a.name


def test_a_pattern_pressure_along_a_global_axis_is_reported_by_the_sap2000_export(
    tmp_path: Path,
) -> None:
    from opensees_studio.services.sap2000_text import export_s2k

    project = _wall()
    project.load_patterns[0].surface_loads[0] = SurfaceLoad(
        element_id=1, value=1.0, direction="Y", joint_pattern_id=1
    )
    report = export_s2k(project, tmp_path / "w.s2k")
    assert any("global axis" in what for what in report.skipped)


# ──────────────────────────── IFC ────────────────────────────
def test_a_pattern_pressure_is_a_discrete_planar_action_in_ifc(tmp_path: Path) -> None:
    ifcopenshell = pytest.importorskip("ifcopenshell")
    validate = pytest.importorskip("ifcopenshell.validate")

    from opensees_studio.services.ifc_export import export_ifc

    project = _wall()
    export_ifc(project, tmp_path / "wall.ifc")
    f = ifcopenshell.open(str(tmp_path / "wall.ifc"))

    (action,) = f.by_type("IfcStructuralPlanarAction")
    assert action.PredefinedType == "DISCRETE"
    assert action.GlobalOrLocal == "LOCAL_COORDS"
    load = action.AppliedLoad
    assert [round(v.PlanarForceZ, 6) for v in load.Values] == [3 * WATER, 3 * WATER, 0.0, 0.0]
    assert [tuple(round(c, 9) for c in loc) for loc in load.Locations] == [
        (0.0, 0.0),
        (WIDTH, 0.0),
        (WIDTH, HEIGHT),
        (0.0, HEIGHT),
    ]

    class _Errors(list):  # type: ignore[type-arg]
        def error(self, msg, *args, **_kw):  # type: ignore[no-untyped-def]
            self.append(msg % args if args else msg)

        def warning(self, *a, **k):  # type: ignore[no-untyped-def]
            pass

        info = debug = warning

    errors = _Errors()
    validate.validate(f, errors)
    assert errors == []
