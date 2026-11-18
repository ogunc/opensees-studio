"""Line, edge and area springs: how they reach the nodes, and how they travel.

Pinned here: the tributary distribution (a raft on k carries k·A, a frame on k
carries k·L), the direction and the medium's side, contributions merging per
node, the model check counting them as support (and joint springs, which it used
to ignore), the edits that keep them in step, the file staying byte-identical
without them, and SAP2000's ``AREA SPRING ASSIGNMENTS`` read and written — the
columns written here by hand from the table format.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from opensees_studio.core import (
    AreaSpring,
    EdgeSpring,
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    LineSpring,
    Node,
    Project,
    ShellMITC4Element,
)
from opensees_studio.core.model_check import check_model
from opensees_studio.core.support_springs import (
    copy_support_springs,
    has_one_sided_springs,
    nodal_springs,
    prune_support_springs,
    springs_follow_pieces,
)

FREE = (False,) * 6
PLANE = (True, True, False, False, False, True)  # held in X, Y and about Z: only Uz, Rx, Ry free


def _raft(n: int = 2, size: float = 4.0, **spring: object) -> Project:
    nodes, ids = [], {}
    for j in range(n + 1):
        for i in range(n + 1):
            ids[(i, j)] = len(nodes) + 1
            nodes.append(
                Node(id=len(nodes) + 1, coords=(size * i / n, size * j / n, 0.0), restraint=PLANE)
            )
    shells = [
        ShellMITC4Element(
            id=100 + i + j * n,
            nodes=(ids[(i, j)], ids[(i + 1, j)], ids[(i + 1, j + 1)], ids[(i, j + 1)]),
            section_id=1,
        )
        for j in range(n)
        for i in range(n)
    ]
    fields = {"stiffness": 1000.0, "direction": "Z", **spring}
    return Project(
        nodes=nodes,
        sections=[ElasticMembranePlateSection(id=1, name="Raft", E=3e10, nu=0.2, h=0.5)],
        elements=shells,
        area_springs=[AreaSpring(element_id=s.id, **fields) for s in shells],  # type: ignore[arg-type]
    )


def _beam(**spring: object) -> Project:
    sec = ElasticSection(id=1, E=2e11, A=0.01, Iz=1e-4, Iy=1e-4, G=8e10, J=1e-5)
    return Project(
        nodes=[Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(3.0, 0.0, 0.0))],
        sections=[sec],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        line_springs=[LineSpring(element_id=1, stiffness=200.0, **spring)],  # type: ignore[arg-type]
    )


# ──────────────────────────── distribution ────────────────────────────
def test_a_raft_carries_k_times_its_area_shared_by_tributary_area() -> None:
    springs = nodal_springs(_raft())
    total = sum(s.stiffness for s in springs)
    assert total == pytest.approx(1000.0 * 16.0)
    by_node = {s.node_id: s.stiffness for s in springs}
    # A 2 x 2 raft of 2 m shells: corners 1 m², edge midpoints 2 m², the centre 4 m².
    assert sorted(set(round(v, 9) for v in by_node.values())) == [1000.0, 2000.0, 4000.0]
    assert len(springs) == 9  # four shells, one spring per node


def test_soil_under_a_z_spring_pushes_up_and_soil_above_pushes_down() -> None:
    below = nodal_springs(_raft(side="negative"))[0]
    above = nodal_springs(_raft(side="positive"))[0]
    assert below.direction == (0.0, 0.0, 1.0)  # from the medium to the structure
    assert above.direction == (0.0, 0.0, -1.0)


def test_a_normal_spring_follows_the_shell_normal() -> None:
    # Nodes 1-2-3-4 counter-clockwise from above: local 3 is +Z.
    spring = nodal_springs(_raft(direction="normal", side="positive"))[0]
    assert spring.direction == pytest.approx((0.0, 0.0, -1.0))


def test_a_line_spring_gives_each_end_half_of_k_times_l_along_its_axis() -> None:
    springs = nodal_springs(_beam(direction="Z"))
    assert [(s.node_id, s.stiffness) for s in springs] == [(1, 300.0), (2, 300.0)]
    local_2 = nodal_springs(_beam(direction="2"))  # a horizontal 3D beam: local 2 is global Y
    assert local_2[0].direction == pytest.approx((0.0, 1.0, 0.0))


def test_an_edge_spring_loads_only_the_two_ends_of_its_edge() -> None:
    project = _raft(n=1)
    project.area_springs.clear()
    project.edge_springs.append(EdgeSpring(element_id=100, edge=2, stiffness=10.0))
    springs = nodal_springs(project)
    shell = project.elements[0]
    assert {s.node_id for s in springs} == {shell.nodes[1], shell.nodes[2]}
    assert all(s.stiffness == pytest.approx(10.0 * 4.0 / 2) for s in springs)


def test_different_behaviours_at_a_node_stay_separate() -> None:
    project = _raft(n=1)
    project.area_springs.append(
        AreaSpring(element_id=100, stiffness=5.0, direction="Z", behaviour="compression")
    )
    assert len(nodal_springs(project)) == 8
    assert has_one_sided_springs(project)


# ──────────────────────────── model check ────────────────────────────
def test_springs_count_as_support_in_the_model_check() -> None:
    project = _raft()
    project.nodes[:] = [n.model_copy(update={"restraint": PLANE}) for n in project.nodes]
    assert check_model(project).is_clean
    project.area_springs.clear()
    assert check_model(project).has_errors  # nothing holds it vertically any more


def test_a_joint_spring_is_a_support_for_the_model_check() -> None:
    """The model check used to ignore joint springs and call such a model floating."""
    project = _beam()
    project.line_springs.clear()
    project.nodes[0] = project.nodes[0].model_copy(update={"spring": (1.0,) * 6})
    assert check_model(project).is_clean


def test_a_line_spring_along_z_alone_leaves_a_beam_free_sideways() -> None:
    report = check_model(_beam(direction="Z"))
    assert any(f.code == "mechanism" for f in report.findings)


def test_a_spring_on_the_wrong_kind_of_element_is_a_reference_error() -> None:
    project = _beam()
    project.area_springs.append(AreaSpring(element_id=1, stiffness=1.0))
    with pytest.raises(ValueError, match="area spring is on element 1, which is not a shell"):
        project.validate_references()


# ──────────────────────────── file ────────────────────────────
def test_a_project_without_springs_saves_as_before_and_with_them_round_trips() -> None:
    assert "springs" not in Project().model_dump_json()
    project = _raft(behaviour="compression", side="positive")
    again = Project.model_validate_json(project.model_dump_json())
    assert again.area_springs == project.area_springs


# ──────────────────────────── keeping in step ────────────────────────────
def test_springs_of_deleted_elements_are_pruned() -> None:
    project = _raft()
    project.elements[:] = project.elements[1:]
    assert prune_support_springs(project)
    assert {s.element_id for s in project.area_springs} == {e.id for e in project.elements}


def test_copied_elements_take_their_springs() -> None:
    project = _beam()
    copy_support_springs(project, {1: 7})
    assert [s.element_id for s in project.line_springs] == [1, 7]


def test_after_a_mesh_area_springs_go_to_every_piece_and_edge_springs_to_the_edge() -> None:
    project = _raft(n=1)
    project.edge_springs.append(EdgeSpring(element_id=100, edge=1, stiffness=10.0))
    corners = {
        100: np.array(
            [n.coords for n in project.nodes[:2]]
            + [project.nodes[3].coords, project.nodes[2].coords],
            dtype=float,
        )
    }
    # Split the 4 m shell into two 2 m pieces along X.
    project.nodes += [Node(id=5, coords=(2.0, 0.0, 0.0)), Node(id=6, coords=(2.0, 4.0, 0.0))]
    project.elements[:] = [
        ShellMITC4Element(id=201, nodes=(1, 5, 6, 3), section_id=1),
        ShellMITC4Element(id=202, nodes=(5, 2, 4, 6), section_id=1),
    ]
    springs_follow_pieces(project, {100: [201, 202]}, corners, 1e-9)

    assert [s.element_id for s in project.area_springs] == [201, 202]
    assert sorted((s.element_id, s.edge) for s in project.edge_springs) == [(201, 1), (202, 1)]
    total = sum(s.stiffness for s in nodal_springs(project) if s.behaviour == "both")
    assert total == pytest.approx(1000.0 * 16.0 + 10.0 * 4.0)  # nothing lost or doubled


# ──────────────────────────── SAP2000 text ────────────────────────────
_SLAB = """\
TABLE:  "PROGRAM CONTROL"
   ProgramName=SAP2000   CurrUnits="KN, m, C"
TABLE:  "JOINT COORDINATES"
   Joint=1   CoordSys=GLOBAL   CoordType=Cartesian   XorR=0   Y=0   Z=0
   Joint=2   CoordSys=GLOBAL   CoordType=Cartesian   XorR=2   Y=0   Z=0
   Joint=3   CoordSys=GLOBAL   CoordType=Cartesian   XorR=2   Y=2   Z=0
   Joint=4   CoordSys=GLOBAL   CoordType=Cartesian   XorR=0   Y=2   Z=0
TABLE:  "MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES"
   Material=C   UnitWeight=0   UnitMass=0   E1=30000000   G12=12500000   U12=0.2
TABLE:  "AREA SECTION PROPERTIES"
   Section=S   Material=C   AreaType=Shell   Type=Shell-Thin   Thickness=0.3   BendThick=0.3
TABLE:  "CONNECTIVITY - AREA"
   Area=1   NumJoints=4   Joint1=1   Joint2=4   Joint3=3   Joint4=2
   Area=2   NumJoints=4   Joint1=1   Joint2=2   Joint3=3   Joint4=4
TABLE:  "AREA SECTION ASSIGNMENTS"
   Area=1   Section=S   MatProp=Default
   Area=2   Section=S   MatProp=Default
TABLE:  "AREA SPRING ASSIGNMENTS"
   Area=1   Type=Simple   Stiffness=50000   SimpleType="Compression Only"   Face=Top   Dir1Type="Normal To Face"   NormalDir=Inward
   Area=2   Type=Simple   Stiffness=20000   SimpleType="Tension and Compression"   Face=Bottom   Dir1Type="Normal To Face"   NormalDir=Inward
   Area=2   Type=Simple   Stiffness=1   SimpleType="Tension and Compression"   Face=1   Dir1Type="Normal To Face"   NormalDir=Inward
   Area=2   Type=Link   LinkProp=L1   Face=Top
END TABLE DATA
"""


@pytest.fixture
def slab(tmp_path: Path) -> Path:
    path = tmp_path / "slab.s2k"
    path.write_text(_SLAB, encoding="utf-8")
    return path


def test_sap2000_area_springs_are_read_on_their_face(slab: Path) -> None:
    from opensees_studio.services.sap2000_text import import_s2k

    imported = import_s2k(slab)
    springs = {s.element_id: s for s in imported.project.area_springs}
    # kN/m³ → N/m³; Top is the +3 side, so the medium is there.
    assert (springs[1].stiffness, springs[1].side, springs[1].behaviour) == (
        5e7,
        "positive",
        "compression",
    )
    assert (springs[2].stiffness, springs[2].side, springs[2].behaviour) == (
        2e7,
        "negative",
        "both",
    )
    # Area 1 turns clockwise from above (local 3 down): its Top-face soil is below.
    down = next(s for s in nodal_springs(imported.project) if s.behaviour == "compression")
    assert down.direction == pytest.approx((0.0, 0.0, 1.0))
    assert imported.dropped["area spring on an area edge face"] == 1
    assert imported.dropped["area spring from a link property"] == 1


def test_sap2000_area_springs_go_out_and_back(slab: Path, tmp_path: Path) -> None:
    from opensees_studio.services.sap2000_text import export_s2k, import_s2k

    first = import_s2k(slab).project
    report = export_s2k(first, tmp_path / "again.s2k")
    assert report.written["area spring(s)"] == 2
    again = import_s2k(tmp_path / "again.s2k").project
    assert again.area_springs == first.area_springs


_BEAM = """\
TABLE:  "PROGRAM CONTROL"
   ProgramName=SAP2000   CurrUnits="KN, m, C"
TABLE:  "JOINT COORDINATES"
   Joint=1   CoordSys=GLOBAL   CoordType=Cartesian   XorR=0   Y=0   Z=0
   Joint=2   CoordSys=GLOBAL   CoordType=Cartesian   XorR=4   Y=0   Z=0
   Joint=3   CoordSys=GLOBAL   CoordType=Cartesian   XorR=8   Y=0   Z=0
TABLE:  "MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES"
   Material=S   UnitWeight=0   UnitMass=0   E1=200000000   G12=77000000   U12=0.3
TABLE:  "FRAME SECTION PROPERTIES 01 - GENERAL"
   SectionName=R   Material=S   Shape=Rectangular   t3=0.4   t2=0.2
TABLE:  "CONNECTIVITY - FRAME"
   Frame=1   JointI=1   JointJ=2
   Frame=2   JointI=2   JointJ=3
TABLE:  "FRAME SECTION ASSIGNMENTS"
   Frame=1   AnalSect=R
   Frame=2   AnalSect=R
TABLE:  "FRAME SPRING ASSIGNMENTS"
   Frame=1   Type=Simple   Stiffness=100   SimpleType="Compression Only"   Dir1Type="Object Axes"   Dir=2
   Frame=2   Type=Simple   Stiffness=50   SimpleType="Tension and Compression"   Dir1Type="Object Axes"   Dir=-2
   Frame=2   Type=Link   LinkProp=L1
END TABLE DATA
"""


@pytest.fixture
def beam_s2k(tmp_path: Path) -> Path:
    path = tmp_path / "beam.s2k"
    path.write_text(_BEAM, encoding="utf-8")
    return path


def test_sap2000_frame_springs_are_read_along_their_object_axis(beam_s2k: Path) -> None:
    from opensees_studio.services.sap2000_text import import_s2k

    imported = import_s2k(beam_s2k)
    springs = {s.element_id: s for s in imported.project.line_springs}
    assert springs[1].stiffness == pytest.approx(1e5)  # kN/m² → N/m²
    assert springs[1].behaviour == "compression"
    # SAP's local 2 of a horizontal beam is +Z: soil under the beam pushes up.
    up = [s for s in nodal_springs(imported.project) if s.behaviour == "compression"]
    assert all(s.direction == pytest.approx((0.0, 0.0, 1.0)) for s in up)
    # Dir=-2: the medium is above.
    down = [s for s in nodal_springs(imported.project) if s.behaviour == "both"]
    assert all(s.direction == pytest.approx((0.0, 0.0, -1.0)) for s in down)
    assert imported.dropped["frame spring from a link property"] == 1


def test_sap2000_frame_springs_go_out_and_back(beam_s2k: Path, tmp_path: Path) -> None:
    from opensees_studio.services.sap2000_text import export_s2k, import_s2k

    first = import_s2k(beam_s2k).project
    report = export_s2k(first, tmp_path / "again.s2k")
    assert report.written["line spring(s)"] == 2
    again = import_s2k(tmp_path / "again.s2k").project
    assert nodal_springs(again) == nodal_springs(first)
