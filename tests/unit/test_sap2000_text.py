"""Reading and writing the SAP2000 text format (``.s2k`` / ``.$2k``).

The fixtures in ``tests/fixtures/s2k`` are hand-written from the table format:
a 2D portal in kN-m and a one-storey 3D frame in kip-in with a slab, releases,
a local-axis angle, partial and point loads, a scaled pattern and combinations.
Smaller cases are written inline, each the smallest file that shows one rule.
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest

from opensees_studio.core import UnitSystem
from opensees_studio.core.analysis import ModalCase, ResponseSpectrumCase, StaticCase
from opensees_studio.core.combinations import CombinationTerm, LoadCombination
from opensees_studio.core.geometry.elements import ElasticBeamColumn, ShellMITC4Element
from opensees_studio.core.geometry.frame_options import (
    EndRelease,
    FrameModifiers,
    FrameReleases,
)
from opensees_studio.core.geometry.node import Node
from opensees_studio.core.loads import (
    LinearTimeSeries,
    NodalLoad,
    PlainLoadPattern,
    PointElementLoad,
    ResponseSpectrum,
    TrapezoidalElementLoad,
    UniformElementLoad,
)
from opensees_studio.core.mass_source import MassSource
from opensees_studio.core.project import Project, ProjectMeta
from opensees_studio.core.sections import (
    ElasticMembranePlateSection,
    ElasticSection,
    NonprismaticSection,
    RectShape,
    WideFlangeShape,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.sap2000_text import (
    S2kFile,
    Sap2000Import,
    Sap2000TextError,
    export_s2k,
    import_s2k,
    parse_tables,
    project_to_s2k,
    read_s2k,
    s2k_to_project,
    sap_local_axes,
    unit_scale,
    writer_angle,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "s2k"
PORTAL = FIXTURES / "portal_2d.s2k"
FRAME = FIXTURES / "frame_3d.s2k"


def _write(tmp_path: Path, body: str, name: str = "model.s2k") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


_CANTILEVER = """\
TABLE:  "PROGRAM CONTROL"
   ProgramName=SAP2000   CurrUnits="{units}"
TABLE:  "JOINT COORDINATES"
   Joint=A   CoordSys=GLOBAL   CoordType=Cartesian   XorR=0   Y=0   Z=0
   Joint=B   CoordSys=GLOBAL   CoordType=Cartesian   XorR={x}   Y=0   Z={z}
TABLE:  "JOINT RESTRAINT ASSIGNMENTS"
   Joint=A   U1=Yes   U2=Yes   U3=Yes   R1=Yes   R2=Yes   R3=Yes
TABLE:  "MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES"
   Material=M   UnitWeight=0   UnitMass=0   E1=200   G12=80   U12=0.25
TABLE:  "FRAME SECTION PROPERTIES 01 - GENERAL"
   SectionName=S   Material=M   Shape=General   t3=1   t2=1   Area=10   TorsConst=3   I33=50   I22=20   AS2=4   AS3=6
TABLE:  "CONNECTIVITY - FRAME"
   Frame=B1   JointI=A   JointJ=B
TABLE:  "FRAME SECTION ASSIGNMENTS"
   Frame=B1   AnalSect=S   MatProp=Default
{extra}END TABLE DATA
"""


def _cantilever(
    tmp_path: Path, *, units: str = "KN, m, C", x: float = 5, z: float = 0, extra: str = ""
) -> Path:
    return _write(tmp_path, _CANTILEVER.format(units=units, x=x, z=z, extra=extra))


# ──────────────────────────── the file ────────────────────────────
def test_tables_records_quotes_and_continuations() -> None:
    tables = parse_tables(
        'File x.s2k was saved on 1/1/26\n\nTABLE:  "PROGRAM CONTROL"\n'
        '   ProgramName=SAP2000   CurrUnits="KN, m, C"\n'
        'TABLE:  "LOAD PATTERN DEFINITIONS"\n'
        "   LoadPat=DEAD   DesignType=Dead _\n"
        "      SelfWtMult=1\n"
        '   LoadPat="WIND X"   SelfWtMult=0\n'
        "END TABLE DATA\n"
        'TABLE:  "AFTER THE END"\n   Key=1\n'
    )
    assert tables["PROGRAM CONTROL"] == [{"ProgramName": "SAP2000", "CurrUnits": "KN, m, C"}]
    assert tables["LOAD PATTERN DEFINITIONS"] == [
        {"LoadPat": "DEAD", "DesignType": "Dead", "SelfWtMult": "1"},
        {"LoadPat": "WIND X", "SelfWtMult": "0"},
    ]
    assert "AFTER THE END" not in tables


def test_unit_factors() -> None:
    kn_m = unit_scale("KN, m, C", UnitSystem.SI_M_N)
    assert (kn_m.length, kn_m.force) == (1.0, 1000.0)
    assert kn_m.stress == 1000.0
    kip_in = unit_scale("Kip, in, F", UnitSystem.US_IN_KIP)
    assert kip_in.is_identity
    n_mm = unit_scale("N, mm, C", UnitSystem.SI_M_N)
    assert n_mm.length == 1e-3 and n_mm.stress == pytest.approx(1e6)
    with pytest.raises(Sap2000TextError, match="Unknown units"):
        unit_scale("furlong, fortnight", UnitSystem.SI_M_N)


def test_missing_and_empty_files_are_refused(tmp_path: Path) -> None:
    with pytest.raises(Sap2000TextError, match="No such file"):
        read_s2k(tmp_path / "nope.s2k")
    with pytest.raises(Sap2000TextError, match="no SAP2000 table"):
        read_s2k(_write(tmp_path, "just some text\n"))


def test_a_broken_reference_is_named(tmp_path: Path) -> None:
    body = _CANTILEVER.format(units="KN, m, C", x=5, z=0, extra="").replace("JointJ=B", "JointJ=C")
    with pytest.raises(Sap2000TextError, match=r"Frame B1 .*: joint 'C' is not defined"):
        import_s2k(_write(tmp_path, body))


def test_an_error_names_the_table_and_the_line(tmp_path: Path) -> None:
    body = _CANTILEVER.format(units="KN, m, C", x=5, z=0, extra="").replace("JointJ=B", "JointJ=C")
    line = next(
        number for number, text in enumerate(body.splitlines(), start=1) if "JointJ=C" in text
    )
    with pytest.raises(
        Sap2000TextError, match=rf"CONNECTIVITY - FRAME, line {line}\): joint 'C' is not defined"
    ):
        import_s2k(_write(tmp_path, body))


def test_a_line_that_is_not_a_record_is_reported_not_fatal(tmp_path: Path) -> None:
    extra = '   this is not a record at all\n   LoadPat=DEAD   Note="an unbalanced quote\n'
    imported = import_s2k(_cantilever(tmp_path, extra=extra))
    assert len(imported.project.nodes) == 2  # the model around the bad lines still imports
    (note,) = [note for note in imported.notes if "not Key=Value records" in note]
    assert note.startswith("2 line(s)")
    assert "this is not a record at all" in note


def test_a_file_without_joints_is_refused(tmp_path: Path) -> None:
    body = (
        'TABLE:  "PROGRAM CONTROL"\n   ProgramName=SAP2000   CurrUnits="KN, m, C"\n'
        'TABLE:  "GRID LINES"\n   CoordSys=GLOBAL   AxisDir=X   GridID=A   XRYZCoord=0\n'
        "END TABLE DATA\n"
    )
    with pytest.raises(Sap2000TextError, match="has no joints"):
        import_s2k(_write(tmp_path, body))


# ──────────────────────────── local axes ────────────────────────────
def test_sap_local_axes_of_a_beam_a_column_and_a_turned_member() -> None:
    o = np.zeros(3)
    e1, e2, e3 = sap_local_axes(o, np.array([5.0, 0, 0]))
    np.testing.assert_allclose((e1, e2, e3), ([1, 0, 0], [0, 0, 1], [0, -1, 0]), atol=1e-12)
    _, e2, e3 = sap_local_axes(o, np.array([0, 0, 3.0]))
    np.testing.assert_allclose((e2, e3), ([1, 0, 0], [0, 1, 0]), atol=1e-12)
    _, e2, e3 = sap_local_axes(o, np.array([5.0, 0, 0]), angle=90)
    np.testing.assert_allclose((e2, e3), ([0, -1, 0], [0, 0, -1]), atol=1e-12)


def test_writer_angle_puts_local_2_on_opensees_z() -> None:
    o = np.zeros(3)
    assert writer_angle(3, o, np.array([5.0, 0, 0])) == 0.0
    assert writer_angle(3, o, np.array([0, 0, 3.0])) == 0.0
    # A steep brace in the Y-Z plane: OpenSees takes vecxz = X, a quarter turn from SAP2000.
    assert abs(writer_angle(3, o, np.array([0, 1.0, 3.0]))) == pytest.approx(90.0)
    # 2D: local 2 goes on OpenSees' in-plane y, half a turn for a beam drawn right to left.
    assert abs(writer_angle(2, np.array([5.0, 0, 0]), o)) == pytest.approx(180.0)


# ──────────────────────────── the 2D portal ────────────────────────────
def test_portal_is_a_2d_frame_scaled_to_newtons() -> None:
    imported = import_s2k(PORTAL)
    project = imported.project
    assert project.ndm == 2 and project.ndf == 3
    assert project.meta.units is UnitSystem.SI_M_N
    assert imported.scale.force == 1000.0
    assert [n.coords for n in project.nodes] == [(0, 0, 0), (0, 0, 4), (6, 0, 4), (6, 0, 0)]
    assert project.nodes[0].restraint == (True, False, True, False, True, False)
    assert not any(project.nodes[1].restraint)

    (section,) = project.sections
    assert isinstance(section, ElasticSection)
    # In-plane bending is about SAP2000's local 3: I33 becomes Iz.
    assert section.Iz == pytest.approx(0.003125)
    assert pytest.approx(3e10) == section.E
    assert section.unit_weight == pytest.approx(24000.0)
    assert section.shape == RectShape(d=0.5, b=0.3)
    assert section.As2 is None  # AS2 = 0: no shear deformation
    beam = project.elements[1]
    assert isinstance(beam, ElasticBeamColumn)
    assert beam.rho == pytest.approx(2447.3 * 0.15)


def test_portal_loads_cases_and_combinations() -> None:
    imported = import_s2k(PORTAL)
    project = imported.project
    dead, live, wind = project.load_patterns
    assert dead.self_weight == 1.0
    # Gravity on a beam drawn left to right is along -y (its local y is up).
    assert live.element_loads == [UniformElementLoad(element_id=2, wy=-10000.0)]
    assert wind.nodal_loads == [NodalLoad(node_id=2, forces=(20000.0, 0, 0, 0, 0, 0))]
    assert [c.name for c in project.analyses] == ["DEAD", "LIVE", "WIND"]
    uls, env = project.combinations
    assert uls.terms == [
        CombinationTerm(ref_id=1, factor=1.2),
        CombinationTerm(ref_id=2, factor=1.6),
    ]
    assert env.combination_type == "Envelope"
    assert env.terms[0] == CombinationTerm(source="combination", ref_id=1)
    # What did not come across is reported, never silently dropped.
    assert imported.dropped["modal case without its general properties"] == 1
    # The added mass at joint 2 is kN.s2/m in a 2D model: MX survives, MY is reported.
    node2 = next(n for n in project.nodes if n.id == 2)
    assert node2.mass == pytest.approx((1000.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    assert imported.dropped["out-of-plane added mass component"] == 1
    assert not imported.unsupported_tables
    grid = project.coord_systems[0].grid
    assert [(g.id, g.ordinate) for g in grid.x_grid_lines] == [("A", 0.0), ("B", 6.0)]


# ──────────────────────────── the 3D frame ────────────────────────────
def _section(project: Project, element_id: int) -> ElasticSection:
    element = next(e for e in project.elements if e.id == element_id)
    section = next(s for s in project.sections if s.id == element.section_id)
    assert isinstance(section, ElasticSection)
    return section


def test_3d_sections_follow_the_local_axes() -> None:
    project = import_s2k(FRAME).project
    assert project.ndm == 3 and project.meta.units is UnitSystem.US_IN_KIP
    column = _section(project, 1)
    # A column's SAP2000 local 2 is OpenSees' z: I33 is Iy, AS2 is As3.
    assert (column.Iy, column.Iz, column.As3, column.As2) == (999.0, 362.0, 6.16, 17.16)
    assert column.shape == WideFlangeShape(d=14, bf=14.5, tw=0.44, tf=0.71)
    turned = _section(project, 2)  # local-axis angle 90: local 2 lies on OpenSees' y
    assert (turned.Iz, turned.Iy) == (999.0, 362.0)
    assert turned.name == "W14X90 (axes 2-3)" and turned.shape is None
    beam = _section(project, 5)
    assert beam.Iy == pytest.approx(510 * 1.5)  # I3Mod
    tube = _section(project, 9)  # Box/Tube with dimensions only: closed-form properties
    assert pytest.approx(6 * 6 - 5.5 * 5.5) == tube.A
    assert tube.As2 is None  # its releases make it an Euler-Bernoulli member


def test_3d_releases_map_sap2000_m3_onto_bending_about_local_y() -> None:
    project = import_s2k(FRAME).project
    beam = next(e for e in project.elements if e.id == 6)
    assert isinstance(beam, ElasticBeamColumn)
    assert beam.releases.i.released == ("M2",) and beam.releases.j.released == ("M2",)
    brace = next(e for e in project.elements if e.id == 9)
    assert isinstance(brace, ElasticBeamColumn)
    assert brace.releases.i == EndRelease(released=("T", "M2", "M3"), springs={"M2": 5000.0})
    assert _section(project, 6).name == "W18X35 (no shear)"


def test_3d_loads_cases_and_shells() -> None:
    imported = import_s2k(FRAME)
    project = imported.project
    live = next(p for p in project.load_patterns if p.name == "LIVE")
    assert live.element_loads == [UniformElementLoad(element_id=5, wz=-0.1)]
    assert live.point_loads == [PointElementLoad(element_id=6, pz=-12.0, x=0.5)]
    assert live.distributed_loads == [
        TrapezoidalElementLoad(element_id=7, x_start=0.25, x_end=0.75, wz_start=-0.05, wz_end=-0.15)
    ]
    # GRAV = DEAD + 0.5 LIVE: the scaled pattern becomes one of its own.
    grav = next(c for c in project.analyses if c.name == "GRAV")
    assert isinstance(grav, StaticCase)
    half = next(p for p in project.load_patterns if p.id == grav.pattern_ids[1])
    assert half.name == "LIVE x 0.5" and half.point_loads[0].pz == -6.0
    (shell,) = [e for e in project.elements if isinstance(e, ShellMITC4Element)]
    assert shell.id == 10 and shell.nodes == (5, 6, 7, 8)
    slab = next(s for s in project.sections if s.id == shell.section_id)
    assert isinstance(slab, ElasticMembranePlateSection)
    assert (slab.h, slab.nu, slab.E) == (6.0, 0.2, 3605.0)
    c2 = next(c for c in project.combinations if c.name == "C2")
    assert c2.combination_type == "AbsoluteAdd"
    assert imported.dropped["Range Add combination"] == 1
    assert imported.dropped["automatic ASCE 7-16 load"] == 1
    assert imported.dropped["distributed moment load"] == 1


def test_names_that_are_not_integers_are_numbered(tmp_path: Path) -> None:
    imported = import_s2k(_cantilever(tmp_path))
    assert [n.id for n in imported.project.nodes] == [1, 2]
    assert imported.project.elements[0].id == 1
    assert any("numbered 1" in note for note in imported.notes)


def test_projected_and_local_loads(tmp_path: Path) -> None:
    extra = (
        'TABLE:  "LOAD PATTERN DEFINITIONS"\n   LoadPat=L   SelfWtMult=0\n'
        'TABLE:  "FRAME LOADS - DISTRIBUTED"\n'
        '   Frame=B1   LoadPat=L   CoordSys=GLOBAL   Type=Force   Dir="Gravity Projected"   '
        "RelDistA=0   RelDistB=1   FOverLA=2   FOverLB=2\n"
    )
    imported = import_s2k(_cantilever(tmp_path, x=3, z=4, extra=extra))
    (load,) = imported.project.load_patterns[0].element_loads
    # A 3-4-5 slope: 2 per horizontal metre is 2·3/5 per metre of member, pointing down.
    total = np.hypot(np.hypot(load.wx, load.wy), load.wz)
    assert total == pytest.approx(2000 * 3 / 5)


# ──────────────────────────── joint masses and springs ────────────────────────────
_MASS_SPRINGS = """\
TABLE:  "JOINT ADDED MASS ASSIGNMENTS"
   Joint=B   CoordSys="Joint Local"   Mass1=1   Mass2=2   Mass3=5555   MMI1=2   MMI2=3   MMI3=4
TABLE:  "JOINT SPRING ASSIGNMENTS 1 - UNCOUPLED"
   Joint=A   CoordSys=Local   U1=12   U2=3   U3=222   R1=5   R2=6   R3=7
"""


def test_added_masses_and_springs_are_scaled_to_the_project(tmp_path: Path) -> None:
    imported = import_s2k(_cantilever(tmp_path, units="Kgf, m, C", extra=_MASS_SPRINGS))
    node_a, node_b = imported.project.nodes
    kgf = 9.80665  # 1 kgf.s2/m is 1 kg, and 1 kgf.m.s2 is 1 kg.m2
    assert node_b.mass == pytest.approx((kgf, 2 * kgf, 5555 * kgf, 2 * kgf, 3 * kgf, 4 * kgf))
    assert node_a.spring == pytest.approx((12 * kgf, 3 * kgf, 222 * kgf, 5 * kgf, 6 * kgf, 7 * kgf))
    assert not imported.dropped and not imported.unsupported_tables


def test_an_all_zero_joint_assignment_is_not_a_mass(tmp_path: Path) -> None:
    extra = (
        'TABLE:  "JOINT ADDED MASS ASSIGNMENTS"\n'
        '   Joint=B   CoordSys="Joint Local"   Mass1=0   Mass2=0   Mass3=0 _\n'
        "      MMI1=0   MMI2=0   MMI3=0\n"
        'TABLE:  "JOINT SPRING ASSIGNMENTS 1 - UNCOUPLED"\n'
        "   Joint=A   CoordSys=Local   U1=0   U2=0   U3=0   R1=0   R2=0   R3=0\n"
    )
    imported = import_s2k(_cantilever(tmp_path, extra=extra))
    assert all(not any(n.mass) for n in imported.project.nodes)
    assert all(not n.has_spring for n in imported.project.nodes)
    assert not imported.dropped


def test_joint_assignments_on_a_missing_joint_are_reported(tmp_path: Path) -> None:
    extra = _MASS_SPRINGS.replace("Joint=B", "Joint=Z").replace("Joint=A", "Joint=Y")
    imported = import_s2k(_cantilever(tmp_path, extra=extra))
    assert imported.dropped["added mass on a missing joint"] == 1
    assert imported.dropped["support spring on a missing joint"] == 1


def test_a_2d_model_keeps_only_its_in_plane_mass_and_springs(tmp_path: Path) -> None:
    dofs = (
        'TABLE:  "ACTIVE DEGREES OF FREEDOM"\n   UX=Yes   UY=No   UZ=Yes   RX=No   RY=Yes   RZ=No\n'
    )
    imported = import_s2k(_cantilever(tmp_path, units="Kgf, m, C", extra=dofs + _MASS_SPRINGS))
    assert imported.project.ndm == 2
    node_a, node_b = imported.project.nodes
    kgf = 9.80665
    assert node_b.mass == pytest.approx((kgf, 0.0, 5555 * kgf, 0.0, 3 * kgf, 0.0))
    assert node_a.spring == pytest.approx((12 * kgf, 0.0, 222 * kgf, 0.0, 6 * kgf, 0.0))
    assert imported.dropped["out-of-plane added mass component"] == 1
    assert imported.dropped["out-of-plane support spring component"] == 1


def test_rotated_joint_axes_leave_the_assignments_unread(tmp_path: Path) -> None:
    extra = (
        'TABLE:  "JOINT LOCAL AXES ASSIGNMENTS 1 - TYPICAL"\n   Joint=B   Angle=30\n'
        + _MASS_SPRINGS
    )
    imported = import_s2k(_cantilever(tmp_path, extra=extra))
    assert imported.dropped["added mass in rotated joint local axes"] == 1
    assert imported.dropped["support spring in rotated joint local axes"] == 1
    assert all(not any(n.mass) and not n.has_spring for n in imported.project.nodes)


def test_a_negative_joint_mass_is_refused_with_its_line(tmp_path: Path) -> None:
    extra = _MASS_SPRINGS.replace("Mass1=1", "Mass1=-1")
    with pytest.raises(
        Sap2000TextError,
        match=r"JOINT ADDED MASS ASSIGNMENTS, line \d+\): an added mass must not be negative",
    ):
        import_s2k(_cantilever(tmp_path, extra=extra))


def test_a_mass_source_that_excludes_masses_skips_the_table(tmp_path: Path) -> None:
    extra = (
        'TABLE:  "MASS SOURCE"\n'
        "   MassSource=MSSSRC1   Elements=Yes   Masses=No   Loads=No   IsDefault=Yes\n"
        + _MASS_SPRINGS
    )
    imported = import_s2k(_cantilever(tmp_path, extra=extra))
    assert not any(any(n.mass) for n in imported.project.nodes)
    assert any("excludes added joint masses" in note for note in imported.notes)
    assert imported.project.nodes[0].has_spring  # the mass source does not touch springs


def test_a_mass_source_with_loads_and_no_element_mass_is_reported(tmp_path: Path) -> None:
    extra = 'TABLE:  "MASS SOURCE"\n   MassSource=MSSSRC1   Elements=No   Masses=Yes   Loads=Yes\n'
    notes = " ".join(import_s2k(_cantilever(tmp_path, extra=extra)).notes)
    assert "excludes element masses" in notes
    assert "turns load patterns into mass" in notes


# ──────────────────────────── real-world section definitions ────────────────────────────
_2D_DOFS = (
    'TABLE:  "ACTIVE DEGREES OF FREEDOM"\n   UX=Yes   UY=No   UZ=Yes   RX=No   RY=Yes   RZ=No\n'
)


def test_a_2d_frame_accepts_zero_out_of_plane_inertia_and_torsion(tmp_path: Path) -> None:
    body = (
        _CANTILEVER.format(units="KN, m, C", x=5, z=0, extra=_2D_DOFS)
        .replace("I22=20", "I22=0")
        .replace("TorsConst=3", "TorsConst=0")
    )
    imported = import_s2k(_write(tmp_path, body))
    assert imported.project.ndm == 2
    section = imported.project.sections[0]
    assert isinstance(section, ElasticSection)
    assert (section.A, section.Iz) == (10.0, 50.0)
    # A 2D section carries no out-of-plane inertia and no torsion constant.
    assert section.Iy is None and section.J is None
    assert not imported.dropped


def test_a_2d_member_without_in_plane_inertia_is_refused(tmp_path: Path) -> None:
    extra = _2D_DOFS + (
        'TABLE:  "FRAME LOCAL AXES ASSIGNMENTS 1 - TYPICAL"\n   Frame=B1   Angle=90\n'
    )
    body = _CANTILEVER.format(units="KN, m, C", x=5, z=0, extra=extra).replace("I22=20", "I22=0")
    with pytest.raises(Sap2000TextError, match="no inertia about the member's in-plane axis"):
        import_s2k(_write(tmp_path, body))


def test_a_zero_torsional_constant_gets_a_small_one(tmp_path: Path) -> None:
    body = _CANTILEVER.format(units="KN, m, C", x=5, z=0, extra="").replace(
        "TorsConst=3", "TorsConst=0"
    )
    imported = import_s2k(_write(tmp_path, body))
    section = imported.project.sections[0]
    assert isinstance(section, ElasticSection)
    assert section.Iy is not None
    assert pytest.approx(1e-6 * min(section.Iz, section.Iy)) == section.J
    assert imported.dropped["zero torsional constant (a small one substituted)"] == 1


def test_a_diaphragm_uses_the_floating_sap2000_master(tmp_path: Path) -> None:
    extra = (
        'TABLE:  "JOINT COORDINATES"\n'
        "   Joint=C   CoordSys=GLOBAL   CoordType=Cartesian   XorR=2.5   Y=0   Z=0\n"
        'TABLE:  "CONSTRAINT DEFINITIONS - DIAPHRAGM"\n'
        "   Name=D1   CoordSys=GLOBAL   Axis=Z   MultiLevel=No\n"
        'TABLE:  "JOINT CONSTRAINT ASSIGNMENTS"\n'
        "   Joint=A   Constraint=D1\n"
        "   Joint=B   Constraint=D1\n"
        "   Joint=C   Constraint=D1\n"
    )
    imported = import_s2k(_cantilever(tmp_path, extra=extra))
    project = imported.project
    (diaphragm,) = project.diaphragms
    # C is the floating SAP master; A is a support and cannot follow the floor.
    assert diaphragm.retained_node == 3
    assert diaphragm.constrained_nodes == (2,)
    assert diaphragm.perp_dirn == 3
    assert imported.dropped["diaphragm joint restrained in the plane (left out)"] == 1
    project.validate_references()

    target = tmp_path / "diaphragm.s2k"
    report = export_s2k(project, target)
    text = target.read_text(encoding="utf-8-sig")
    assert 'TABLE:  "CONSTRAINT DEFINITIONS - DIAPHRAGM"' in text
    assert "Joint=3   Constraint=D1" in text and "Joint=2   Constraint=D1" in text
    assert "Joint=1   Constraint=D1" not in text  # the support is not a slave
    assert report.written["rigid diaphragm(s)"] == 1
    assert "rigid diaphragm" not in report.skipped
    again = import_s2k(target)
    (round_trip,) = again.project.diaphragms
    assert (round_trip.retained_node, round_trip.constrained_nodes) == (3, (2,))


def test_a_diaphragm_in_a_2d_model_is_reported(tmp_path: Path) -> None:
    extra = _2D_DOFS + (
        'TABLE:  "CONSTRAINT DEFINITIONS - DIAPHRAGM"\n'
        "   Name=D1   CoordSys=GLOBAL   Axis=Z   MultiLevel=No\n"
        'TABLE:  "JOINT CONSTRAINT ASSIGNMENTS"\n'
        "   Joint=A   Constraint=D1\n"
        "   Joint=B   Constraint=D1\n"
    )
    imported = import_s2k(_cantilever(tmp_path, extra=extra))
    assert imported.project.diaphragms == []
    assert imported.dropped["rigid diaphragm in a 2D model"] == 1


def test_frame_property_modifiers_are_imported_and_mapped(tmp_path: Path) -> None:
    extra = (
        'TABLE:  "FRAME PROPERTY MODIFIERS"\n'
        "   Frame=B1   AMod=0.5   AS2Mod=0   AS3Mod=0   JMod=0.4 _\n"
        "      I22Mod=0.6   I33Mod=0.7   MassMod=0.8   WeightMod=0.9\n"
    )
    imported = import_s2k(_cantilever(tmp_path, extra=extra))
    frame = imported.project.element(1)
    assert isinstance(frame, ElasticBeamColumn)
    # 3D: SAP's local 2 is our z. AS3Mod -> our As2, I22Mod -> our Iz.
    assert frame.modifiers == FrameModifiers(
        area=0.5,
        as2=0.0,
        as3=0.0,
        torsion=0.4,
        i22=0.7,
        i33=0.6,
        mass=0.8,
        weight=0.9,
    )
    # The section has shear areas AS2=4/AS3=6, but both modifiers are zero:
    # the member must run Euler-Bernoulli, not Timoshenko.
    from opensees_studio.services.frame_members import plan_frame_members

    member = plan_frame_members(imported.project).members[1]
    assert member.timoshenko is None
    assert member.section_id != 1  # the non-shear modifiers still make a derived section
    assert "FRAME PROPERTY MODIFIERS" not in imported.unsupported_tables


def test_frame_property_modifiers_use_the_2d_axis_mapping(tmp_path: Path) -> None:
    extra = _2D_DOFS + (
        'TABLE:  "FRAME PROPERTY MODIFIERS"\n'
        "   Frame=B1   AMod=0.5   AS2Mod=0   AS3Mod=0   JMod=0.4 _\n"
        "      I22Mod=0.6   I33Mod=0.7   MassMod=0.8   WeightMod=0.9\n"
    )
    imported = import_s2k(_cantilever(tmp_path, extra=extra))
    frame = imported.project.element(1)
    assert isinstance(frame, ElasticBeamColumn)
    # 2D: SAP's local 2 is our local y, so the modifiers keep their names.
    assert frame.modifiers == FrameModifiers(
        area=0.5,
        as2=0.0,
        as3=0.0,
        torsion=0.4,
        i22=0.6,
        i33=0.7,
        mass=0.8,
        weight=0.9,
    )


def test_frame_property_modifiers_round_trip_through_the_export(tmp_path: Path) -> None:
    imported = import_s2k(_cantilever(tmp_path))
    project = imported.project
    modifiers = FrameModifiers(
        area=0.5,
        as2=0.0,
        as3=0.0,
        torsion=0.4,
        i22=0.7,
        i33=0.6,
        mass=0.8,
        weight=0.9,
    )
    frame = project.element(1)
    project.elements[0] = frame.model_copy(update={"modifiers": modifiers})
    target = tmp_path / "modified.s2k"
    report = export_s2k(project, target)
    text = target.read_text(encoding="utf-8-sig")
    assert 'TABLE:  "FRAME PROPERTY MODIFIERS"' in text
    assert "AMod=0.5" in text and "AS2Mod=0" in text and "I22Mod=0.6" in text
    assert "I33Mod=0.7" in text and "MassMod=0.8" in text
    assert "frame modifiers" not in report.skipped
    again = import_s2k(target)
    assert again.project.element(1).modifiers == modifiers


def test_a_nonprismatic_section_is_subdivided(tmp_path: Path) -> None:
    extra = (
        'TABLE:  "FRAME SECTION PROPERTIES 01 - GENERAL"\n'
        "   SectionName=BIG   Material=M   Shape=Rectangular   t3=2   t2=1 _\n"
        "      Area=2   TorsConst=0.5   I33=0.6667   I22=0.1667\n"
        "   SectionName=VAR   Shape=Nonprismatic\n"
        'TABLE:  "FRAME SECTION PROPERTIES 05 - NONPRISMATIC"\n'
        "   SectionName=VAR   StartSect=BIG   EndSect=BIG   LengthType=Relative _\n"
        "      RelLength=1   EI33Var=Linear   EI22Var=Linear\n"
    )
    body = _CANTILEVER.format(units="KN, m, C", x=5, z=0, extra=extra).replace(
        "AnalSect=S", "AnalSect=VAR"
    )
    imported = import_s2k(_write(tmp_path, body), nonprismatic_subdivisions=12)
    project = imported.project
    template = next(s for s in project.sections if isinstance(s, NonprismaticSection))
    assert template.name == "VAR (nonprismatic)"
    assert template.subdivisions == 12
    assert len(template.segments) == 1
    assert template.segments[0].length_type == "relative"
    assert template.segments[0].length == pytest.approx(1.0)
    # A constant taper is the same section everywhere, so the 12 pieces reuse BIG.
    big = next(s for s in project.sections if isinstance(s, ElasticSection) and s.name == "BIG")
    assert (big.A, big.Iz, big.Iy) == pytest.approx((2.0, 0.1667, 0.6667))
    assert pytest.approx(200_000.0) == big.E  # from BIG's material M, not VAR's (empty)
    frames = [e for e in project.elements if isinstance(e, ElasticBeamColumn)]
    assert len(frames) == 12
    assert all(f.section_id == big.id for f in frames)
    assert any("subdivided into 12" in note for note in imported.notes)
    assert "nonprismatic section (imported as its start section)" not in imported.dropped


def test_shear_modifiers_on_a_nonprismatic_frame_are_ignored(tmp_path: Path) -> None:
    """SAP2000's own nonprismatic results keep the segment shear flexibility.

    Its table can still say AS2Mod/AS3Mod = 0; applying that would make the
    imported member stiffer than SAP2000's stored results.
    """
    extra = (
        'TABLE:  "FRAME SECTION PROPERTIES 01 - GENERAL"\n'
        "   SectionName=VAR   Shape=Nonprismatic\n"
        'TABLE:  "FRAME SECTION PROPERTIES 05 - NONPRISMATIC"\n'
        "   SectionName=VAR   StartSect=S   EndSect=S   LengthType=Relative _\n"
        "      RelLength=1   EI33Var=Linear   EI22Var=Linear\n"
        'TABLE:  "FRAME PROPERTY MODIFIERS"\n'
        "   Frame=B1   AMod=1   AS2Mod=0   AS3Mod=0   JMod=1 _\n"
        "      I22Mod=1   I33Mod=1   MassMod=1   WeightMod=1\n"
    )
    body = _CANTILEVER.format(units="KN, m, C", x=5, z=0, extra=extra).replace(
        "AnalSect=S", "AnalSect=VAR"
    )
    imported = import_s2k(_write(tmp_path, body))
    first = imported.project.element(1)
    assert isinstance(first, ElasticBeamColumn)
    assert first.modifiers.as2 == 1.0 and first.modifiers.as3 == 1.0
    assert any("shear-area" in note for note in imported.notes)


def test_nonprismatic_rows_keep_the_sap2000_table_order(tmp_path: Path) -> None:
    extra = (
        'TABLE:  "FRAME SECTION PROPERTIES 01 - GENERAL"\n'
        "   SectionName=S1   Material=M   Shape=Rectangular   t3=2   t2=1 _\n"
        "      Area=2   TorsConst=0.5   I33=0.6667   I22=0.1667\n"
        "   SectionName=S2   Material=M   Shape=Rectangular   t3=3   t2=1 _\n"
        "      Area=3   TorsConst=1.2   I33=2.25   I22=0.25\n"
        "   SectionName=S3   Material=M   Shape=Rectangular   t3=4   t2=1 _\n"
        "      Area=4   TorsConst=2.5   I33=5.3333   I22=0.3333\n"
        "   SectionName=VAR   Shape=Nonprismatic\n"
        'TABLE:  "FRAME SECTION PROPERTIES 05 - NONPRISMATIC"\n'
        "   SectionName=VAR   StartSect=S1   EndSect=S2   LengthType=Relative _\n"
        "      RelLength=0.5   EI33Var=Linear   EI22Var=Linear\n"
        "   SectionName=VAR   StartSect=S3   EndSect=S1   LengthType=Relative _\n"
        "      RelLength=0.5   EI33Var=Linear   EI22Var=Linear\n"
    )
    body = _CANTILEVER.format(units="KN, m, C", x=5, z=0, extra=extra).replace(
        "AnalSect=S", "AnalSect=VAR"
    )
    imported = import_s2k(_write(tmp_path, body), nonprismatic_subdivisions=12)
    sections = {s.name: s for s in imported.project.sections if isinstance(s, ElasticSection)}
    template = next(s for s in imported.project.sections if isinstance(s, NonprismaticSection))
    assert [
        (segment.start_section_id, segment.end_section_id) for segment in template.segments
    ] == [(sections["S1"].id, sections["S2"].id), (sections["S3"].id, sections["S1"].id)]


@pytest.mark.parametrize(
    "segment", ["", "   SectionName=VAR   StartSect=VAR\n"], ids=["no-table", "a-cycle"]
)
def test_a_nonprismatic_section_without_a_usable_start_is_refused(
    tmp_path: Path, segment: str
) -> None:
    extra = (
        'TABLE:  "FRAME SECTION PROPERTIES 01 - GENERAL"\n   SectionName=VAR   Shape=Nonprismatic\n'
    )
    if segment:
        extra += 'TABLE:  "FRAME SECTION PROPERTIES 05 - NONPRISMATIC"\n' + segment
    body = _CANTILEVER.format(units="KN, m, C", x=5, z=0, extra=extra).replace(
        "AnalSect=S", "AnalSect=VAR"
    )
    with pytest.raises(Sap2000TextError, match="needs a start section"):
        import_s2k(_write(tmp_path, body))


# ──────────────────────────── modal cases ────────────────────────────
_MODAL_CASE = """\
TABLE:  "LOAD PATTERN DEFINITIONS"
   LoadPat=DEAD   SelfWtMult=0
TABLE:  "LOAD CASE DEFINITIONS"
   Case=DEAD   Type=LinStatic   InitialCond=Zero   RunCase=Yes
   Case=MODAL   Type=LinModal   InitialCond=Zero   RunCase=Yes
TABLE:  "CASE - STATIC 1 - LOAD ASSIGNMENTS"
   Case=DEAD   LoadType="Load pattern"   LoadName=DEAD   LoadSF=1
TABLE:  "CASE - MODAL 1 - GENERAL"
   Case=MODAL   ModeType=Eigen   MaxNumModes=7   MinNumModes=1 _
      EigenShift=0   EigenCutoff=0   EigenTol=1E-07   AutoShift=No
"""


def test_a_modal_case_comes_across_with_its_mode_count(tmp_path: Path) -> None:
    imported = import_s2k(_cantilever(tmp_path, extra=_MODAL_CASE))
    static, modal = imported.project.analyses
    assert isinstance(static, StaticCase) and static.name == "DEAD"
    assert isinstance(modal, ModalCase)
    assert (modal.name, modal.n_modes, modal.solver) == ("MODAL", 7, "auto")
    assert not imported.dropped


def test_a_modal_case_that_is_not_an_eigen_one_is_reported(tmp_path: Path) -> None:
    extra = _MODAL_CASE.replace("ModeType=Eigen", "ModeType=Ritz")
    imported = import_s2k(_cantilever(tmp_path, extra=extra))
    assert imported.dropped["Ritz modal case"] == 1
    assert not any(isinstance(c, ModalCase) for c in imported.project.analyses)


@pytest.mark.parametrize("modes", ["0", "2.5", "-3"])
def test_a_modal_case_needs_a_positive_whole_mode_count(tmp_path: Path, modes: str) -> None:
    extra = _MODAL_CASE.replace("MaxNumModes=7", f"MaxNumModes={modes}")
    with pytest.raises(Sap2000TextError, match="MaxNumModes must be a positive whole number"):
        import_s2k(_cantilever(tmp_path, extra=extra))


# ──────────────────────────── response spectra ────────────────────────────
_SPECTRUM_CASE = """\
TABLE:  "FUNCTION - RESPONSE SPECTRUM - USER"
   Name=FUNC   Period=0   Accel=0.4   FuncDamp=0
   Name=FUNC   Period=0.5   Accel=1.0
   Name=FUNC   Period=1   Accel=0.5
TABLE:  "LOAD CASE DEFINITIONS"
   Case=RSC   Type=LinRespSpec   RunCase=Yes
TABLE:  "CASE - RESPONSE SPECTRUM 1 - GENERAL"
   Case=RSC   ModalCombo=CQC   GMCf1=1   GMCf2=0   PerRigid=SRSS   DirCombo=SRSS _
      ConstDamp=0.05   EccenRatio=0
TABLE:  "CASE - RESPONSE SPECTRUM 2 - LOAD ASSIGNMENTS"
   Case=RSC   LoadName=U1   CoordSys=GLOBAL   Function=FUNC   Angle=0   TransAccSF=9.80665
"""


def _spectrum_file(tmp_path: Path, extra: str = _SPECTRUM_CASE) -> Sap2000Import:
    return import_s2k(_cantilever(tmp_path, extra=_MODAL_CASE + extra))


def test_a_response_spectrum_case_comes_across(tmp_path: Path) -> None:
    imported = _spectrum_file(tmp_path)
    project = imported.project
    (spectrum,) = project.spectra
    g = 9.80665
    assert spectrum.name == "FUNC"
    assert spectrum.periods == pytest.approx([1e-6, 0.5, 1.0])
    assert spectrum.accelerations == pytest.approx([0.4 * g, g, 0.5 * g])
    assert spectrum.damping_ratio == pytest.approx(0.05)
    static, modal, case = project.analyses
    assert isinstance(static, StaticCase) and isinstance(modal, ModalCase)
    assert isinstance(case, ResponseSpectrumCase)
    assert (case.name, case.modal_case_id, case.spectrum_id) == ("RSC", modal.id, spectrum.id)
    assert (case.direction, case.combination, case.damping_ratio) == (1, "CQC", 0.05)
    assert imported.dropped["zero period in a response spectrum (read as 1e-6 s)"] == 1


def test_the_modal_combination_rule_is_kept(tmp_path: Path) -> None:
    imported = _spectrum_file(tmp_path, _SPECTRUM_CASE.replace("ModalCombo=CQC", "ModalCombo=SRSS"))
    case = imported.project.analyses[-1]
    assert isinstance(case, ResponseSpectrumCase) and case.combination == "SRSS"


@pytest.mark.parametrize("rule", ["ABS", "10 Percent"])
def test_a_modal_combination_without_a_counterpart_is_reported(tmp_path: Path, rule: str) -> None:
    extra = _SPECTRUM_CASE.replace("ModalCombo=CQC", f'ModalCombo="{rule}"')
    imported = _spectrum_file(tmp_path, extra)
    assert imported.dropped[f"{rule} modal combination"] == 1
    assert not any(isinstance(c, ResponseSpectrumCase) for c in imported.project.analyses)


def test_a_spectrum_case_needs_one_direction(tmp_path: Path) -> None:
    load = (
        "   Case=RSC   LoadName=U1   CoordSys=GLOBAL   Function=FUNC   Angle=0   "
        "TransAccSF=9.80665\n"
    )
    extra = _SPECTRUM_CASE.replace(load, load + load.replace("U1", "U2"))
    imported = _spectrum_file(tmp_path, extra)
    assert imported.dropped["spectrum case with more than one direction"] == 1


def test_a_spectrum_at_an_angle_is_reported(tmp_path: Path) -> None:
    imported = _spectrum_file(tmp_path, _SPECTRUM_CASE.replace("Angle=0", "Angle=15"))
    assert imported.dropped["spectrum at a non-zero angle"] == 1


def test_a_spectrum_needs_at_least_two_points(tmp_path: Path) -> None:
    extra = _SPECTRUM_CASE.replace(
        "   Name=FUNC   Period=0.5   Accel=1.0\n   Name=FUNC   Period=1   Accel=0.5\n", ""
    )
    imported = _spectrum_file(tmp_path, extra)
    assert imported.dropped["spectrum function 'FUNC' with fewer than two points"] == 1


def test_a_spectrum_damping_outside_zero_to_one_is_refused(tmp_path: Path) -> None:
    extra = _SPECTRUM_CASE.replace("ConstDamp=0.05", "ConstDamp=1.5")
    with pytest.raises(Sap2000TextError, match="ConstDamp must be between 0 and 1"):
        _spectrum_file(tmp_path, extra)


# ──────────────────────────── Wave 1: loads and mass ────────────────────────────
def _temperature_file(tmp_path: Path, rows: str) -> Path:
    body = _CANTILEVER.format(units="KN, m, C", x=5, z=0, extra="")
    body = body.replace("U12=0.25", "U12=0.25   A1=1.2E-05")
    body = body.replace(
        'TABLE:  "FRAME SECTION ASSIGNMENTS"',
        'TABLE:  "LOAD PATTERN DEFINITIONS"\n   LoadPat=T   SelfWtMult=0\n'
        'TABLE:  "FRAME SECTION ASSIGNMENTS"',
    )
    return _write(tmp_path, body.replace("END TABLE DATA", rows + "END TABLE DATA"))


def test_a_uniform_temperature_load_expands_the_member(tmp_path: Path) -> None:
    rows = (
        'TABLE:  "FRAME LOADS - TEMPERATURE"\n'
        "   Frame=B1   LoadPat=T   Type=Temperature   Temp=20\n"
    )
    imported = import_s2k(_temperature_file(tmp_path, rows))
    (pattern,) = imported.project.load_patterns
    (temperature,) = pattern.temperature_loads
    assert temperature.alpha == pytest.approx(1.2e-5)
    assert (temperature.uniform, temperature.gradient_y, temperature.gradient_z) == (20, 0, 0)
    result = OpenSeesRunner(imported.project).run(imported.project.analyses[0])
    assert result.node_disp[2][-1][0] == pytest.approx(1.2e-5 * 20 * 5)  # alpha dT L


def test_a_temperature_gradient_is_per_unit_length(tmp_path: Path) -> None:
    rows = (
        'TABLE:  "FRAME LOADS - TEMPERATURE"\n'
        "   Frame=B1   LoadPat=T   Type=Gradient2   TempGrad2=20\n"
    )
    imported = import_s2k(_temperature_file(tmp_path, rows))
    (temperature,) = imported.project.load_patterns[0].temperature_loads
    assert temperature.uniform == 0
    # A member along +X has SAP's local 2 on OpenSees' local z.
    assert temperature.gradient_y == pytest.approx(0, abs=1e-12)
    assert temperature.gradient_z == pytest.approx(20)


def test_a_joint_pattern_temperature_uses_the_pattern_mean(tmp_path: Path) -> None:
    rows = (
        'TABLE:  "JOINT PATTERN ASSIGNMENTS"\n'
        "   Joint=A   Pattern=GRAD1   Value=0\n"
        "   Joint=B   Pattern=GRAD1   Value=20\n"
        'TABLE:  "FRAME LOADS - TEMPERATURE"\n'
        "   Frame=B1   LoadPat=T   Type=Temperature   Temp=1   JtPattern=GRAD1\n"
    )
    imported = import_s2k(_temperature_file(tmp_path, rows))
    (temperature,) = imported.project.load_patterns[0].temperature_loads
    assert temperature.uniform == pytest.approx(10)  # the pattern's mean; Temp is the reference
    assert imported.dropped["temperature varying along the member (mean used)"] == 1


def test_a_ground_displacement_needs_a_restrained_dof(tmp_path: Path) -> None:
    rows = (
        'TABLE:  "JOINT LOADS - GROUND DISPLACEMENT"\n'
        "   Joint=A   LoadPat=T   CoordSys=GLOBAL   U3=-0.5\n"
    )
    imported = import_s2k(_temperature_file(tmp_path, rows))
    (imposed,) = imported.project.load_patterns[0].imposed_displacements
    assert (imposed.node_id, imposed.dof) == (1, 3)  # node A, U3
    assert imposed.value == pytest.approx(-0.5)


def test_a_ground_displacement_on_a_free_dof_is_reported(tmp_path: Path) -> None:
    rows = (
        'TABLE:  "JOINT LOADS - GROUND DISPLACEMENT"\n'
        "   Joint=B   LoadPat=T   CoordSys=GLOBAL   U3=-0.5\n"
    )
    imported = import_s2k(_temperature_file(tmp_path, rows))
    assert not imported.project.load_patterns[0].imposed_displacements
    assert imported.dropped["ground displacement on a non-restrained DOF"] == 1


def test_frame_added_mass_is_added_to_the_element_mass(tmp_path: Path) -> None:
    rows = 'TABLE:  "FRAME ADDED MASS ASSIGNMENTS"\n   Frame=B1   MassPerLen=2\n'
    imported = import_s2k(_temperature_file(tmp_path, rows))
    (element,) = imported.project.elements
    assert isinstance(element, ElasticBeamColumn)
    # 2 kN.s2/m2 is 2000 kg/m in the project units; the material has no mass of its own.
    assert element.rho == pytest.approx(2000)
    assert any("added mass" in note for note in imported.notes)


def _preload_file(tmp_path: Path, initial: str = "G") -> Path:
    body = _CANTILEVER.format(units="KN, m, C", x=5, z=0, extra="")
    rows = (
        'TABLE:  "LOAD PATTERN DEFINITIONS"\n   LoadPat=G   SelfWtMult=0\n'
        'TABLE:  "LOAD CASE DEFINITIONS"\n'
        "   Case=G   Type=LinStatic   InitialCond=Zero   RunCase=Yes\n"
        f"   Case=C   Type=LinStatic   InitialCond={initial}   RunCase=Yes\n"
        'TABLE:  "CASE - STATIC 1 - LOAD ASSIGNMENTS"\n'
        '   Case=G   LoadType="Load pattern"   LoadName=G   LoadSF=1\n'
        '   Case=C   LoadType="Load pattern"   LoadName=G   LoadSF=1\n'
    )
    return _write(tmp_path, body.replace("END TABLE DATA", rows + "END TABLE DATA"))


def test_a_static_case_starting_from_another_case_gets_a_preload(tmp_path: Path) -> None:
    imported = import_s2k(_preload_file(tmp_path))
    first, second = imported.project.analyses
    assert isinstance(first, StaticCase) and isinstance(second, StaticCase)
    assert second.preload_case_ids == [first.id]
    assert not imported.dropped


def test_a_preload_that_is_not_imported_runs_from_zero_and_is_reported(tmp_path: Path) -> None:
    imported = import_s2k(_preload_file(tmp_path, initial="MISSING"))
    second = imported.project.analyses[1]
    assert isinstance(second, StaticCase)
    assert second.preload_case_ids == []
    assert imported.dropped["static case starting from another case (run from zero)"] == 1


def test_the_export_writes_the_preload_case_name(tmp_path: Path) -> None:
    project = import_s2k(_preload_file(tmp_path)).project
    text, _ = project_to_s2k(project)
    assert "InitialCond=G" in text
    again = s2k_to_project(S2kFile(path=Path("again.s2k"), tables=parse_tables(text))).project
    first, second = again.analyses
    assert second.name == "C" and second.preload_case_ids == [first.id]


# ──────────────────────────── writing ────────────────────────────
def _totals(project: Project) -> dict[tuple[str, int], np.ndarray]:
    """Per pattern name and element, every frame load summed (distribution kept apart)."""
    out: dict[tuple[str, int], np.ndarray] = {}
    for pattern in project.load_patterns:
        for u in pattern.element_loads:
            key = (pattern.name, u.element_id)
            out[key] = out.get(key, np.zeros(9)) + np.array([u.wx, u.wy, u.wz, 0, 0, 0, 0, 0, 0])
        for d in pattern.distributed_loads:
            key = (pattern.name, d.element_id)
            out[key] = out.get(key, np.zeros(9)) + np.array(
                [0, 0, 0, *d.start(), d.x_start, d.x_end, 0]
            )
        for p in pattern.point_loads:
            key = (pattern.name, p.element_id)
            out[key] = out.get(key, np.zeros(9)) + np.array([0, 0, 0, p.px, p.py, p.pz, 0, 0, p.x])
    return out


def _assert_same_model(a: Project, b: Project) -> None:
    assert (a.ndm, a.meta.units) == (b.ndm, b.meta.units)
    assert [(n.id, n.coords, n.restraint, n.mass, n.spring) for n in a.nodes] == [
        (n.id, n.coords, n.restraint, n.mass, n.spring) for n in b.nodes
    ]
    assert len(a.elements) == len(b.elements)
    for ea, eb in zip(a.elements, b.elements, strict=True):
        assert (ea.id, ea.nodes, type(ea)) == (eb.id, eb.nodes, type(eb))
        sa = next(s for s in a.sections if s.id == ea.section_id)
        sb = next(s for s in b.sections if s.id == eb.section_id)
        fields = ("E", "A", "Iz", "Iy", "J", "G", "As2", "As3", "unit_weight", "h", "nu", "rho")
        for name in fields:
            va, vb = getattr(sa, name, None), getattr(sb, name, None)
            if isinstance(va, float) and isinstance(vb, float):
                assert va == pytest.approx(vb, rel=1e-12), (ea.id, name)
            else:
                assert va == vb, (ea.id, name)
        if isinstance(ea, ElasticBeamColumn):
            assert isinstance(eb, ElasticBeamColumn)
            assert ea.releases == eb.releases
            assert ea.rho == pytest.approx(eb.rho, rel=1e-12)
    assert [(p.name, p.self_weight, p.nodal_loads) for p in a.load_patterns] == [
        (p.name, p.self_weight, p.nodal_loads) for p in b.load_patterns
    ]
    ta, tb = _totals(a), _totals(b)
    assert ta.keys() == tb.keys()
    for key in ta:
        np.testing.assert_allclose(ta[key], tb[key], rtol=1e-12, atol=1e-15)
    assert [c.model_dump() for c in a.analyses] == [c.model_dump() for c in b.analyses]
    assert len(a.spectra) == len(b.spectra)
    for sa, sb in zip(a.spectra, b.spectra, strict=True):
        assert (sa.id, sa.name) == (sb.id, sb.name)
        assert sa.periods == pytest.approx(sb.periods)
        assert sa.accelerations == pytest.approx(sb.accelerations, rel=1e-11)
        assert sa.damping_ratio == pytest.approx(sb.damping_ratio)
    assert [(c.name, c.combination_type, c.terms) for c in a.combinations] == [
        (c.name, c.combination_type, c.terms) for c in b.combinations
    ]


@pytest.mark.parametrize("fixture", [PORTAL, FRAME], ids=["portal_2d", "frame_3d"])
def test_round_trip_keeps_what_the_import_reads(tmp_path: Path, fixture: Path) -> None:
    first = import_s2k(fixture).project
    report = export_s2k(first, tmp_path / "again.s2k")
    assert not report.skipped
    again = import_s2k(tmp_path / "again.s2k")
    assert not again.dropped and not again.unsupported_tables
    _assert_same_model(first, again.project)


@pytest.mark.parametrize("fixture", [PORTAL, FRAME], ids=["portal_2d", "frame_3d"])
def test_exporting_again_writes_the_same_text(tmp_path: Path, fixture: Path) -> None:
    once = export_s2k(import_s2k(fixture).project, tmp_path / "once.s2k")
    assert once.path is not None
    twice = export_s2k(import_s2k(once.path).project, tmp_path / "twice.s2k")
    assert twice.path is not None
    assert once.path.read_text(encoding="utf-8") == twice.path.read_text(encoding="utf-8")


def _built_project() -> Project:
    """A 3D project made in the application: a sloped brace, loads in local axes."""
    section = ElasticSection(
        id=1,
        name="Box",
        E=2e11,
        A=0.01,
        Iz=2e-5,
        Iy=5e-5,
        G=8e10,
        J=3e-5,
        unit_weight=77000.0,
    )
    return Project(
        meta=ProjectMeta(name="built", units=UnitSystem.SI_M_N),
        nodes=[
            Node(
                id=1,
                coords=(0, 0, 0),
                restraint=(True,) * 6,
                spring=(1e6, 2e6, 3e6, 4e6, 5e6, 6e6),
            ),
            Node(id=2, coords=(0, 1, 3), mass=(4.0, 5.0, 6.0, 7.0, 8.0, 9.0)),
            Node(id=3, coords=(4, 1, 3)),
        ],
        sections=[section],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1, rho=78.5),
            ElasticBeamColumn(
                id=2,
                nodes=(2, 3),
                section_id=1,
                releases=FrameReleases(j=EndRelease(released=("M2", "M3"))),
            ),
        ],
        time_series=[LinearTimeSeries(id=1)],
        spectra=[
            ResponseSpectrum(
                id=1,
                name="RS",
                periods=[0.1, 0.5, 2.0],
                accelerations=[9.8, 3.0, 1.0],
                damping_ratio=0.05,
            )
        ],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="Q",
                time_series_id=1,
                element_loads=[UniformElementLoad(element_id=1, wy=1.5, wz=-2.0, wx=0.25)],
                point_loads=[PointElementLoad(element_id=2, py=3.0, pz=-4.0, x=0.3)],
            )
        ],
        analyses=[
            StaticCase(id=1, name="Q", pattern_ids=[1]),
            ModalCase(id=2, name="M", n_modes=3),
            ResponseSpectrumCase(
                id=3,
                name="RS-CQC",
                modal_case_id=2,
                spectrum_id=1,
                direction=1,
                combination="CQC",
                damping_ratio=0.05,
            ),
        ],
        combinations=[
            LoadCombination(id=1, name="1.5Q", terms=[CombinationTerm(ref_id=1, factor=1.5)])
        ],
    )


def _table_block(text: str, name: str) -> list[str]:
    """The lines of one ``TABLE: "name"`` block, for comparing two exports."""
    lines = text.splitlines()
    start = lines.index(f'TABLE:  "{name}"')
    end = next(
        index
        for index in range(start + 1, len(lines))
        if lines[index].startswith(("TABLE:", "END TABLE"))
    )
    return lines[start:end]


def test_a_spectrum_export_is_stable(tmp_path: Path) -> None:
    once = export_s2k(_built_project(), tmp_path / "once.s2k")
    assert once.path is not None
    twice = export_s2k(import_s2k(once.path).project, tmp_path / "twice.s2k")
    assert twice.path is not None
    first = once.path.read_text(encoding="utf-8")
    second = twice.path.read_text(encoding="utf-8")
    for table in (
        "FUNCTION - RESPONSE SPECTRUM - USER",
        "CASE - RESPONSE SPECTRUM 1 - GENERAL",
        "CASE - RESPONSE SPECTRUM 2 - LOAD ASSIGNMENTS",
    ):
        assert _table_block(first, table) == _table_block(second, table)


def test_a_project_made_here_survives_the_trip() -> None:
    project = _built_project()
    text, report = project_to_s2k(project)
    assert "FRAME LOCAL AXES ASSIGNMENTS 1 - TYPICAL" in text  # the steep brace is turned
    assert not report.skipped
    again = s2k_to_project(S2kFile(path=Path("built.s2k"), tables=parse_tables(text))).project
    _assert_same_model(project, again)


def test_the_export_reports_what_it_leaves_out() -> None:
    project = _built_project()
    project.analyses.append(StaticCase(id=4, name="push", pattern_ids=[1], n_steps=10))
    _, report = project_to_s2k(project)
    # Added masses and springs are written now, so they are no longer in "skipped".
    assert report.written["joint mass"] == 1
    assert report.written["joint spring"] == 1
    assert "joint mass" not in report.skipped and "joint spring" not in report.skipped
    assert report.skipped["Static analysis case"] == 1
    assert "Not written" in report.summary()


def test_a_mass_source_is_reported_when_exporting() -> None:
    project = _built_project()
    project.mass_source = MassSource()
    _, report = project_to_s2k(project)
    assert report.skipped["mass source"] == 1
    assert "mass source" in report.summary()


def test_area_modifier_leaves_mass_and_weight_alone(tmp_path: Path) -> None:
    body = (
        _CANTILEVER.format(units="KN, m, C", x=5, z=0, extra="")
        .replace("UnitWeight=0   UnitMass=0", "UnitWeight=78   UnitMass=7.8")
        .replace("Shape=General", "Shape=Channel   AMod=2")
    )
    imported = import_s2k(_write(tmp_path, body))
    section = imported.project.sections[0]
    member = imported.project.elements[0]
    assert isinstance(section, ElasticSection) and isinstance(member, ElasticBeamColumn)
    assert section.A == 20.0
    assert section.unit_weight * section.A == pytest.approx(78_000 * 10.0)
    assert member.rho == pytest.approx(7_800 * 10.0)
    # A shape this reader cannot draw keeps its properties, and says so once.
    assert imported.dropped["'Channel' section geometry (kept its properties)"] == 1


def test_a_load_in_a_user_coordinate_system_is_reported_not_guessed(tmp_path: Path) -> None:
    extra = (
        'TABLE:  "LOAD PATTERN DEFINITIONS"\n   LoadPat=L   SelfWtMult=0\n'
        'TABLE:  "FRAME LOADS - POINT"\n'
        "   Frame=B1   LoadPat=L   CoordSys=CSYS1   Type=Force   Dir=X   RelDist=0.5   Force=3\n"
    )
    imported = import_s2k(_cantilever(tmp_path, extra=extra))
    assert imported.project.load_patterns[0].point_loads == []
    assert imported.dropped["point load in another coordinate system"] == 1


# ──────────────────────────── damaged files ────────────────────────────
@pytest.mark.parametrize("count", ["1000000000", "1E300", "2.7", "0", "3", "5"])
def test_an_area_needs_exactly_four_joints(tmp_path: Path, count: str) -> None:
    """A bad NumJoints is a dropped area, not a billion-iteration loop or a truncation."""
    body = FRAME.read_text(encoding="utf-8").replace("NumJoints=4", f"NumJoints={count}")
    imported = import_s2k(_write(tmp_path, body))
    assert imported.dropped["area with other than four joints"] == 1
    assert not [e for e in imported.project.elements if isinstance(e, ShellMITC4Element)]


@pytest.mark.parametrize(
    "name", ["9" * 5000, "²"], ids=["thousands-of-digits", "digit-int-refuses"]
)
def test_a_name_that_cannot_be_an_integer_is_numbered(tmp_path: Path, name: str) -> None:
    """``isdigit`` is not an int guarantee: CPython refuses 4 300+ digits and ``²``."""
    body = _CANTILEVER.format(units="KN, m, C", x=5, z=0, extra="")
    for old, new in (("A", f"{name}A"), ("B", f"{name}B")):
        body = (
            body.replace(f"Joint={old} ", f"Joint={new} ")
            .replace(f"JointI={old}", f"JointI={new}")
            .replace(f"JointJ={old}", f"JointJ={new}")
        )
    imported = import_s2k(_write(tmp_path, body))
    assert [n.id for n in imported.project.nodes] == [1, 2]
    assert any("numbered 1" in note for note in imported.notes)


def _imports_or_says_why(tmp_path: Path, text: str) -> None:
    try:
        import_s2k(_write(tmp_path, text))
    except Sap2000TextError:
        return


@pytest.mark.parametrize("fixture", [PORTAL, FRAME], ids=["portal_2d", "frame_3d"])
def test_a_damaged_file_only_ever_raises_a_message(tmp_path: Path, fixture: Path) -> None:
    """Truncated and mutated files reach the caller as Sap2000TextError, never as a crash."""
    text = fixture.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    for cut in range(len(lines) + 1):
        _imports_or_says_why(tmp_path, "".join(lines[:cut]))
    rng = random.Random(20261024)
    for _ in range(80):
        body = list(text)
        for _ in range(3):
            body[rng.randrange(len(body))] = rng.choice('=" _\n\t0123456789xyz')
        _imports_or_says_why(tmp_path, "".join(body))
