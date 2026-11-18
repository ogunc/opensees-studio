"""File → Export → IFC: a valid IFC4 file with the physical and the analytical model."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("ifcopenshell")
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.validate

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    EndRelease,
    FloorLoad,
    FrameReleases,
    ImposedDisplacement,
    LinearTimeSeries,
    LoadCombination,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ShellMITC4Element,
    StaticCase,
    Storey,
    SurfaceLoad,
    TrapezoidalElementLoad,
    TrussElement,
    UniformElementLoad,
)
from opensees_studio.core.aisc import get_shape, shape_to_elastic_section
from opensees_studio.core.combinations import CombinationTerm
from opensees_studio.core.sections import PipeShape, RectShape
from opensees_studio.core.units import UnitSystem
from opensees_studio.services.ifc_export import export_ifc
from opensees_studio.services.persistence import load_project

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
FIXED = (True,) * 6


class _Errors(list):
    def error(self, msg, *args, **_kw):  # type: ignore[no-untyped-def]
        self.append(msg % args if args else msg)

    def warning(self, *a, **k):  # type: ignore[no-untyped-def]
        pass

    info = debug = warning


def _validate(path: Path) -> list[str]:
    errors = _Errors()
    ifcopenshell.validate.validate(ifcopenshell.open(str(path)), errors)
    return list(errors)


def _bay(tmp_path: Path) -> tuple[Project, ifcopenshell.file]:
    """A 3D bay: two columns, a beam, a brace, a slab, with every kind of load."""
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=FIXED),
        Node(id=2, coords=(6.0, 0.0, 0.0), restraint=FIXED),
        Node(id=3, coords=(0.0, 0.0, 3.0)),
        Node(id=4, coords=(6.0, 0.0, 3.0)),
        Node(id=5, coords=(6.0, 4.0, 3.0)),
        Node(id=6, coords=(0.0, 4.0, 3.0)),
        Node(id=7, coords=(6.0, 4.0, 0.0), restraint=FIXED),
        Node(id=8, coords=(0.0, 4.0, 0.0), restraint=FIXED),
    ]
    sections = [
        ElasticSection(
            id=1,
            name="C400",
            E=3e10,
            A=0.16,
            Iz=2e-3,
            Iy=2e-3,
            G=1e10,
            J=3e-3,
            shape=RectShape(d=0.4, b=0.4),
        ),
        ElasticSection(
            id=2,
            name="P",
            E=2e11,
            A=3e-3,
            Iz=1e-5,
            Iy=1e-5,
            G=8e10,
            J=2e-5,
            shape=PipeShape(od=0.2, t=0.01),
        ),
        ElasticMembranePlateSection(id=3, name="Slab 20", E=3e10, nu=0.2, h=0.2),
    ]
    elements = [
        ElasticBeamColumn(id=1, nodes=(1, 3), section_id=1),
        ElasticBeamColumn(id=2, nodes=(2, 4), section_id=1),
        ElasticBeamColumn(id=6, nodes=(7, 5), section_id=1),
        ElasticBeamColumn(id=7, nodes=(8, 6), section_id=1),
        ElasticBeamColumn(
            id=3,
            nodes=(3, 4),
            section_id=1,
            releases=FrameReleases(j=EndRelease(released=("M3",))),
        ),
        ElasticBeamColumn(id=8, nodes=(4, 5), section_id=1),
        ElasticBeamColumn(id=9, nodes=(5, 6), section_id=1),
        ElasticBeamColumn(id=10, nodes=(6, 3), section_id=1),
        TrussElement(id=4, nodes=(1, 4), area=2e-3, material_id=1),
        ShellMITC4Element(id=5, nodes=(3, 4, 5, 6), section_id=3),
    ]
    from opensees_studio.core import ElasticUniaxial

    project = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=sections,
        materials=[ElasticUniaxial(id=1, E=2e11)],
        elements=elements,
        storeys=[Storey(id=1, name="First floor", elevation=3.0)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(id=1, name="DEAD", time_series_id=1, self_weight=1.0),
            PlainLoadPattern(
                id=2,
                name="LIVE",
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=3, forces=(10.0, 0.0, -5.0, 0.0, 0.0, 0.0))],
                element_loads=[UniformElementLoad(element_id=3, wz=-2.0)],
                distributed_loads=[
                    TrapezoidalElementLoad(
                        element_id=3, x_start=0.2, x_end=0.8, wz_start=-1.0, wz_end=-3.0
                    )
                ],
                surface_loads=[SurfaceLoad(element_id=5, value=-4.0)],
                floor_loads=[FloorLoad(nodes=(3, 4, 5, 6), value=1.0)],
                imposed_displacements=[ImposedDisplacement(node_id=1, dof=3, value=-0.01)],
            ),
        ],
        analyses=[
            StaticCase(id=1, name="DEAD", pattern_ids=[1]),
            StaticCase(id=2, name="LIVE", pattern_ids=[2]),
        ],
        combinations=[
            LoadCombination(
                id=1,
                name="1.2D+1.6L",
                terms=[
                    CombinationTerm(ref_id=1, factor=1.2),
                    CombinationTerm(ref_id=2, factor=1.6),
                ],
            )
        ],
    )
    report = export_ifc(project, tmp_path / "bay.ifc")
    assert _validate(report.path) == []
    return project, ifcopenshell.open(str(report.path))


@pytest.mark.parametrize(
    "example",
    [
        "space_frame_3d",
        "building_3storey_diaphragm",
        "ex1b_portal2d",
        "basic_truss",
        "isolated_portal2d",
    ],
)
def test_bundled_examples_export_to_valid_ifc4(example: str, tmp_path: Path) -> None:
    report = export_ifc(load_project(EXAMPLES / f"{example}.osmodel"), tmp_path / "m.ifc")
    assert _validate(report.path) == []
    f = ifcopenshell.open(str(report.path))
    assert f.schema == "IFC4"
    assert report.analytical == len(f.by_type("IfcStructuralMember"))
    assert len(f.by_type("IfcRelAssignsToProduct")) == report.analytical


def test_members_are_classified_and_contained_in_their_storey(tmp_path: Path) -> None:
    _project, f = _bay(tmp_path)
    assert {e.Tag for e in f.by_type("IfcColumn")} == {"1", "2", "6", "7"}
    assert {e.Tag for e in f.by_type("IfcBeam")} == {"3", "8", "9", "10"}
    assert [e.Tag for e in f.by_type("IfcMember")] == ["4"]  # the truss brace
    (slab,) = f.by_type("IfcSlab")
    assert slab.Tag == "5"
    storeys = {s.Name: s for s in f.by_type("IfcBuildingStorey")}
    assert set(storeys) == {"Base", "First floor"}
    beam = next(e for e in f.by_type("IfcBeam") if e.Tag == "3")
    assert beam.ContainedInStructure[0].RelatingStructure == storeys["First floor"]


def test_profiles_come_from_the_section_shapes(tmp_path: Path) -> None:
    _project, f = _bay(tmp_path)
    column = next(e for e in f.by_type("IfcColumn") if e.Tag == "1")
    swept = column.Representation.Representations[0].Items[0].SweptArea
    assert swept.is_a("IfcRectangleProfileDef") and swept.ProfileName == "C400"
    assert (swept.XDim, swept.YDim) == pytest.approx((0.4, 0.4))
    sets = f.by_type("IfcMaterialProfileSet")
    assert {s.Name for s in sets} >= {"C400"}


def test_an_aisc_name_becomes_an_i_profile_and_the_geometry_has_the_right_size(
    tmp_path: Path,
) -> None:
    section = shape_to_elastic_section(
        get_shape("W14X90"),
        elastic_modulus=29000.0,
        shear_modulus=11200.0,
        units=UnitSystem.US_IN_KIP,
        ndm=3,
    )
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[Node(id=1, coords=(0.0, 0.0, 144.0)), Node(id=2, coords=(240.0, 0.0, 144.0))],
        sections=[section],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=section.id)],
    )
    project.meta.units = UnitSystem.US_IN_KIP
    report = export_ifc(project, tmp_path / "w.ifc")
    f = ifcopenshell.open(str(report.path))
    (beam,) = f.by_type("IfcBeam")
    swept = beam.Representation.Representations[0].Items[0].SweptArea
    assert swept.is_a("IfcIShapeProfileDef")
    assert (swept.OverallDepth, swept.OverallWidth) == pytest.approx((14.0, 14.5))
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    verts = np.array(ifcopenshell.geom.create_shape(settings, beam).geometry.verts).reshape(-1, 3)
    span = verts.max(axis=0) - verts.min(axis=0)  # metres
    assert span[0] == pytest.approx(240 * 0.0254, rel=1e-6)  # along the axis
    assert span[2] == pytest.approx(14.0 * 0.0254, rel=1e-3)  # depth stands up
    assert span[1] == pytest.approx(14.5 * 0.0254, rel=1e-3)
    units = {
        u.UnitType: u for u in f.by_type("IfcUnitAssignment")[0].Units if u.is_a("IfcNamedUnit")
    }
    assert units["LENGTHUNIT"].Name.lower() == "inch"
    assert units["FORCEUNIT"].Name.lower() == "kip"


def test_the_analytical_model_has_nodes_supports_releases_and_links(tmp_path: Path) -> None:
    _project, f = _bay(tmp_path)
    (model,) = f.by_type("IfcStructuralAnalysisModel")
    assert model.PredefinedType == "LOADING_3D"
    connections = {c.Name: c for c in f.by_type("IfcStructuralPointConnection")}
    assert len(connections) == 8
    support = connections["N1"].AppliedCondition
    assert support.TranslationalStiffnessZ.wrappedValue is True
    assert connections["N3"].AppliedCondition is None
    beam = next(m for m in f.by_type("IfcStructuralCurveMember") if m.Name == "E3")
    end_j = next(r for r in beam.ConnectedBy if r.RelatedStructuralConnection.Name == "N4")
    assert end_j.AppliedCondition.RotationalStiffnessZ.wrappedValue is False  # M3 released
    assert f.by_type("IfcStructuralSurfaceMember")[0].Thickness == pytest.approx(0.2)
    truss = next(m for m in f.by_type("IfcStructuralCurveMember") if m.Name == "E4")
    assert truss.PredefinedType == "PIN_JOINED_MEMBER"


def test_loads_cases_and_combinations(tmp_path: Path) -> None:
    _project, f = _bay(tmp_path)
    cases = {c.Name: c for c in f.by_type("IfcStructuralLoadCase")}
    assert set(cases) == {"DEAD", "LIVE"}
    assert cases["DEAD"].ActionSource == "DEAD_LOAD_G"
    assert list(cases["DEAD"].SelfWeightCoefficients) == [0.0, 0.0, -1.0]
    live = {a for rel in cases["LIVE"].IsGroupedBy for a in rel.RelatedObjects}
    kinds = sorted(a.is_a() for a in live)
    assert kinds.count("IfcStructuralPointAction") == 2  # the force and the settlement
    assert kinds.count("IfcStructuralPlanarAction") == 1
    # The uniform load, the trapezoid, and the 6 x 4 two-way panel: three pieces on
    # each long edge, two on each short one.
    assert kinds.count("IfcStructuralCurveAction") == 1 + 1 + (3 + 2 + 3 + 2)
    force = next(a for a in live if a.AppliedLoad.is_a("IfcStructuralLoadSingleForce"))
    assert (force.AppliedLoad.ForceX, force.AppliedLoad.ForceZ) == (10.0, -5.0)
    (combo,) = [
        g for g in f.by_type("IfcStructuralLoadGroup") if g.PredefinedType == "LOAD_COMBINATION"
    ]
    factors = {
        rel.RelatedObjects[0].Name: rel.Factor
        for rel in f.by_type("IfcRelAssignsToGroupByFactor")
        if rel.RelatingGroup == combo
    }
    assert factors == {"DEAD": 1.2, "LIVE": 1.6}


def test_a_2d_model_is_an_in_plane_analysis_model(tmp_path: Path) -> None:
    report = export_ifc(load_project(EXAMPLES / "ex1b_portal2d.osmodel"), tmp_path / "p.ifc")
    (model,) = ifcopenshell.open(str(report.path)).by_type("IfcStructuralAnalysisModel")
    assert model.PredefinedType == "IN_PLANE_LOADING_2D"


def test_what_is_left_out_is_reported(tmp_path: Path) -> None:
    report = export_ifc(load_project(EXAMPLES / "isolated_portal2d.osmodel"), tmp_path / "i.ifc")
    text = report.summary()
    assert "ElastomericBearingPlasticity" in text and "not in the analytical model" in text


def test_support_springs_are_stiffness_values(tmp_path: Path) -> None:
    project = load_project(EXAMPLES / "cantilever.osmodel")
    base = project.nodes[0]
    project.nodes[0] = base.model_copy(
        update={"restraint": (True,) * 4 + (False, True), "spring": (0, 0, 0, 0, 2e3, 0)}
    )
    path = tmp_path / "springs.ifc"
    export_ifc(project, path)
    assert _validate(path) == []
    f = ifcopenshell.open(str(path))
    condition = next(
        c.AppliedCondition
        for c in f.by_type("IfcStructuralPointConnection")
        if c.Name == f"N{base.id}"
    )
    assert condition.RotationalStiffnessY.is_a("IfcRotationalStiffnessMeasure")
    assert condition.RotationalStiffnessY.wrappedValue == pytest.approx(2e3)
    assert condition.TranslationalStiffnessX.wrappedValue is True


@pytest.mark.parametrize(
    ("name", "profile"),
    [
        ("C10X30", "IfcUShapeProfileDef"),
        ("WT7X45", "IfcTShapeProfileDef"),
        ("HSS10X10X1_2", "IfcRectangleHollowProfileDef"),
    ],
)
def test_every_aisc_profile_kind_has_its_ifc_profile(
    name: str, profile: str, tmp_path: Path
) -> None:
    section = shape_to_elastic_section(
        get_shape(name), elastic_modulus=29000.0, units=UnitSystem.US_IN_KIP, ndm=3
    )
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[Node(id=1, coords=(0.0, 0.0, 144.0)), Node(id=2, coords=(240.0, 0.0, 144.0))],
        sections=[section.model_copy(update={"name": "custom"})],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=section.id)],
    )
    project.meta.units = UnitSystem.US_IN_KIP
    report = export_ifc(project, tmp_path / "p.ifc")
    assert _validate(report.path) == []
    (beam,) = ifcopenshell.open(str(report.path)).by_type("IfcBeam")
    assert beam.Representation.Representations[0].Items[0].SweptArea.is_a(profile)
