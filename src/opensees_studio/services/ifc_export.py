"""Export a project as IFC4: the physical BIM model and the structural analysis model.

The file carries two linked descriptions of the same structure:

- **Physical** (what BIM viewers draw): an ``IfcProject`` → ``IfcSite`` →
  ``IfcBuilding`` → one ``IfcBuildingStorey`` per storey (or a single level),
  with every frame member as an ``IfcColumn`` (within 10° of vertical),
  ``IfcBeam`` (within 10° of horizontal) or ``IfcMember`` (a brace, any truss
  bar), extruded along its axis from its profile — an I, angle, hollow or solid
  circle or rectangle from the section's shape, an AISC name looked up in the
  library, else the rectangle of the section's extent — and every shell as an
  ``IfcSlab``, ``IfcWall`` or ``IfcPlate`` by its tilt, its thickness extruded
  along its normal. Members carry an ``IfcMaterialProfileSet`` named after the
  section; shells an ``IfcMaterial`` named after theirs.
- **Analytical** (what structural software reads): an
  ``IfcStructuralAnalysisModel`` with an ``IfcStructuralPointConnection`` per
  node (its restraints as an ``IfcBoundaryNodeCondition``), an
  ``IfcStructuralCurveMember`` per frame or truss (end releases on the
  connection relationship) and an ``IfcStructuralSurfaceMember`` per shell, and
  one ``IfcStructuralLoadCase`` per Plain pattern: nodal forces, uniform and
  trapezoidal member loads (floor loads as the member loads they become),
  point loads on members, shell pressures, imposed displacements and the
  self-weight coefficients. Load combinations become ``IfcStructuralLoadGroup``
  of type ``LOAD_COMBINATION`` with each case assigned by its factor.

Each analytical member is assigned to its physical element
(``IfcRelAssignsToProduct``). Coordinates and values are in the project's own
units (metre, millimetre, foot or inch; newton or kip), declared in the file.
A 2D model is written as it stands, in the X-Z plane.

This module imports ``ifcopenshell`` (a GUI dependency) when it runs, so the
headless services stay importable without it. No Qt.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from opensees_studio.core import (
    CorotTrussElement,
    PlainLoadPattern,
    Project,
    ShellMITC4Element,
    TrussElement,
)
from opensees_studio.core.area_loads import pattern_distributed_loads
from opensees_studio.core.combinations import guess_load_role
from opensees_studio.core.frame_members import section_extents
from opensees_studio.core.geometry.elements import FRAME_ELEMENT_CLASSES
from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.plane import dof_indices
from opensees_studio.core.sections import (
    SHELL_SECTION_CLASSES,
    AngleShape,
    ChannelShape,
    PipeShape,
    RectShape,
    TeeShape,
    TubeShape,
    WideFlangeShape,
)
from opensees_studio.core.storeys import base_elevation, sorted_storeys
from opensees_studio.core.units import UnitSystem, length_scale

VERTICAL_TOLERANCE_DEG = 10.0
"""A member within this angle of vertical is a column, of horizontal a beam."""

_LENGTH_UNIT: dict[UnitSystem, tuple[str, str | None]] = {
    UnitSystem.SI_M_N: ("si", None),
    UnitSystem.SI_MM_N: ("si", "MILLI"),
    UnitSystem.US_FT_KIP: ("conv", "foot"),
    UnitSystem.US_IN_KIP: ("conv", "inch"),
}
_FORCE_UNIT: dict[UnitSystem, tuple[str, str | None]] = {
    UnitSystem.SI_M_N: ("si", None),
    UnitSystem.SI_MM_N: ("si", None),
    UnitSystem.US_FT_KIP: ("conv", "kip"),
    UnitSystem.US_IN_KIP: ("conv", "kip"),
}
#: Load role -> (IfcActionTypeEnum, IfcActionSourceTypeEnum).
_ACTION: dict[str, tuple[str, str]] = {
    "D": ("PERMANENT_G", "DEAD_LOAD_G"),
    "L": ("VARIABLE_Q", "LIVE_LOAD_Q"),
    "Lr": ("VARIABLE_Q", "LIVE_LOAD_Q"),
    "S": ("VARIABLE_Q", "SNOW_S"),
    "R": ("VARIABLE_Q", "RAIN_R"),
    "W": ("VARIABLE_Q", "WIND_W"),
    "E": ("EXTRAORDINARY_A", "EARTHQUAKE_E"),
}


class IfcExportError(RuntimeError):
    """The model cannot be written (ifcopenshell missing, or bad geometry)."""


def _api() -> Any:
    try:
        import ifcopenshell
        import ifcopenshell.api.aggregate
        import ifcopenshell.api.context
        import ifcopenshell.api.geometry
        import ifcopenshell.api.material
        import ifcopenshell.api.project
        import ifcopenshell.api.root
        import ifcopenshell.api.spatial
        import ifcopenshell.api.structural
        import ifcopenshell.api.unit
    except ImportError as exc:  # pragma: no cover - the GUI install has it
        raise IfcExportError(
            "IFC export needs ifcopenshell: pip install ifcopenshell (it comes with the "
            "desktop install)."
        ) from exc
    return ifcopenshell


class _Writer:
    """One export: the file, its contexts and the lookups shared by both models."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.ios = _api()
        self.api = self.ios.api
        self.f = self.api.project.create_file(version="IFC4")
        self.coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
        self.sections = {s.id: s for s in project.sections}
        self.materials = {m.id: m for m in project.materials}
        self.notes: list[str] = []

    # ── project, units, spatial structure ──────────────────────────
    def header(self, name: str) -> None:
        api, f = self.api, self.f
        self.ifc_project = api.root.create_entity(
            f, ifc_class="IfcProject", name=self.project.meta.name or name
        )
        units = self.project.meta.units
        kind, value = _LENGTH_UNIT[units]
        length = (
            api.unit.add_si_unit(f, unit_type="LENGTHUNIT", prefix=value)
            if kind == "si"
            else api.unit.add_conversion_based_unit(f, name=value)
        )
        kind, value = _FORCE_UNIT[units]
        force = (
            api.unit.add_si_unit(f, unit_type="FORCEUNIT")
            if kind == "si"
            else api.unit.add_conversion_based_unit(f, name=value)
        )
        angle = api.unit.add_si_unit(f, unit_type="PLANEANGLEUNIT")
        time = api.unit.add_si_unit(f, unit_type="TIMEUNIT")
        derived = [
            self._derived("LINEARFORCEUNIT", {force: 1, length: -1}),
            self._derived("PLANARFORCEUNIT", {force: 1, length: -2}),
            self._derived("TORQUEUNIT", {force: 1, length: 1}),
            self._derived("LINEARMOMENTUNIT", {force: 1}),
            self._derived("LINEARSTIFFNESSUNIT", {force: 1, length: -1}),
            self._derived("ROTATIONALSTIFFNESSUNIT", {force: 1, length: 1, angle: -1}),
        ]
        api.unit.assign_unit(f, units=[length, force, angle, time, *derived])
        import ifcopenshell.util.unit

        # The geometry API takes SI lengths; the file's coordinates are model units.
        self.si = float(ifcopenshell.util.unit.calculate_unit_scale(f))
        self.model_ctx = api.context.add_context(f, context_type="Model")
        self.body = api.context.add_context(
            f,
            context_type="Model",
            context_identifier="Body",
            target_view="MODEL_VIEW",
            parent=self.model_ctx,
        )
        self.reference = api.context.add_context(
            f,
            context_type="Model",
            context_identifier="Reference",
            target_view="GRAPH_VIEW",
            parent=self.model_ctx,
        )
        site = api.root.create_entity(f, ifc_class="IfcSite", name="Site")
        api.aggregate.assign_object(f, products=[site], relating_object=self.ifc_project)
        self.building = api.root.create_entity(f, ifc_class="IfcBuilding", name="Building")
        api.aggregate.assign_object(f, products=[self.building], relating_object=site)
        levels = [
            (s.name or f"Storey {s.id}", float(s.elevation)) for s in sorted_storeys(self.project)
        ]
        base = base_elevation(self.project)
        if not levels or levels[0][1] > base + 1e-9:
            levels.insert(0, ("Base", base))
        self.storeys: list[tuple[float, Any]] = []
        for label, elevation in levels:
            storey = api.root.create_entity(f, ifc_class="IfcBuildingStorey", name=label)
            storey.Elevation = elevation
            api.aggregate.assign_object(f, products=[storey], relating_object=self.building)
            self.storeys.append((elevation, storey))

    def _support_value(self, node: Any, slot: int, in_model: bool) -> Any:
        """A DOF of a support: fixed/free (IfcBoolean) or a spring stiffness (IFC4 select)."""
        f = self.f
        if in_model and not node.restraint[slot] and node.spring[slot] > 0:
            measure = "IfcLinearStiffnessMeasure" if slot < 3 else "IfcRotationalStiffnessMeasure"
            return f.create_entity(measure, float(node.spring[slot]))
        return f.createIfcBoolean(bool(node.restraint[slot]) and in_model)

    def _derived(self, unit_type: str, elements: dict[Any, int]) -> Any:
        return self.api.unit.add_derived_unit(
            self.f, unit_type=unit_type, userdefinedtype=None, attributes=elements
        )

    def storey_for(self, z: float) -> Any:
        """The storey a product at elevation ``z`` belongs to (the last at or below it)."""
        chosen = self.storeys[0][1]
        for elevation, storey in self.storeys:
            if elevation <= z + 1e-9:
                chosen = storey
        return chosen

    # ── geometry helpers ─────────────────────────────────────────────
    def point(self, xyz: Sequence[float] | np.ndarray) -> Any:
        return self.f.createIfcCartesianPoint([float(v) for v in xyz])

    def direction(self, xyz: Sequence[float] | np.ndarray) -> Any:
        return self.f.createIfcDirection([float(v) for v in xyz])

    def placement(self, product: Any, origin: np.ndarray, x: np.ndarray, z: np.ndarray) -> None:
        y = np.cross(z, x)
        matrix = np.eye(4)
        matrix[:3, 0], matrix[:3, 1], matrix[:3, 2], matrix[:3, 3] = x, y, z, origin
        self.api.geometry.edit_object_placement(self.f, product=product, matrix=matrix, is_si=False)

    # ── profiles ─────────────────────────────────────────────────────
    def profile(self, element: Any) -> tuple[Any, str]:
        """The IFC profile of a frame member and the name of its section."""
        f = self.f
        if isinstance(element, (TrussElement, CorotTrussElement)):
            radius = math.sqrt(max(float(element.area), 1e-30) / math.pi)
            return f.createIfcCircleProfileDef("AREA", f"A={element.area:g}", None, radius), (
                f"Truss A={element.area:g}"
            )
        section = self.sections.get(getattr(element, "section_id", -1))
        name = (
            section.name if section is not None else ""
        ) or f"Section {getattr(element, 'section_id', '')}"
        shape = getattr(section, "shape", None)
        if isinstance(shape, PipeShape):
            if shape.t * 2 >= shape.od:
                return f.createIfcCircleProfileDef("AREA", name, None, shape.od / 2), name
            return f.createIfcCircleHollowProfileDef(
                "AREA", name, None, shape.od / 2, shape.t
            ), name
        if isinstance(shape, RectShape):
            return f.createIfcRectangleProfileDef("AREA", name, None, shape.b, shape.d), name
        if isinstance(shape, AngleShape):
            return f.createIfcLShapeProfileDef("AREA", name, None, shape.d, shape.b, shape.t), name
        if isinstance(shape, WideFlangeShape):
            return f.createIfcIShapeProfileDef(
                "AREA", name, None, shape.bf, shape.d, shape.tw, shape.tf
            ), name
        if isinstance(shape, ChannelShape):
            return f.createIfcUShapeProfileDef(
                "AREA", name, None, shape.d, shape.bf, shape.tw, shape.tf
            ), name
        if isinstance(shape, TeeShape):
            return f.createIfcTShapeProfileDef(
                "AREA", name, None, shape.d, shape.bf, shape.tw, shape.tf
            ), name
        if isinstance(shape, TubeShape):
            return f.createIfcRectangleHollowProfileDef(
                "AREA", name, None, shape.b, shape.d, shape.t
            ), name
        library = self._aisc_profile(name)
        if library is not None:
            return library, name
        extents = section_extents(self.project, section.id) if section is not None else None
        if extents is None:
            return f.createIfcRectangleProfileDef("AREA", name, None, 0.1, 0.1), name
        width = max(extents.z_max - extents.z_min, 1e-9)
        depth = max(extents.y_max - extents.y_min, 1e-9)
        if self.project.ndm == 3:
            width, depth = depth, width
        return f.createIfcRectangleProfileDef("AREA", name, None, width, depth), name

    def _aisc_profile(self, name: str) -> Any:
        """An I or channel profile when ``name`` is an AISC shape, in model units."""
        if not name:
            return None
        try:
            from opensees_studio.core.aisc import get_shape

            shape = get_shape(name.strip().upper())
        except (KeyError, ValueError, ImportError):
            return None
        k = length_scale(UnitSystem.US_IN_KIP, self.project.meta.units)
        family = getattr(shape, "family", "")
        d, bf, tf, tw = (getattr(shape, a, None) for a in ("d", "bf", "tf", "tw"))
        if not (d and bf and tf and tw):
            return None
        if family in {"W", "M", "S", "HP"}:
            return self.f.createIfcIShapeProfileDef(
                "AREA", name, None, bf * k, d * k, tw * k, tf * k
            )
        if family in {"C", "MC"}:
            return self.f.createIfcUShapeProfileDef(
                "AREA", name, None, d * k, bf * k, tw * k, tf * k
            )
        return None

    # ── physical model ───────────────────────────────────────────────
    def physical(self) -> dict[int, Any]:
        out: dict[int, Any] = {}
        profile_sets: dict[str, Any] = {}
        materials: dict[str, Any] = {}
        for element in self.project.elements:
            if isinstance(element, ShellMITC4Element):
                product = self._shell(element, materials)
            elif isinstance(element, (*FRAME_ELEMENT_CLASSES, TrussElement, CorotTrussElement)):
                product = self._member(element, profile_sets)
            else:
                continue
            if product is not None:
                out[element.id] = product
        return out

    def _member(self, element: Any, profile_sets: dict[str, Any]) -> Any:
        api, f = self.api, self.f
        pi, pj = self.coords[element.nodes[0]], self.coords[element.nodes[1]]
        axis = pj - pi
        length = float(np.linalg.norm(axis))
        if length <= 0.0:
            return None
        axes = frame_local_axes(self.project.ndm, pi.tolist(), pj.tolist())
        if axes is None:
            return None
        x_local, y_local, z_local = axes
        tilt = math.degrees(math.asin(min(1.0, abs(float(axis[2]) / length))))
        truss = isinstance(element, (TrussElement, CorotTrussElement))
        if truss:
            ifc_class = "IfcMember"
        elif tilt >= 90.0 - VERTICAL_TOLERANCE_DEG:
            ifc_class = "IfcColumn"
        elif tilt <= VERTICAL_TOLERANCE_DEG:
            ifc_class = "IfcBeam"
        else:
            ifc_class = "IfcMember"
        product = api.root.create_entity(
            f, ifc_class=ifc_class, name=element.name or f"{ifc_class[3:]} {element.id}"
        )
        product.Tag = str(element.id)
        profile, section_name = self.profile(element)
        representation = api.geometry.add_profile_representation(
            f, context=self.body, profile=profile, depth=length * self.si
        )
        api.geometry.assign_representation(f, product=product, representation=representation)
        # Profile x = width, profile y = depth: local z in 3D, local y in 2D (core.frame_members).
        profile_x = y_local if self.project.ndm == 3 else -z_local
        self.placement(product, pi, profile_x, x_local)
        if section_name not in profile_sets:
            material = api.material.add_material(f, name=section_name, category="steel")
            profile_set = api.material.add_material_set(
                f, name=section_name, set_type="IfcMaterialProfileSet"
            )
            api.material.add_profile(f, profile_set=profile_set, material=material, profile=profile)
            profile_sets[section_name] = profile_set
        api.material.assign_material(
            f, products=[product], type="IfcMaterialProfileSet", material=profile_sets[section_name]
        )
        api.spatial.assign_container(
            f, products=[product], relating_structure=self.storey_for(float(min(pi[2], pj[2])))
        )
        return product

    def _shell(self, element: Any, materials: dict[str, Any]) -> Any:
        api, f = self.api, self.f
        points = np.array([self.coords[n] for n in element.nodes])
        normal = np.cross(points[2] - points[0], points[3] - points[1])
        if float(np.linalg.norm(normal)) <= 0.0:
            return None
        normal = normal / float(np.linalg.norm(normal))
        section = self.sections.get(element.section_id)
        thickness = float(section.h) if isinstance(section, SHELL_SECTION_CLASSES) else 0.1
        tilt = math.degrees(math.acos(min(1.0, abs(float(normal[2])))))
        ifc_class = (
            "IfcSlab"
            if tilt <= VERTICAL_TOLERANCE_DEG
            else "IfcWall"
            if tilt >= 90.0 - VERTICAL_TOLERANCE_DEG
            else "IfcPlate"
        )
        product = api.root.create_entity(
            f, ifc_class=ifc_class, name=element.name or f"{ifc_class[3:]} {element.id}"
        )
        product.Tag = str(element.id)
        origin = points.mean(axis=0) - normal * thickness / 2.0
        x = points[1] - points[0]
        x = x / float(np.linalg.norm(x))
        y = np.cross(normal, x)
        local = [((p - origin) @ x, (p - origin) @ y) for p in points]
        profile = f.createIfcArbitraryClosedProfileDef(
            "AREA",
            None,
            f.createIfcPolyline(
                [f.createIfcCartesianPoint([float(u), float(v)]) for u, v in [*local, local[0]]]
            ),
        )
        representation = api.geometry.add_profile_representation(
            f, context=self.body, profile=profile, depth=thickness * self.si
        )
        api.geometry.assign_representation(f, product=product, representation=representation)
        self.placement(product, origin, x, normal)
        name = (section.name if section is not None else "") or f"Section {element.section_id}"
        if name not in materials:
            materials[name] = api.material.add_material(f, name=name, category="concrete")
        api.material.assign_material(f, products=[product], material=materials[name])
        api.spatial.assign_container(
            f, products=[product], relating_structure=self.storey_for(float(points[:, 2].min()))
        )
        return product

    # ── analytical model ─────────────────────────────────────────────
    def analytical(self, physical: dict[int, Any]) -> None:
        api, f = self.api, self.f
        model = api.structural.add_structural_analysis_model(f)
        model.Name = "OpenSees Studio analysis model"
        model.PredefinedType = "IN_PLANE_LOADING_2D" if self.project.ndm == 2 else "LOADING_3D"
        if self.project.ndm == 2:
            model.OrientationOf2DPlane = f.createIfcAxis2Placement3D(
                self.point((0, 0, 0)), self.direction((0, -1, 0)), self.direction((1, 0, 0))
            )
        f.createIfcRelServicesBuildings(
            self.ios.guid.new(), None, None, None, model, [self.building]
        )
        self.vertices: dict[int, Any] = {}
        self.connections: dict[int, Any] = {}
        products: list[Any] = []
        slots = dof_indices(self.project.ndm, self.project.ndf)
        connected = {
            nid
            for e in self.project.elements
            if isinstance(
                e, (*FRAME_ELEMENT_CLASSES, TrussElement, CorotTrussElement, ShellMITC4Element)
            )
            for nid in e.nodes
        }
        orphans = [n.id for n in self.project.nodes if n.id not in connected]
        if orphans:
            shown = ", ".join(str(n) for n in orphans[:10]) + (" …" if len(orphans) > 10 else "")
            self.notes.append(
                f"{len(orphans)} node(s) on no frame, truss or shell (a diaphragm's retained "
                f"node, or only on the elements below) are not in the analytical model, nor "
                f"their loads: {shown}."
            )
        skipped: dict[str, int] = {}
        for e in self.project.elements:
            if not isinstance(
                e, (*FRAME_ELEMENT_CLASSES, TrussElement, CorotTrussElement, ShellMITC4Element)
            ):
                skipped[e.type] = skipped.get(e.type, 0) + 1
        if skipped:
            self.notes.append(
                "Elements IFC has no member for are left out: "
                + ", ".join(f"{n} {t}" for t, n in sorted(skipped.items()))
                + "."
            )
        for node in self.project.nodes:
            if node.id not in connected:
                continue
            vertex = f.createIfcVertexPoint(self.point(node.coords))
            self.vertices[node.id] = vertex
            connection = api.root.create_entity(
                f, ifc_class="IfcStructuralPointConnection", name=f"N{node.id}"
            )
            connection.Representation = f.createIfcProductDefinitionShape(
                None,
                None,
                [api.geometry.add_topology_representation(f, context=self.reference, item=vertex)],
            )
            if any(node.restraint[i] or node.spring[i] > 0 for i in slots):
                connection.AppliedCondition = f.createIfcBoundaryNodeCondition(
                    f"Support N{node.id}",
                    *(self._support_value(node, i, i in slots) for i in range(6)),
                )
            self.connections[node.id] = connection
            products.append(connection)
        self.members: dict[int, Any] = {}
        for element in self.project.elements:
            member = self._analytical_member(element)
            if member is None:
                continue
            self.members[element.id] = member
            products.append(member)
            if element.id in physical:
                api.structural.assign_product(
                    f, relating_product=physical[element.id], related_object=member
                )
        api.structural.assign_structural_analysis_model(
            f, products=products, structural_analysis_model=model
        )
        self.model = model
        self._loads(model)

    def _analytical_member(self, element: Any) -> Any:
        api, f = self.api, self.f
        if isinstance(element, ShellMITC4Element):
            section = self.sections.get(element.section_id)
            member = api.root.create_entity(
                f, ifc_class="IfcStructuralSurfaceMember", name=f"E{element.id}"
            )
            member.PredefinedType = "SHELL"
            if isinstance(section, SHELL_SECTION_CLASSES):
                member.Thickness = float(section.h)
            edges = [
                f.createIfcOrientedEdge(
                    None,
                    None,
                    f.createIfcEdge(self.vertices[a], self.vertices[b]),
                    True,
                )
                for a, b in zip(element.nodes, (*element.nodes[1:], element.nodes[0]), strict=True)
            ]
            points = np.array([self.coords[n] for n in element.nodes])
            normal = np.cross(points[2] - points[0], points[3] - points[1])
            normal = normal / float(np.linalg.norm(normal))
            ref = points[1] - points[0]
            plane = f.createIfcPlane(
                f.createIfcAxis2Placement3D(
                    self.point(points[0]),
                    self.direction(normal),
                    self.direction(ref / np.linalg.norm(ref)),
                )
            )
            face = f.createIfcFaceSurface(
                [f.createIfcFaceOuterBound(f.createIfcEdgeLoop(edges), True)], plane, True
            )
            member.Representation = f.createIfcProductDefinitionShape(
                None,
                None,
                [api.geometry.add_topology_representation(f, context=self.reference, item=face)],
            )
            for nid in element.nodes:
                api.structural.add_structural_member_connection(
                    f,
                    relating_structural_member=member,
                    related_structural_connection=self.connections[nid],
                )
            return member
        if not isinstance(element, (*FRAME_ELEMENT_CLASSES, TrussElement, CorotTrussElement)):
            return None
        pi, pj = self.coords[element.nodes[0]], self.coords[element.nodes[1]]
        axes = frame_local_axes(self.project.ndm, pi.tolist(), pj.tolist())
        if axes is None:
            return None
        truss = isinstance(element, (TrussElement, CorotTrussElement))
        member = api.root.create_entity(
            f, ifc_class="IfcStructuralCurveMember", name=f"E{element.id}"
        )
        member.PredefinedType = "PIN_JOINED_MEMBER" if truss else "RIGID_JOINED_MEMBER"
        member.Axis = self.direction(axes[2])  # IFC local z; local y = z x x is ours
        edge = f.createIfcEdge(self.vertices[element.nodes[0]], self.vertices[element.nodes[1]])
        member.Representation = f.createIfcProductDefinitionShape(
            None,
            None,
            [api.geometry.add_topology_representation(f, context=self.reference, item=edge)],
        )
        releases = getattr(element, "releases", None)
        for end, nid in zip(("i", "j"), element.nodes, strict=True):
            rel = api.structural.add_structural_member_connection(
                f,
                relating_structural_member=member,
                related_structural_connection=self.connections[nid],
            )
            release = releases.end(end) if releases is not None else None
            if release is not None and release.released:
                free = set(release.released)
                rel.AppliedCondition = f.createIfcBoundaryNodeCondition(
                    f"Release {end}",
                    *(f.createIfcBoolean(True) for _ in range(3)),
                    f.createIfcBoolean("T" not in free),
                    f.createIfcBoolean("M2" not in free),
                    f.createIfcBoolean("M3" not in free),
                )
        return member

    # ── loads ────────────────────────────────────────────────────────
    def _loads(self, model: Any) -> None:
        f = self.f
        cases: dict[int, Any] = {}
        groups: list[Any] = []
        for pattern in self.project.load_patterns:
            if not isinstance(pattern, PlainLoadPattern):
                continue
            role = guess_load_role(pattern.name or "")
            action_type, action_source = _ACTION.get(role or "", ("NOTDEFINED", "NOTDEFINED"))
            case = self.api.structural.add_structural_load_case(
                f,
                name=pattern.name or f"Pattern {pattern.id}",
                action_type=action_type,
                action_source=action_source,
            )
            if pattern.self_weight:
                case.SelfWeightCoefficients = [0.0, 0.0, -float(pattern.self_weight)]
            actions = self._pattern_actions(pattern)
            if actions:
                f.createIfcRelAssignsToGroup(
                    self.ios.guid.new(), None, None, None, actions, None, case
                )
            cases[pattern.id] = case
            groups.append(case)
        analyses = {a.id: a for a in self.project.analyses}
        for combo in self.project.combinations:
            group = self.api.structural.add_structural_load_group(
                f, name=combo.name or f"Combination {combo.id}"
            )
            group.PredefinedType = "LOAD_COMBINATION"
            group.Description = combo.combination_type
            for term in combo.terms:
                if term.source != "case":
                    continue
                case = analyses.get(term.ref_id)
                for pid in getattr(case, "pattern_ids", []) or []:
                    if pid in cases:
                        f.createIfcRelAssignsToGroupByFactor(
                            self.ios.guid.new(),
                            None,
                            None,
                            None,
                            [cases[pid]],
                            None,
                            group,
                            float(term.factor),
                        )
            groups.append(group)
        if groups:
            model.LoadedBy = groups

    def _pattern_actions(self, pattern: PlainLoadPattern) -> list[Any]:
        api, f = self.api, self.f
        actions: list[Any] = []
        lengths = {
            e.id: float(np.linalg.norm(self.coords[e.nodes[1]] - self.coords[e.nodes[0]]))
            for e in self.project.elements
            if len(e.nodes) == 2
        }
        for k, nodal in enumerate(pattern.nodal_loads):
            if nodal.node_id not in self.connections:
                continue
            load = f.createIfcStructuralLoadSingleForce(f"F{k + 1}", *map(float, nodal.forces))
            actions.append(
                api.structural.add_structural_activity(
                    f,
                    applied_load=load,
                    structural_member=self.connections[nodal.node_id],
                    ifc_class="IfcStructuralPointAction",
                    predefined_type=None,
                )
            )
        for k, imposed in enumerate(pattern.imposed_displacements):
            if imposed.node_id not in self.connections:
                continue
            values = [0.0] * 6
            slot = dof_indices(self.project.ndm, self.project.ndf)[imposed.dof - 1]
            values[slot] = float(imposed.value)
            load = f.createIfcStructuralLoadSingleDisplacement(f"D{k + 1}", *values)
            actions.append(
                api.structural.add_structural_activity(
                    f,
                    applied_load=load,
                    structural_member=self.connections[imposed.node_id],
                    ifc_class="IfcStructuralPointAction",
                    predefined_type=None,
                )
            )
        uniform = [
            (u.element_id, 0.0, 1.0, (u.wx, u.wy, u.wz), (u.wx, u.wy, u.wz))
            for u in pattern.element_loads
        ]
        trapezoidal = [
            (d.element_id, d.x_start, d.x_end, d.start(), d.end())
            for d in pattern_distributed_loads(self.project, pattern)
        ]
        for eid, x0, x1, w0, w1 in uniform + trapezoidal:
            member = self.members.get(eid)
            if member is None:
                continue
            length = lengths.get(eid, 1.0)
            if x0 == 0.0 and x1 == 1.0 and tuple(w0) == tuple(w1):
                load = f.createIfcStructuralLoadLinearForce(None, *map(float, w0), 0.0, 0.0, 0.0)
                kind = "CONST"
            else:
                load = f.createIfcStructuralLoadConfiguration(
                    None,
                    [
                        f.createIfcStructuralLoadLinearForce(None, *map(float, w0), 0.0, 0.0, 0.0),
                        f.createIfcStructuralLoadLinearForce(None, *map(float, w1), 0.0, 0.0, 0.0),
                    ],
                    [[float(x0 * length)], [float(x1 * length)]],
                )
                kind = "LINEAR"
            action = api.structural.add_structural_activity(
                f,
                applied_load=load,
                structural_member=member,
                ifc_class="IfcStructuralCurveAction",
                predefined_type=kind,
                global_or_local="LOCAL_COORDS",
            )
            action.ProjectedOrTrue = "TRUE_LENGTH"
            actions.append(action)
        for point in pattern.point_loads:
            member = self.members.get(point.element_id)
            if member is None:
                continue
            load = f.createIfcStructuralLoadSingleForce(
                None, float(point.px), float(point.py), float(point.pz), 0.0, 0.0, 0.0
            )
            action = api.structural.add_structural_activity(
                f,
                applied_load=load,
                structural_member=member,
                ifc_class="IfcStructuralPointAction",
                predefined_type=None,
                global_or_local="LOCAL_COORDS",
            )
            element = next(e for e in self.project.elements if e.id == point.element_id)
            pi, pj = self.coords[element.nodes[0]], self.coords[element.nodes[1]]
            at = pi + float(point.x) * (pj - pi)
            action.Representation = f.createIfcProductDefinitionShape(
                None,
                None,
                [
                    api.geometry.add_topology_representation(
                        f, context=self.reference, item=f.createIfcVertexPoint(self.point(at))
                    )
                ],
            )
            actions.append(action)
        for surface in pattern.surface_loads:
            member = self.members.get(surface.element_id)
            if member is None:
                continue
            vector = [0.0, 0.0, 0.0]
            local = surface.direction == "normal"
            vector["XYZ".index(surface.direction) if not local else 2] = float(surface.value)
            load = f.createIfcStructuralLoadPlanarForce(None, *vector)
            actions.append(
                api.structural.add_structural_activity(
                    f,
                    applied_load=load,
                    structural_member=member,
                    ifc_class="IfcStructuralPlanarAction",
                    predefined_type="CONST",
                    global_or_local="LOCAL_COORDS" if local else "GLOBAL_COORDS",
                )
            )
        return actions


@dataclass
class IfcExportReport:
    """Where the file went, what it holds, and what was left out."""

    path: Path
    physical: int
    analytical: int
    load_cases: int
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        text = (
            f"IFC4 written to {self.path}: {self.physical} physical element(s), "
            f"{self.analytical} analytical member(s), {self.load_cases} load case(s)."
        )
        return " ".join([text, *self.notes])


def export_ifc(project: Project, path: str | Path) -> IfcExportReport:
    """Write ``project`` as an IFC4 file at ``path`` (physical and analytical models)."""
    target = Path(path)
    writer = _Writer(project)
    writer.header(target.stem)
    physical = writer.physical()
    writer.analytical(physical)
    target.parent.mkdir(parents=True, exist_ok=True)
    writer.f.write(str(target))
    return IfcExportReport(
        path=target,
        physical=len(physical),
        analytical=len(writer.members),
        load_cases=len(writer.f.by_type("IfcStructuralLoadCase")),
        notes=writer.notes,
    )
