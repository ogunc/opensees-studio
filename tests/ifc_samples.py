"""IFC files the way other programs write them, built in the test, never copied in.

Two small structures, in kN and millimetres (the units Tekla and Revit export in
most often), with nothing this application writes itself:

* :func:`analytical_portal` — an ``IfcStructuralAnalysisModel`` only: two
  columns (one fixed, one pinned with a rotational spring), a beam released at
  one end, a slab as a surface member, ``Pset_MaterialMechanical`` in MPa, an
  IPE300 (not an AISC shape) and W12X26 columns, one of them turned 90°, load
  cases written as plain ``IfcStructuralLoadGroup`` s with global loads, and a
  factored combination.
* :func:`physical_frame` — solids only: three columns, a beam that stops at the
  column faces, a secondary beam that lands on the first one's flange, a slab and
  a wall. No supports, no loads, no analytical model.

The expected numbers each builder promises are in its docstring and pinned in
``tests/unit/test_ifc_import.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.unit


def _file() -> tuple[Any, Any]:
    f = ifcopenshell.api.project.create_file(version="IFC4")
    project = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="Sample")
    mm = ifcopenshell.api.unit.add_si_unit(f, unit_type="LENGTHUNIT", prefix="MILLI")
    kn = ifcopenshell.api.unit.add_si_unit(f, unit_type="FORCEUNIT", prefix="KILO")
    mpa = ifcopenshell.api.unit.add_si_unit(f, unit_type="PRESSUREUNIT", prefix="MEGA")
    ifcopenshell.api.unit.assign_unit(f, units=[mm, kn, mpa])
    context = f.createIfcGeometricRepresentationContext(
        None,
        "Model",
        3,
        1e-5,
        f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0))),
        None,
    )
    project.RepresentationContexts = [context]
    return f, context


def _guid() -> str:
    return ifcopenshell.guid.new()


def _pt(f: Any, xyz: tuple[float, ...]) -> Any:
    return f.createIfcCartesianPoint([float(v) for v in xyz])


def _dir(f: Any, xyz: tuple[float, ...]) -> Any:
    return f.createIfcDirection([float(v) for v in xyz])


def _steel(f: Any) -> Any:
    steel = f.createIfcMaterial("S355", None, "steel")
    pset = ifcopenshell.api.pset.add_pset(f, product=steel, name="Pset_MaterialMechanical")
    ifcopenshell.api.pset.edit_pset(
        f, pset=pset, properties={"YoungModulus": 210000.0, "PoissonRatio": 0.3}
    )
    common = ifcopenshell.api.pset.add_pset(f, product=steel, name="Pset_MaterialCommon")
    ifcopenshell.api.pset.edit_pset(f, pset=common, properties={"MassDensity": 7850.0})
    yield_set = ifcopenshell.api.pset.add_pset(f, product=steel, name="Pset_MaterialSteel")
    ifcopenshell.api.pset.edit_pset(f, pset=yield_set, properties={"YieldStress": 355.0})
    return steel


def _ipe300(f: Any) -> Any:
    return f.createIfcIShapeProfileDef("AREA", "IPE300", None, 150.0, 300.0, 7.1, 10.7, 15.0)


def _ipe200(f: Any) -> Any:
    return f.createIfcIShapeProfileDef("AREA", "IPE200", None, 100.0, 200.0, 5.6, 8.5, 12.0)


def _w12x26(f: Any) -> Any:
    # AISC W12X26: d 12.2 in, bf 6.49 in, tw 0.23 in, tf 0.38 in.
    return f.createIfcIShapeProfileDef("AREA", "W12X26", None, 164.8, 309.9, 5.8, 9.7, None)


def _associate(f: Any, objects: list[Any], material: Any, profile: Any | None = None) -> None:
    if profile is not None:
        profile_set = f.createIfcMaterialProfileSet(
            profile.ProfileName,
            None,
            [f.createIfcMaterialProfile(profile.ProfileName, None, material, profile, None, None)],
            None,
        )
        relating = f.createIfcMaterialProfileSetUsage(profile_set, 5, None)
    else:
        relating = material
    f.createIfcRelAssociatesMaterial(_guid(), None, None, None, objects, relating)


# ──────────────────────────── analytical ────────────────────────────
def analytical_portal(path: Path) -> Path:
    """A 6 m × 4 m portal in the X-Z plane, plus a 6 m × 3 m slab beside it.

    Nodes ``N1 (0,0,0)`` fixed, ``N2 (0,0,4000)``, ``N3 (6000,0,4000)``,
    ``N4 (6000,0,0)`` pinned with ``RotationalStiffnessY = 5000 kN·mm/rad``, and
    ``N5 (0,3000,4000)``, ``N6 (6000,3000,4000)`` for the slab.

    Members: ``C1`` (N1→N2, W12X26, ``Axis`` +X, the default),
    ``C2`` (N4→N3, W12X26, ``Axis`` +Y: turned 90°), ``B1`` (N2→N3, IPE300,
    released about its local z at N3), ``S1`` the slab N2-N3-N6-N5, 200 mm of
    ``C30/37`` with no properties.

    Load cases: ``DEAD`` (``-5 kN/m`` global Z on B1, ``-0.000005
    kN/mm²`` global Z on S1), ``SELF`` (self weight ×1, an ``IfcStructuralLoadCase``) and ``LIVE`` (``-20 kN`` global Z at the middle of
    B1, ``10 kN`` along X at N2); combination ``ULS = 1.2 DEAD + 1.6 LIVE``.
    """
    f, context = _file()
    steel = _steel(f)
    concrete = f.createIfcMaterial("C30/37", None, "concrete")
    model = f.createIfcStructuralAnalysisModel(
        _guid(), None, "Analysis", None, None, "LOADING_3D", None, None, None, None
    )

    def vertex(xyz: tuple[float, float, float]) -> Any:
        return f.createIfcVertexPoint(_pt(f, xyz))

    def topology(item: Any, kind: str) -> Any:
        return f.createIfcProductDefinitionShape(
            None, None, [f.createIfcTopologyRepresentation(context, "Reference", kind, [item])]
        )

    points = {
        "N1": (0.0, 0.0, 0.0),
        "N2": (0.0, 0.0, 4000.0),
        "N3": (6000.0, 0.0, 4000.0),
        "N4": (6000.0, 0.0, 0.0),
        "N5": (0.0, 3000.0, 4000.0),
        "N6": (6000.0, 3000.0, 4000.0),
    }
    vertices = {name: vertex(xyz) for name, xyz in points.items()}
    connections: dict[str, Any] = {}
    true, false = f.createIfcBoolean(True), f.createIfcBoolean(False)
    for name, v in vertices.items():
        c = f.createIfcStructuralPointConnection(
            _guid(), None, name, None, None, None, topology(v, "Vertex"), None, None
        )
        connections[name] = c
    connections["N1"].AppliedCondition = f.createIfcBoundaryNodeCondition(
        "Fixed", true, true, true, true, true, true
    )
    connections["N4"].AppliedCondition = f.createIfcBoundaryNodeCondition(
        "Pinned+spring",
        true,
        true,
        true,
        false,
        f.createIfcRotationalStiffnessMeasure(5000.0),
        false,
    )

    def curve(name: str, a: str, b: str, axis: tuple[float, float, float], profile: Any) -> Any:
        edge = f.createIfcEdge(vertices[a], vertices[b])
        m = f.createIfcStructuralCurveMember(
            _guid(),
            None,
            name,
            None,
            None,
            None,
            topology(edge, "Edge"),
            "RIGID_JOINED_MEMBER",
            _dir(f, axis),
        )
        _associate(f, [m], steel, profile)
        for end in (a, b):
            f.createIfcRelConnectsStructuralMember(
                _guid(), None, None, None, m, connections[end], None, None, None, None
            )
        return m

    c1 = curve("C1", "N1", "N2", (1.0, 0.0, 0.0), _w12x26(f))
    c2 = curve("C2", "N4", "N3", (0.0, 1.0, 0.0), _w12x26(f))
    b1 = curve("B1", "N2", "N3", (0.0, 0.0, 1.0), _ipe300(f))
    for rel in b1.ConnectedBy:
        if rel.RelatedStructuralConnection == connections["N3"]:
            rel.AppliedCondition = f.createIfcBoundaryNodeCondition(
                "Pin", true, true, true, true, true, false
            )
    loop = [("N2", "N3"), ("N3", "N6"), ("N6", "N5"), ("N5", "N2")]
    edges = [
        f.createIfcOrientedEdge(None, None, f.createIfcEdge(vertices[a], vertices[b]), True)
        for a, b in loop
    ]
    face = f.createIfcFaceSurface(
        [f.createIfcFaceOuterBound(f.createIfcEdgeLoop(edges), True)],
        f.createIfcPlane(
            f.createIfcAxis2Placement3D(
                _pt(f, points["N2"]), _dir(f, (0, 0, 1)), _dir(f, (1, 0, 0))
            )
        ),
        True,
    )
    s1 = f.createIfcStructuralSurfaceMember(
        _guid(), None, "S1", None, None, None, topology(face, "Face"), "SHELL", 200.0
    )
    _associate(f, [s1], concrete)
    for name in ("N2", "N3", "N6", "N5"):
        f.createIfcRelConnectsStructuralMember(
            _guid(), None, None, None, s1, connections[name], None, None, None, None
        )
    members = [*connections.values(), c1, c2, b1, s1]
    f.createIfcRelAssignsToGroup(_guid(), None, None, None, members, None, model)

    def group(name: str, kind: str) -> Any:
        return f.createIfcStructuralLoadGroup(
            _guid(), None, name, None, None, kind, "PERMANENT_G", "DEAD_LOAD_G", 1.0, None
        )

    def action(
        cls: str,
        load: Any,
        target: Any,
        kind: str | None = None,
        at: tuple[float, ...] | None = None,
    ) -> Any:
        args = [_guid(), None, None, None, None, None, None, load, "GLOBAL_COORDS"]
        if cls == "IfcStructuralPointAction":
            a = f.createIfcStructuralPointAction(*args, None)
            if at is not None:
                a.Representation = topology(vertex(at), "Vertex")
        elif cls == "IfcStructuralCurveAction":
            a = f.createIfcStructuralCurveAction(*args, None, "TRUE_LENGTH", kind)
        else:
            a = f.createIfcStructuralPlanarAction(*args, None, "TRUE_LENGTH", kind)
        f.createIfcRelConnectsStructuralActivity(_guid(), None, None, None, target, a)
        return a

    dead = group("DEAD", "LOAD_CASE")
    dead_actions = [
        action(
            "IfcStructuralCurveAction",
            f.createIfcStructuralLoadLinearForce("w", 0.0, 0.0, -0.005, None, None, None),
            b1,
            "CONST",
        ),
        action(
            "IfcStructuralPlanarAction",
            f.createIfcStructuralLoadPlanarForce("q", 0.0, 0.0, -0.000005),
            s1,
            "CONST",
        ),
    ]
    f.createIfcRelAssignsToGroup(_guid(), None, None, None, dead_actions, None, dead)
    live = group("LIVE", "LOAD_CASE")
    live_actions = [
        action(
            "IfcStructuralPointAction",
            f.createIfcStructuralLoadSingleForce("P", 0.0, 0.0, -20.0, None, None, None),
            b1,
            at=(3000.0, 0.0, 4000.0),
        ),
        action(
            "IfcStructuralPointAction",
            f.createIfcStructuralLoadSingleForce("H", 10.0, 0.0, 0.0, None, None, None),
            connections["N2"],
        ),
    ]
    f.createIfcRelAssignsToGroup(_guid(), None, None, None, live_actions, None, live)
    combo = group("ULS", "LOAD_COMBINATION")
    f.createIfcRelAssignsToGroupByFactor(_guid(), None, None, None, [dead], None, combo, 1.2)
    f.createIfcRelAssignsToGroupByFactor(_guid(), None, None, None, [live], None, combo, 1.6)
    # Self weight on DEAD, the way the standard writes it: a load case.
    case = f.createIfcStructuralLoadCase(
        _guid(),
        None,
        "SELF",
        None,
        None,
        "LOAD_CASE",
        "PERMANENT_G",
        "DEAD_LOAD_G",
        1.0,
        None,
        (0.0, 0.0, -1.0),
    )
    model.LoadedBy = [dead, live, combo, case]
    f.write(str(path))
    return path


# ──────────────────────────── physical ────────────────────────────
def physical_frame(path: Path) -> Path:
    """Solids as a detailer draws them: members meet at faces, not at axes.

    Columns W12X26, 4000 mm tall from z = 0: ``C1`` at (0, 0) and ``C3`` at
    (3000, 4000) with the depth along X, ``C2`` at (6000, 0) turned 90° (depth
    along Y). ``B1`` (IPE300, top flush at z = 4000) runs from C1's face (x = 155)
    to C2's flange edge (x = 5917.5); ``B2`` (IPE200, top flush) runs along Y from
    B1's flange (y = 75) at x = 3000 to C3's flange (y = 3917.5). A 200 mm slab
    from z = 3800 to 4000 covers x 0 to 3000, y 0 to 4000, and a 200 mm wall stands
    between C1 and C2 from z = 0 to 3000.

    Joined, that is a frame with nodes at the three column bases and tops and
    B1 split at x = 3000 where B2 lands.
    """
    f, context = _file()
    steel = _steel(f)
    concrete = f.createIfcMaterial("C30/37", None, "concrete")
    body = f.createIfcGeometricRepresentationSubContext(
        "Body", "Model", None, None, None, None, context, None, "MODEL_VIEW", None
    )

    def placed(
        cls: str,
        name: str,
        origin: tuple[float, ...],
        axis: tuple[float, ...],
        ref: tuple[float, ...],
        solid: Any,
    ) -> Any:
        placement = f.createIfcLocalPlacement(
            None, f.createIfcAxis2Placement3D(_pt(f, origin), _dir(f, axis), _dir(f, ref))
        )
        shape = f.createIfcProductDefinitionShape(
            None, None, [f.createIfcShapeRepresentation(body, "Body", "SweptSolid", [solid])]
        )
        return getattr(f, f"create{cls}")(
            _guid(), None, name, None, None, placement, shape, None, None
        )

    def extrusion(profile: Any, depth: float) -> Any:
        return f.createIfcExtrudedAreaSolid(
            profile,
            f.createIfcAxis2Placement3D(_pt(f, (0.0, 0.0, 0.0)), None, None),
            _dir(f, (0, 0, 1)),
            depth,
        )

    products: list[Any] = []
    # Columns: placement X = ref, Y = Z × X is the profile depth.
    for name, origin, ref in (
        ("C1", (0.0, 0.0, 0.0), (0.0, -1.0, 0.0)),  # depth along +X
        ("C2", (6000.0, 0.0, 0.0), (1.0, 0.0, 0.0)),  # depth along +Y (turned)
        ("C3", (3000.0, 4000.0, 0.0), (0.0, -1.0, 0.0)),
    ):
        col = placed("IfcColumn", name, origin, (0, 0, 1), ref, extrusion(_w12x26(f), 4000.0))
        _associate(f, [col], steel, _w12x26(f))
        products.append(col)
    b1 = placed(
        "IfcBeam",
        "B1",
        (155.0, 0.0, 3850.0),
        (1, 0, 0),
        (0, 1, 0),
        extrusion(_ipe300(f), 5917.5 - 155.0),
    )
    _associate(f, [b1], steel, _ipe300(f))
    b2 = placed(
        "IfcBeam",
        "B2",
        (3000.0, 75.0, 3900.0),
        (0, 1, 0),
        (-1, 0, 0),
        extrusion(_ipe200(f), 3917.5 - 75.0),
    )
    _associate(f, [b2], steel, _ipe200(f))
    products += [b1, b2]
    slab_profile = f.createIfcRectangleProfileDef(
        "AREA", None, f.createIfcAxis2Placement2D(_pt(f, (1500.0, 2000.0)), None), 3000.0, 4000.0
    )
    slab = placed(
        "IfcSlab", "Slab", (0.0, 0.0, 3800.0), (0, 0, 1), (1, 0, 0), extrusion(slab_profile, 200.0)
    )
    wall_profile = f.createIfcRectangleProfileDef(
        "AREA", None, f.createIfcAxis2Placement2D(_pt(f, (3000.0, 0.0)), None), 5690.0, 200.0
    )
    wall = placed(
        "IfcWall", "Wall", (0.0, 0.0, 0.0), (0, 0, 1), (1, 0, 0), extrusion(wall_profile, 3000.0)
    )
    _associate(f, [slab, wall], concrete)
    products += [slab, wall]
    site = f.createIfcBuildingStorey(
        _guid(), None, "Level 1", None, None, None, None, None, "ELEMENT", 0.0
    )
    f.createIfcRelContainedInSpatialStructure(_guid(), None, None, None, products, site)
    f.write(str(path))
    return path
