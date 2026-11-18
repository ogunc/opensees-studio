"""File → Import → IFC: what comes back from our own files, and from other programs'.

Three kinds of evidence:

* **Round trip.** Every example File → Export → IFC can write, and the export
  tests' bay (shells, releases, a truss, every kind of load, a combination),
  imports back to the same nodes, supports, members, section values, releases
  and loads.
* **Other programs' files**, built in ``tests/ifc_samples.py`` the way Tekla or
  Revit write them: kN and millimetres, moduli in MPa, an IPE profile that is not
  an AISC shape, a member turned 90°, plain load groups, global loads.
* **The physical model**, whose members meet at faces and have to be joined.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("ifcopenshell")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    Node,
    Project,
    ProjectMeta,
)
from opensees_studio.core.model_check import check_model
from opensees_studio.core.units import UnitSystem
from opensees_studio.services.ifc_export import export_ifc
from opensees_studio.services.ifc_import import (
    IfcImportError,
    IfcImportOptions,
    _aisc_candidates,
    import_ifc,
    inspect_ifc,
)
from opensees_studio.services.persistence import load_project
from tests.ifc_samples import analytical_portal, physical_frame

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

#: Examples with nothing IFC has a member for (plane quads, a zero-length section).
NOTHING_TO_EXPORT = {"beam_quad_2d", "moment_curvature"}
#: Loads on a node no member touches (a diaphragm's retained node) are not exported.
LOADS_LEFT_OUT = {"building_3storey_diaphragm"}

ROUND_TRIP = sorted(p.stem for p in EXAMPLES.glob("*.osmodel") if p.stem not in NOTHING_TO_EXPORT)
EXPORTED_TYPES = {
    "ElasticBeamColumn",
    "ForceBeamColumn",
    "DispBeamColumn",
    "BeamWithHinges",
    "Truss",
    "CorotTruss",
    "ShellMITC4",
}


def _close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


def _dofs(project: Project) -> list[int]:
    return [0, 2, 4] if project.ndm == 2 else list(range(6))


def _assert_same_model(src: Project, dst: Project, *, loads: bool = True) -> None:
    assert (dst.ndm, dst.ndf) == (src.ndm, src.ndf)
    original = {n.id: n for n in src.nodes}
    for node in dst.nodes:
        before = original[node.id]
        assert np.allclose(node.coords, before.coords, atol=1e-9), node.id
        assert [node.restraint[i] for i in _dofs(src)] == [before.restraint[i] for i in _dofs(src)]
        assert np.allclose(
            [node.spring[i] for i in _dofs(src)], [before.spring[i] for i in _dofs(src)]
        )
    elements = {e.id: e for e in src.elements}
    exported = {e.id for e in src.elements if e.type in EXPORTED_TYPES}
    assert {e.id for e in dst.elements} == exported
    for element in dst.elements:
        before = elements[element.id]
        assert tuple(element.nodes) == tuple(before.nodes), element.id
        assert element.name == before.name, element.id
        assert getattr(element, "geom_transf", None) == getattr(before, "geom_transf", None)
        if element.type == "ElasticBeamColumn" and before.type == "ElasticBeamColumn":
            a, b = src.section(before.section_id), dst.section(element.section_id)
            for key in ("E", "A", "Iz", "Iy", "G", "J"):
                assert _close(getattr(a, key), getattr(b, key)), (element.id, key)
            assert element.releases == before.releases, element.id
    if not loads:
        return
    for pattern in (p for p in src.load_patterns if p.type == "Plain"):
        twin = next(p for p in dst.load_patterns if p.name == pattern.name)
        total = lambda p: np.sum([nl.forces for nl in p.nodal_loads] or [np.zeros(6)], axis=0)  # noqa: E731
        assert np.allclose(total(twin), total(pattern)), pattern.name
        assert len(twin.element_loads) == len(pattern.element_loads)
        assert len(twin.point_loads) == len(pattern.point_loads)
        assert _close(twin.self_weight, pattern.self_weight)


# ──────────────────────────── round trip ────────────────────────────
@pytest.mark.parametrize("example", ROUND_TRIP)
def test_an_exported_example_imports_back_to_the_same_model(example: str, tmp_path: Path) -> None:
    src = load_project(EXAMPLES / f"{example}.osmodel")
    export_ifc(src, tmp_path / "model.ifc")
    imported = import_ifc(tmp_path / "model.ifc")

    assert imported.source == "analytical"
    assert imported.project.meta.units == src.meta.units
    _assert_same_model(src, imported.project, loads=example not in LOADS_LEFT_OUT)


def test_the_full_bay_round_trips_shells_releases_trusses_loads_and_combinations(
    tmp_path: Path,
) -> None:
    from tests.unit.test_ifc_export import _bay

    src, _ = _bay(tmp_path)
    dst = import_ifc(tmp_path / "bay.ifc").project
    _assert_same_model(src, dst)

    shell = next(e for e in dst.elements if e.type == "ShellMITC4")
    plate = dst.section(shell.section_id)
    assert (plate.E, plate.nu, plate.h) == (3e10, 0.2, 0.2)
    truss = next(e for e in dst.elements if e.type == "Truss")
    assert truss.area == pytest.approx(2e-3)
    assert pytest.approx(2e11) == dst.materials[truss.material_id - 1].E

    live = next(p for p in dst.load_patterns if p.name == "LIVE")
    assert live.element_loads[0].wz == pytest.approx(-2.0)
    assert live.surface_loads[0].value == pytest.approx(-4.0)
    assert live.surface_loads[0].direction == "Z"
    assert live.imposed_displacements[0].value == pytest.approx(-0.01)
    # The trapezoid comes back as itself; the floor load as the member loads it became.
    trapezoids = [
        d for d in live.distributed_loads if d.element_id == 3 and d.x_start == pytest.approx(0.2)
    ]
    assert trapezoids and trapezoids[0].wz_end == pytest.approx(-3.0)
    assert len(live.distributed_loads) > 1

    (combination,) = dst.combinations
    assert [(t.ref_id, t.factor) for t in combination.terms] == [(1, 1.2), (2, 1.6)]
    # The export's "Base" level is the base itself, not a floor: it does not come back.
    assert [(s.name, s.elevation) for s in dst.storeys] == [("First floor", 3.0)]
    assert not check_model(dst).has_errors


# ──────────────────────────── another program's analytical model ────────────────────────────
@pytest.fixture
def portal(tmp_path: Path) -> Path:
    return analytical_portal(tmp_path / "portal.ifc")


def test_the_inventory_says_what_the_file_holds(portal: Path) -> None:
    inventory = inspect_ifc(portal)

    assert inventory.schema == "IFC4"
    assert inventory.suggested_units is UnitSystem.SI_MM_N
    assert (inventory.point_connections, inventory.supports) == (6, 2)
    assert (inventory.analytical_members, inventory.analytical_surfaces) == (3, 1)
    assert (inventory.load_cases, inventory.combinations) == (3, 1)
    assert inventory.default_source() == "analytical"
    assert "millimetre" in inventory.summary()


def test_kilonewtons_and_millimetres_become_newtons_and_millimetres(portal: Path) -> None:
    imported = import_ifc(portal)
    project = imported.project

    assert project.meta.units is UnitSystem.SI_MM_N
    assert (project.ndm, project.ndf) == (3, 6)
    coords = {n.id: n.coords for n in project.nodes}
    assert coords[3] == (6000.0, 0.0, 4000.0)
    pinned = project.node(4)
    assert pinned.restraint == (True, True, True, False, False, False)
    assert pinned.spring[4] == pytest.approx(5000.0 * 1000.0)  # kN·mm → N·mm
    assert project.node(1).restraint == (True,) * 6


def test_moduli_in_mpa_and_a_yield_stress_are_read_with_their_unit(portal: Path) -> None:
    project = import_ifc(portal).project
    steel = next(s for s in project.sections if s.name == "IPE300")

    assert pytest.approx(210000.0) == steel.E  # MPa = N/mm²
    assert pytest.approx(210000.0 / 2.6) == steel.G
    assert steel.unit_weight == pytest.approx(7850 * 9.80665 * 1e-9)  # N/mm³
    (s355,) = [m for m in project.materials if m.type == "Steel01"]
    assert (s355.name, s355.Fy, s355.E0) == ("S355", pytest.approx(355.0), pytest.approx(210000.0))


def test_an_ipe_takes_its_dimensions_and_a_w_shape_the_aisc_table(portal: Path) -> None:
    project = import_ifc(portal).project
    ipe = next(s for s in project.sections if s.name == "IPE300")
    # Closed form of the IPE300 drawn without root fillets.
    area = 2 * 150 * 10.7 + (300 - 2 * 10.7) * 7.1
    strong = (150 * 300**3 - (150 - 7.1) * (300 - 2 * 10.7) ** 3) / 12
    assert pytest.approx(area) == ipe.A
    assert ipe.Iy == pytest.approx(strong)  # 3D: the depth stands along local z

    from opensees_studio.core.aisc import get_shape

    w = get_shape("W12X26")
    column = next(s for s in project.sections if s.name == "W12X26")
    assert pytest.approx(w.area * 25.4**2) == column.A
    assert column.Iy == pytest.approx(w.ix * 25.4**4)
    assert pytest.approx(w.j * 25.4**4) == column.J


def test_a_member_turned_90_degrees_gets_its_inertias_exchanged(portal: Path) -> None:
    imported = import_ifc(portal)
    project = imported.project
    straight = next(s for s in project.sections if s.name == "W12X26")
    turned = next(s for s in project.sections if s.name == "W12X26 (rotated 90°)")

    assert (turned.Iz, turned.Iy) == (straight.Iy, straight.Iz)
    assert turned.shape is None  # the drawing hint would stand the wrong way
    assert any("turned 90°" in note for note in imported.notes)


def test_end_releases_and_loads_in_global_coordinates(portal: Path) -> None:
    project = import_ifc(portal).project
    beam = next(e for e in project.elements if e.type == "ElasticBeamColumn" and e.nodes == (2, 3))
    assert beam.releases.j.released == ("M3",)
    assert beam.releases.i.released == ()

    dead = next(p for p in project.load_patterns if p.name == "DEAD")
    (uniform,) = dead.element_loads
    assert (uniform.wx, uniform.wy, uniform.wz) == (0.0, 0.0, pytest.approx(-5.0))  # kN/m = N/mm
    (pressure,) = dead.surface_loads
    assert (pressure.direction, pressure.value) == ("Z", pytest.approx(-0.005))  # 5 kPa in N/mm²

    live = next(p for p in project.load_patterns if p.name == "LIVE")
    (point,) = live.point_loads
    assert (point.x, point.pz) == (pytest.approx(0.5), pytest.approx(-20000.0))
    (nodal,) = live.nodal_loads
    assert (nodal.node_id, nodal.forces[0]) == (2, pytest.approx(10000.0))

    self_weight = next(p for p in project.load_patterns if p.name == "SELF")
    assert self_weight.self_weight == 1.0
    assert [c.pattern_ids for c in project.analyses] == [[1], [2], [3]]
    (uls,) = project.combinations
    assert [(t.ref_id, t.factor) for t in uls.terms] == [(1, 1.2), (2, 1.6)]


def test_a_material_without_properties_gets_its_kind_s_defaults_and_says_so(portal: Path) -> None:
    imported = import_ifc(portal)
    shell = next(e for e in imported.project.elements if e.type == "ShellMITC4")
    slab = imported.project.section(shell.section_id)

    assert (slab.h, slab.E, slab.nu) == (200.0, pytest.approx(24900.0), 0.2)
    assert any("C30/37" in note and "concrete defaults" in note for note in imported.notes)


def test_the_project_units_can_be_chosen(portal: Path) -> None:
    project = import_ifc(portal, IfcImportOptions(units=UnitSystem.SI_M_N)).project

    assert project.node(3).coords == (6.0, 0.0, 4.0)
    assert pytest.approx(2.1e11) == next(s for s in project.sections if s.name == "IPE300").E
    assert project.node(4).spring[4] == pytest.approx(5000.0)  # kN·mm = N·m
    dead = next(p for p in project.load_patterns if p.name == "DEAD")
    assert dead.element_loads[0].wz == pytest.approx(-5000.0)


def test_shells_and_loads_can_be_left_out(portal: Path) -> None:
    imported = import_ifc(portal, IfcImportOptions(include_shells=False, include_loads=False))

    assert all(e.type != "ShellMITC4" for e in imported.project.elements)
    assert imported.project.load_patterns == []
    assert imported.dropped["surface member (shells not requested)"] == 1


def test_another_program_s_portal_passes_the_model_check(portal: Path) -> None:
    assert check_model(import_ifc(portal).project).is_clean


# ──────────────────────────── the physical model ────────────────────────────
@pytest.fixture
def frame(tmp_path: Path) -> Path:
    return physical_frame(tmp_path / "frame.ifc")


def _node_at(project: Project, xyz: tuple[float, float, float]) -> int:
    for node in project.nodes:
        if np.allclose(node.coords, xyz, atol=1e-6):
            return node.id
    raise AssertionError(f"no node at {xyz}: {[n.coords for n in project.nodes]}")


def test_members_drawn_to_their_faces_are_joined_on_the_axes(frame: Path) -> None:
    imported = import_ifc(frame)
    project = imported.project
    assert imported.source == "physical"

    top_c1 = _node_at(project, (0.0, 0.0, 4000.0))
    top_c2 = _node_at(project, (6000.0, 0.0, 4000.0))
    top_c3 = _node_at(project, (3000.0, 4000.0, 4000.0))
    mid_b1 = _node_at(project, (3000.0, 0.0, 4000.0))
    frames = {tuple(e.nodes) for e in project.elements if e.type == "ElasticBeamColumn"}
    # B1 split where B2 lands, B2 from that point to C3's top.
    assert {(top_c1, mid_b1), (mid_b1, top_c2), (mid_b1, top_c3)} <= frames
    assert len(frames) == 6
    assert any("Axes joined: 4 member end(s)" in note for note in imported.notes)


def test_the_column_bases_are_fixed_unless_asked_not_to(frame: Path) -> None:
    fixed = import_ifc(frame).project
    bases = [_node_at(fixed, (x, y, 0.0)) for x, y in ((0, 0), (6000, 0), (3000, 4000))]
    assert all(fixed.node(n).restraint == (True,) * 6 for n in bases)
    assert check_model(fixed).is_clean

    free = import_ifc(frame, IfcImportOptions(fix_column_bases=False)).project
    assert not any(any(n.restraint) for n in free.nodes)
    assert check_model(free).has_errors  # a rigid body, as the model check says


def test_slab_and_wall_corners_attach_to_member_nodes(frame: Path) -> None:
    imported = import_ifc(frame)
    project = imported.project
    shells = [e for e in project.elements if e.type == "ShellMITC4"]
    assert len(shells) == 2
    slab = next(s for s in shells if _node_at(project, (3000.0, 0.0, 4000.0)) in s.nodes)
    assert _node_at(project, (0.0, 0.0, 4000.0)) in slab.nodes
    assert _node_at(project, (3000.0, 4000.0, 4000.0)) in slab.nodes
    wall = next(s for s in shells if s is not slab)
    assert {_node_at(project, (0.0, 0.0, 0.0)), _node_at(project, (6000.0, 0.0, 0.0))} <= set(
        wall.nodes
    )
    assert project.section(wall.section_id).h == pytest.approx(200.0)
    assert any("Edit → Mesh" in note for note in imported.notes)


def test_a_column_turned_90_degrees_is_seen_in_the_physical_model_too(frame: Path) -> None:
    project = import_ifc(frame).project
    c2 = next(
        e
        for e in project.elements
        if e.nodes
        == (_node_at(project, (6000.0, 0.0, 0.0)), _node_at(project, (6000.0, 0.0, 4000.0)))
    )
    assert project.section(c2.section_id).name == "W12X26 (rotated 90°)"


def test_our_own_physical_model_rebuilds_the_frame(tmp_path: Path) -> None:
    """The export draws members centred on their axes: joined, they are the model again."""
    src = load_project(EXAMPLES / "space_frame_3d.osmodel")
    export_ifc(src, tmp_path / "frame.ifc")
    project = import_ifc(tmp_path / "frame.ifc", IfcImportOptions(source="physical")).project

    assert len(project.elements) == len(src.elements)
    original = {tuple(np.round(n.coords, 9)) for n in src.nodes}
    assert {tuple(np.round(n.coords, 9)) for n in project.nodes} == original


# ──────────────────────────── names and errors ────────────────────────────
def test_aisc_names_are_found_in_type_names_and_any_case() -> None:
    assert "W14X90" in _aisc_candidates(["W-Wide Flange:W14x90"])
    assert "W14X90" in _aisc_candidates(["w14 × 90"])


def test_a_file_that_is_not_ifc_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "notes.ifc"
    path.write_text("this is not a STEP file")
    with pytest.raises(IfcImportError, match="not a readable IFC file"):
        inspect_ifc(path)


def test_asking_for_a_model_the_file_does_not_have_is_an_error(frame: Path) -> None:
    with pytest.raises(IfcImportError, match="no structural analysis model"):
        import_ifc(frame, IfcImportOptions(source="analytical"))


def test_a_local_axis_rotation_round_trips_in_both_models(tmp_path: Path) -> None:
    project = Project(
        meta=ProjectMeta(units=UnitSystem.SI_M_N),
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(6.0, 0.0, 0.0), restraint=(True,) * 6),
        ],
        sections=[
            ElasticSection(
                id=1,
                name="SEC",
                E=2.0e11,
                A=0.01,
                Iz=2.0e-4,
                Iy=1.0e-4,
                G=8.0e10,
                J=3.0e-4,
            )
        ],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1, local_axis_angle=30.0)],
    )
    path = tmp_path / "rolled.ifc"
    export_ifc(project, path)
    for source in ("analytical", "physical"):
        imported = import_ifc(path, IfcImportOptions(source=source)).project
        element = imported.elements[0]
        assert element.local_axis_angle == pytest.approx(30.0), source
        section = imported.sections[0]
        assert section.Iz == pytest.approx(2.0e-4), source
        assert section.Iy == pytest.approx(1.0e-4), source
