"""Import an IFC file as a new project: the structural analysis model, or the physical one.

An IFC file can describe a structure twice, and the two descriptions are not the
same thing:

- **Analytical** (``IfcStructuralAnalysisModel``): point connections with their
  supports, curve and surface members on the members' axes and mid-surfaces,
  member end releases, and load cases with point, line and planar actions. It is
  what Tekla, Revit's analytical model, SAP2000, ETABS and this application's own
  File → Export → IFC write, and it maps onto a model almost one to one.
- **Physical** (``IfcColumn``, ``IfcBeam``, ``IfcMember``, ``IfcSlab``,
  ``IfcWall``, ``IfcPlate``): solids an architect or a detailer drew. Members
  meet at faces, not at axes, so the axes have to be *joined*: an end that stops
  at a column face is moved onto the column's axis, a member is split where
  another one lands on it, and slab and wall corners are attached to the nearest
  node. Nothing carries supports or loads.

``source="auto"`` (the default) takes the analytical model when the file has one
and the physical model otherwise.

Sections. A profile whose name is an AISC v16 shape (``W14X90``, ``HSS6X6X1/4``)
takes the library's properties; otherwise A, I and J come from the profile's own
dimensions (I, channel, angle, tee, rectangle, round and rectangular hollow,
or any closed polygon), from ``Pset_ProfileMechanical`` when the file gives it,
and only failing all of that from a placeholder that is reported. A file this
application wrote carries its exact section and material values in the
``OpenSeesStudio_Section`` property set, so it comes back as it went out.

Materials. ``Pset_MaterialMechanical`` (E, G, ν), ``Pset_MaterialCommon``
(density, for self weight), ``Pset_MaterialSteel`` (yield stress) and
``Pset_MaterialConcrete`` (compressive strength) are read with their units; a
material that says nothing gets the defaults of its kind (steel or concrete, from
its category or name), which is reported. Steel with a yield stress becomes a
``Steel01`` and concrete with a strength a ``Concrete01`` in Define → Materials,
so they are there for fibre sections; the elastic members use E and G directly.

Units come from the file's ``IfcUnitAssignment`` and are converted to the
nearest of the application's systems (millimetres to SI mm-N, metres to SI m-N,
feet and inches to the US systems). A derived unit the file does not declare is
derived from its length and force units, never assumed to be SI.

This module imports ``ifcopenshell`` (a GUI dependency) when it runs. No Qt.
"""

from __future__ import annotations

import itertools
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast, get_args

import numpy as np
from pydantic import ValidationError

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    PointElementLoad,
    Project,
    ShellMITC4Element,
    StaticCase,
    SurfaceLoad,
    TrapezoidalElementLoad,
    TrussElement,
    UniformElementLoad,
)
from opensees_studio.core.combinations import (
    CombinationTerm,
    CombinationType,
    LoadCombination,
)
from opensees_studio.core.geometry import default_global_system
from opensees_studio.core.geometry.frame_options import EndRelease, FrameReleases
from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.loads import ImposedDisplacement
from opensees_studio.core.materials import Concrete01, ElasticUniaxial, Steel01
from opensees_studio.core.plane import dof_indices
from opensees_studio.core.project import ProjectMeta
from opensees_studio.core.section_outline import hint_regions
from opensees_studio.core.sections import (
    AngleShape,
    ChannelShape,
    PipeShape,
    RectShape,
    SectionShape,
    TeeShape,
    TubeShape,
    WideFlangeShape,
)
from opensees_studio.core.sections.geometry import PolygonRegion, section_properties
from opensees_studio.core.storeys import Storey
from opensees_studio.core.units import UnitSystem, metres_per_unit, newtons_per_unit
from opensees_studio.services.ifc_export import (
    STUDIO_FRAME_PSET,
    STUDIO_MEMBER_PSET,
    STUDIO_PSET,
)

Source = Literal["auto", "analytical", "physical"]
Vec = np.ndarray


#: Standard gravity, m/s² — turns a mass density into a unit weight.
G_SI = 9.80665

#: Defaults for a material the file says nothing about, SI (Pa, kg/m³).
STEEL_DEFAULTS = {"E": 200e9, "nu": 0.3, "density": 7850.0, "fy": 345e6}
CONCRETE_DEFAULTS = {"E": 24.9e9, "nu": 0.2, "density": 2400.0, "fc": 28e6}

#: A frame within this angle of vertical is a column (column bases, orientation).
VERTICAL_TOLERANCE_DEG = 10.0

#: Coincidence tolerance relative to the model's size, as in the DXF import.
RELATIVE_TOLERANCE = 1e-6

#: How far beyond a member's half depth an end may stop and still be joined to
#: it: a detailer's clearance at a column face, or a fin plate's gap.
JOIN_MARGIN = 1.25

#: Strings that make an unnamed material concrete rather than steel.
_CONCRETE_WORDS = (
    "concrete",
    "concreto",
    "hormig",
    "beton",
    "béton",
    "c20",
    "c25",
    "c30",
    "c35",
    "c40",
    "fc",
)
_STEEL_WORDS = (
    "steel",
    "acero",
    "stahl",
    "s235",
    "s275",
    "s355",
    "a36",
    "a992",
    "a572",
    "a500",
    "fy",
)

#: What a combination group's Description may say, as the combination type it is.
_COMBINATION_KIND: dict[str, CombinationType] = {kind: kind for kind in get_args(CombinationType)}

#: A global surface-load direction by component.
_GLOBAL_AXES: tuple[Literal["X", "Y", "Z"], ...] = ("X", "Y", "Z")

#: (length exponent, force exponent) of each unit type the reader converts.
_DIMENSIONS: dict[str, tuple[int, int]] = {
    "LENGTHUNIT": (1, 0),
    "AREAUNIT": (2, 0),
    "FORCEUNIT": (0, 1),
    "LINEARFORCEUNIT": (-1, 1),
    "PLANARFORCEUNIT": (-2, 1),
    "PRESSUREUNIT": (-2, 1),
    "MODULUSOFELASTICITYUNIT": (-2, 1),
    "TORQUEUNIT": (1, 1),
    "MOMENTOFINERTIAUNIT": (4, 0),
    "LINEARSTIFFNESSUNIT": (-1, 1),
    "ROTATIONALSTIFFNESSUNIT": (1, 1),
}


class IfcImportError(RuntimeError):
    """The file cannot be read, or holds nothing this application can model."""


def _ifc() -> Any:
    try:
        import ifcopenshell
        import ifcopenshell.util.element
        import ifcopenshell.util.placement
        import ifcopenshell.util.unit
    except ImportError as exc:  # pragma: no cover - the GUI install has it
        raise IfcImportError(
            "IFC import needs ifcopenshell: pip install ifcopenshell (it comes with the "
            "desktop install)."
        ) from exc
    return ifcopenshell


# ──────────────────────────── what a file holds ────────────────────────────
@dataclass
class IfcInventory:
    """What is in a file, before anything is imported — what the dialog shows."""

    path: Path
    schema: str
    length_unit: str
    force_unit: str
    suggested_units: UnitSystem
    analytical_members: int = 0
    analytical_surfaces: int = 0
    point_connections: int = 0
    supports: int = 0
    physical: dict[str, int] = field(default_factory=dict)
    load_cases: int = 0
    combinations: int = 0
    storeys: int = 0

    @property
    def has_analytical(self) -> bool:
        return self.analytical_members + self.analytical_surfaces > 0

    @property
    def physical_frames(self) -> int:
        return sum(self.physical.get(c, 0) for c in ("IfcColumn", "IfcBeam", "IfcMember"))

    @property
    def physical_shells(self) -> int:
        return sum(
            self.physical.get(c, 0)
            for c in ("IfcSlab", "IfcWall", "IfcWallStandardCase", "IfcPlate")
        )

    def default_source(self) -> Literal["analytical", "physical"]:
        return "analytical" if self.has_analytical else "physical"

    def summary(self) -> str:
        parts = [f"{self.schema}, lengths in {self.length_unit}, forces in {self.force_unit}."]
        if self.has_analytical:
            parts.append(
                f"Analytical model: {self.point_connections} point connection(s) "
                f"({self.supports} support(s)), {self.analytical_members} curve member(s), "
                f"{self.analytical_surfaces} surface member(s), {self.load_cases} load case(s), "
                f"{self.combinations} combination(s)."
            )
        else:
            parts.append("No analytical model.")
        physical = ", ".join(f"{n} {c[3:]}" for c, n in sorted(self.physical.items()) if n)
        parts.append(f"Physical model: {physical or 'none'}.")
        if self.storeys:
            parts.append(f"{self.storeys} storey(s).")
        return " ".join(parts)


@dataclass
class IfcImportOptions:
    """What to take from the file, and how."""

    source: Source = "auto"
    units: UnitSystem | None = None
    """The project's unit system; ``None`` picks the one nearest the file's."""
    include_shells: bool = True
    include_loads: bool = True
    fix_column_bases: bool = True
    """Physical model only: restrain the bottom of every column at the lowest level."""


@dataclass
class IfcImport:
    """The project an import produced, and what it could not carry."""

    project: Project
    source: Literal["analytical", "physical"]
    inventory: IfcInventory
    notes: list[str] = field(default_factory=list)
    dropped: Counter[str] = field(default_factory=Counter)

    def summary(self) -> str:
        project = self.project
        shells = sum(isinstance(e, ShellMITC4Element) for e in project.elements)
        text = (
            f"From the {self.source} model: {len(project.nodes)} node(s), "
            f"{len(project.elements) - shells} frame/truss member(s), {shells} shell(s), "
            f"{len(project.sections)} section(s), {len(project.materials)} material(s), "
            f"{len(project.load_patterns)} load pattern(s), "
            f"{len(project.combinations)} combination(s)."
        )
        if self.dropped:
            items = ", ".join(f"{count} {what}" for what, count in sorted(self.dropped.items()))
            text += f" Not imported: {items}."
        return text


# ──────────────────────────── units ────────────────────────────
class _Units:
    """Every value the reader takes from the file goes through here."""

    def __init__(self, f: Any, target: UnitSystem | None) -> None:
        util = _ifc().util.unit
        self._util = util
        self.f = f
        self.length_si = self._declared("LENGTHUNIT") or 1.0
        self.force_si = self._declared("FORCEUNIT") or 1.0
        self.length_name = self._name("LENGTHUNIT", "metre")
        self.force_name = self._name("FORCEUNIT", "newton")
        self.target = target or self.suggest()
        self.m_per_unit = metres_per_unit(self.target)
        self.n_per_unit = newtons_per_unit(self.target)

    def _unit(self, unit_type: str) -> Any:
        try:
            return self._util.get_project_unit(self.f, unit_type)
        except Exception:
            return None

    def _declared(self, unit_type: str) -> float | None:
        unit = self._unit(unit_type)
        if unit is None:
            return None
        try:
            return float(self._util.get_unit_scale(unit))
        except Exception:
            return None

    def _name(self, unit_type: str, default: str) -> str:
        unit = self._unit(unit_type)
        if unit is None:
            return f"{default} (not declared)"
        try:
            return str(self._util.get_full_unit_name(unit)).lower()
        except Exception:
            return str(getattr(unit, "Name", default)).lower()

    def suggest(self) -> UnitSystem:
        metres = self.length_si
        if math.isclose(metres, 0.001, rel_tol=1e-6):
            return UnitSystem.SI_MM_N
        if math.isclose(metres, 0.3048, rel_tol=1e-6):
            return UnitSystem.US_FT_KIP
        if math.isclose(metres, 0.0254, rel_tol=1e-6):
            return UnitSystem.US_IN_KIP
        return UnitSystem.SI_M_N

    def si(self, unit_type: str) -> float:
        """SI value of one file unit of ``unit_type`` (derived when undeclared).

        A modulus of elasticity without its own unit is read in the file's
        pressure unit when it declares one: that is what exporters mean by "MPa".
        """
        declared = self._declared(unit_type)
        if declared is not None:
            return declared
        if unit_type == "MODULUSOFELASTICITYUNIT":
            pressure = self._declared("PRESSUREUNIT")
            if pressure is not None:
                return pressure
        length, force = _DIMENSIONS[unit_type]
        return self.length_si**length * self.force_si**force

    def factor(self, unit_type: str) -> float:
        """File value of ``unit_type`` → project units.

        A factor within rounding of 1 is exactly 1: a file in kip writes the kip
        as 4448.2216153 N, and a kip-to-kip import must not move the eleventh digit.
        """
        length, force = _DIMENSIONS[unit_type]
        value = self.si(unit_type) / (self.m_per_unit**length * self.n_per_unit**force)
        return 1.0 if abs(value - 1.0) < 1e-9 else value

    @property
    def length(self) -> float:
        return self.factor("LENGTHUNIT")

    def from_si(self, value: float, length: int, force: int) -> float:
        """An SI value (m, N) → project units."""
        return value / (self.m_per_unit**length * self.n_per_unit**force)

    def mass_density_si(self) -> float:
        """kg/m³ in one file unit of mass density.

        Without a declared density unit the value is taken as kg/m³ whatever the
        length unit: a file in millimetres writes steel as 7850, not 7.85e-6.
        """
        declared = self._declared("MASSDENSITYUNIT")
        return declared if declared is not None else 1.0


def _value(item: Any) -> Any:
    """The Python value of an attribute that may be a wrapped IFC select."""
    if item is None:
        return None
    if hasattr(item, "wrappedValue"):
        return item.wrappedValue
    return item


def _float(item: Any, default: float = 0.0) -> float:
    value = _value(item)
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


# ──────────────────────────── geometry helpers ────────────────────────────
def _point(entity: Any) -> Vec:
    coords = list(entity.Coordinates) + [0.0] * (3 - len(entity.Coordinates))
    return np.array(coords[:3], dtype=float)


def _direction(entity: Any | None, default: Sequence[float]) -> Vec:
    if entity is None:
        return np.array(default, dtype=float)
    ratios = list(entity.DirectionRatios) + [0.0] * (3 - len(entity.DirectionRatios))
    vec = np.array(ratios[:3], dtype=float)
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0 else np.array(default, dtype=float)


def _axis2_matrix(position: Any | None) -> np.ndarray:
    """4x4 of an ``IfcAxis2Placement3D``/``2D`` (identity when absent)."""
    matrix = np.eye(4)
    if position is None:
        return matrix
    matrix[:3, 3] = _point(position.Location)
    if position.is_a("IfcAxis2Placement2D"):
        x = _direction(getattr(position, "RefDirection", None), (1, 0, 0))
        matrix[:3, 0] = x
        matrix[:3, 1] = np.cross((0, 0, 1), x)
        return matrix
    z = _direction(getattr(position, "Axis", None), (0, 0, 1))
    ref = _direction(getattr(position, "RefDirection", None), (1, 0, 0))
    x = ref - (ref @ z) * z
    if float(np.linalg.norm(x)) < 1e-9:
        x = np.array([1.0, 0.0, 0.0]) if abs(z[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        x = x - (x @ z) * z
    x /= float(np.linalg.norm(x))
    matrix[:3, 0], matrix[:3, 1], matrix[:3, 2] = x, np.cross(z, x), z
    return matrix


def _apply(matrix: np.ndarray, point: Vec) -> Vec:
    return np.asarray(matrix[:3, :3] @ point + matrix[:3, 3], dtype=float)


class _Nodes:
    """Nodes by position: points within ``tolerance`` of each other are one node."""

    def __init__(self, tolerance: float) -> None:
        self.tolerance = max(tolerance, 1e-12)
        self.coords: dict[int, Vec] = {}
        self.restraint: dict[int, list[bool]] = {}
        self.spring: dict[int, list[float]] = {}
        self._cells: dict[tuple[int, int, int], list[int]] = defaultdict(list)
        self._next = 1

    def _key(self, p: Vec) -> tuple[int, int, int]:
        t = self.tolerance
        return (math.floor(p[0] / t), math.floor(p[1] / t), math.floor(p[2] / t))

    def find(self, p: Vec, radius: float | None = None) -> int | None:
        r = self.tolerance if radius is None else radius
        if r <= self.tolerance:
            cx, cy, cz = self._key(p)
            best, best_d = None, r
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for nid in self._cells.get((cx + dx, cy + dy, cz + dz), ()):
                            d = float(np.linalg.norm(self.coords[nid] - p))
                            if d <= best_d:
                                best, best_d = nid, d
            return best
        best, best_d = None, r
        for nid, q in self.coords.items():
            d = float(np.linalg.norm(q - p))
            if d <= best_d:
                best, best_d = nid, d
        return best

    def add(self, p: Vec, wanted_id: int | None = None) -> int:
        found = self.find(p)
        if found is not None:
            return found
        nid = wanted_id if wanted_id is not None and wanted_id not in self.coords else None
        if nid is None:
            while self._next in self.coords:
                self._next += 1
            nid = self._next
        self.coords[nid] = np.asarray(p, dtype=float)
        self.restraint[nid] = [False] * 6
        self.spring[nid] = [0.0] * 6
        self._cells[self._key(self.coords[nid])].append(nid)
        return nid


# ──────────────────────────── sections ────────────────────────────
def _aisc_candidates(names: Iterable[str | None]) -> list[str]:
    out: list[str] = []
    for raw in names:
        if not raw:
            continue
        for piece in (raw, raw.split(":")[-1]):
            text = piece.strip().upper().replace(" ", "").replace("×", "X")
            if text and text not in out:
                out.append(text)
    return out


def _aisc_shape(names: Iterable[str | None]) -> Any:
    from opensees_studio.core.aisc import get_shape

    for name in _aisc_candidates(names):
        try:
            return get_shape(name)
        except KeyError:
            continue
    return None


def _thin_wall_torsion(shape: SectionShape) -> float:
    """Saint-Venant torsion constant of a hint, thin-walled (closed-form)."""
    if isinstance(shape, PipeShape):
        ro, ri = shape.od / 2, max(shape.od / 2 - shape.t, 0.0)
        return math.pi / 2 * (ro**4 - ri**4)
    if isinstance(shape, RectShape):
        long, short = max(shape.d, shape.b), min(shape.d, shape.b)
        return long * short**3 * (1 / 3 - 0.21 * short / long * (1 - short**4 / (12 * long**4)))
    if isinstance(shape, TubeShape):
        dm, bm = shape.d - shape.t, shape.b - shape.t
        return 2 * shape.t * dm**2 * bm**2 / (dm + bm)
    if isinstance(shape, (WideFlangeShape, ChannelShape)):
        return (2 * shape.bf * shape.tf**3 + (shape.d - 2 * shape.tf) * shape.tw**3) / 3
    if isinstance(shape, TeeShape):
        return (shape.bf * shape.tf**3 + (shape.d - shape.tf) * shape.tw**3) / 3
    if isinstance(shape, AngleShape):
        return (shape.d + shape.b - shape.t) * shape.t**3 / 3
    return 0.0


def _profile_shape(profile: Any, scale: float) -> SectionShape | None:
    """A drawing hint (and the geometry to integrate) from a parameterised profile."""

    def get(name: str) -> float:
        return _float(getattr(profile, name, None)) * scale

    try:
        if profile.is_a("IfcIShapeProfileDef"):
            return WideFlangeShape(
                d=get("OverallDepth"),
                bf=get("OverallWidth"),
                tw=get("WebThickness"),
                tf=get("FlangeThickness"),
            )
        if profile.is_a("IfcUShapeProfileDef"):
            return ChannelShape(
                d=get("Depth"),
                bf=get("FlangeWidth"),
                tw=get("WebThickness"),
                tf=get("FlangeThickness"),
            )
        if profile.is_a("IfcTShapeProfileDef"):
            return TeeShape(
                d=get("Depth"),
                bf=get("FlangeWidth"),
                tw=get("WebThickness"),
                tf=get("FlangeThickness"),
            )
        if profile.is_a("IfcLShapeProfileDef"):
            width = get("Width") or get("Depth")
            return AngleShape(d=get("Depth"), b=width, t=get("Thickness"))
        if profile.is_a("IfcRectangleHollowProfileDef"):
            return TubeShape(d=get("YDim"), b=get("XDim"), t=get("WallThickness"))
        if profile.is_a("IfcRectangleProfileDef"):
            return RectShape(d=get("YDim"), b=get("XDim"))
        if profile.is_a("IfcCircleHollowProfileDef"):
            return PipeShape(od=2 * get("Radius"), t=get("WallThickness"))
        if profile.is_a("IfcCircleProfileDef"):
            return PipeShape(od=2 * get("Radius"), t=get("Radius"))
    except (ValidationError, TypeError):
        return None
    return None


def _polygon_points(curve: Any) -> list[tuple[float, float]] | None:
    """The 2D vertices of a closed polyline or indexed poly curve (closing point dropped)."""
    points: list[tuple[float, float]]
    if curve.is_a("IfcPolyline"):
        points = [(float(p.Coordinates[0]), float(p.Coordinates[1])) for p in curve.Points]
    elif curve.is_a("IfcIndexedPolyCurve"):
        if curve.Segments and any(s.is_a("IfcArcIndex") for s in curve.Segments):
            return None
        points = [(float(c[0]), float(c[1])) for c in curve.Points.CoordList]
    else:
        return None
    if len(points) > 1 and math.dist(points[0], points[-1]) < 1e-12:
        points = points[:-1]
    return points if len(points) >= 3 else None


@dataclass
class _Props:
    A: float
    I_strong: float
    """Second moment about the axis perpendicular to the depth (bending in the depth plane)."""
    I_weak: float
    J: float
    hint: SectionShape | None = None
    origin: str = ""
    depth: float = 0.0
    width: float = 0.0


def _props_from_profile(profile: Any, scale: float) -> _Props | None:
    """Section properties from an IFC profile's own geometry, in project units."""
    shape = _profile_shape(profile, scale)
    if shape is not None:
        regions = hint_regions(shape, 2)  # depth along local y: Iz is the strong axis
        props = section_properties(regions, plastic=False)
        y0, y1 = props.y_range
        z0, z1 = props.z_range
        return _Props(
            A=props.A,
            I_strong=props.Iz,
            I_weak=props.Iy,
            J=_thin_wall_torsion(shape),
            hint=shape,
            origin=f"dimensions of {profile.is_a()[3:]}",
            depth=y1 - y0,
            width=z1 - z0,
        )
    if profile.is_a("IfcArbitraryClosedProfileDef"):
        points = _polygon_points(profile.OuterCurve)
        if points is None:
            return None
        region = PolygonRegion(tuple((p[1] * scale, p[0] * scale) for p in points))
        props = section_properties([region], plastic=False)
        y0, y1 = props.y_range
        z0, z1 = props.z_range
        depth, width = y1 - y0, z1 - z0
        short, long = min(depth, width), max(depth, width)
        j = long * short**3 / 3 if long > 0 else 0.0
        return _Props(
            A=props.A,
            I_strong=props.Iz,
            I_weak=props.Iy,
            J=j,
            origin="polygon profile",
            depth=depth,
            width=width,
        )
    if profile.is_a("IfcDerivedProfileDef") and profile.ParentProfile is not None:
        return _props_from_profile(profile.ParentProfile, scale)
    return None


# ──────────────────────────── materials ────────────────────────────
@dataclass
class _Material:
    name: str
    kind: Literal["steel", "concrete"]
    E: float
    G: float
    nu: float
    unit_weight: float
    rho: float
    fy: float | None = None
    fc: float | None = None
    defaulted: bool = False
    studio: dict[str, float] = field(default_factory=dict)


def _kind_of(material: Any) -> tuple[Literal["steel", "concrete"], bool]:
    text = " ".join(
        str(getattr(material, a, "") or "") for a in ("Category", "Name", "Description")
    ).lower()
    if any(word in text for word in _CONCRETE_WORDS):
        return "concrete", True
    if any(word in text for word in _STEEL_WORDS):
        return "steel", True
    return "steel", False


# ──────────────────────────── the reader ────────────────────────────
class _Reader:
    def __init__(self, path: Path, options: IfcImportOptions) -> None:
        ios = _ifc()
        self.ios = ios
        try:
            self.f = ios.open(str(path))
        except Exception as exc:
            raise IfcImportError(f"{path.name} is not a readable IFC file: {exc}") from exc
        self.path = path
        self.options = options
        self.units = _Units(self.f, options.units)
        self.notes: list[str] = []
        self.dropped: Counter[str] = Counter()
        self._placements: dict[int, np.ndarray] = {}
        self.materials: dict[str, _Material] = {}
        self.sections: dict[tuple[Any, ...], tuple[int, float]] = {}
        self.section_list: list[Any] = []
        self.truss_materials: dict[str, int] = {}
        self.uniaxial: list[Any] = []

    # ── inventory ──
    def inventory(self) -> IfcInventory:
        f = self.f

        def count(cls: str) -> int:
            try:
                return len(f.by_type(cls, include_subtypes=False))
            except Exception:
                return 0

        physical = {
            c: count(c)
            for c in (
                "IfcColumn",
                "IfcBeam",
                "IfcMember",
                "IfcSlab",
                "IfcWall",
                "IfcWallStandardCase",
                "IfcPlate",
            )
        }
        connections = self._by_type("IfcStructuralPointConnection")
        groups = self._by_type("IfcStructuralLoadGroup")
        return IfcInventory(
            path=self.path,
            schema=str(f.schema),
            length_unit=self.units.length_name,
            force_unit=self.units.force_name,
            suggested_units=self.units.suggest(),
            analytical_members=len(self._by_type("IfcStructuralCurveMember")),
            analytical_surfaces=len(self._by_type("IfcStructuralSurfaceMember")),
            point_connections=len(connections),
            supports=sum(1 for c in connections if self._has_support(c)),
            physical={k: v for k, v in physical.items() if v},
            load_cases=sum(1 for g in groups if self._is_load_case(g)),
            combinations=sum(1 for g in groups if self._is_combination(g)),
            storeys=len(self._by_type("IfcBuildingStorey")),
        )

    def _by_type(self, cls: str) -> list[Any]:
        try:
            return list(self.f.by_type(cls))
        except Exception:
            return []

    # ── placement ──
    def placement(self, product: Any) -> np.ndarray:
        key = product.id()
        if key not in self._placements:
            matrix = np.eye(4)
            placement = getattr(product, "ObjectPlacement", None)
            if placement is not None:
                try:
                    matrix = np.asarray(
                        self.ios.util.placement.get_local_placement(placement), dtype=float
                    )
                except Exception:
                    self.dropped["unreadable placement (taken at the origin)"] += 1
            self._placements[key] = matrix
        return self._placements[key]

    def to_model(self, point_file: Vec) -> Vec:
        return np.asarray(point_file, dtype=float) * self.units.length

    # ── materials ──
    def material(self, material: Any | None) -> _Material:
        name = (getattr(material, "Name", None) or "Unnamed material") if material else ""
        if not name:
            name = "Default steel"
        if name in self.materials:
            return self.materials[name]
        kind, known = _kind_of(material) if material is not None else ("steel", False)
        psets: dict[str, dict[str, Any]] = {}
        if material is not None:
            try:
                psets = self.ios.util.element.get_psets(material)
            except Exception:
                psets = {}
        u = self.units
        mech = psets.get("Pset_MaterialMechanical", {})
        common = psets.get("Pset_MaterialCommon", {})
        steel = psets.get("Pset_MaterialSteel", {})
        concrete = psets.get("Pset_MaterialConcrete", {})
        defaults = CONCRETE_DEFAULTS if kind == "concrete" else STEEL_DEFAULTS
        pressure = u.si("MODULUSOFELASTICITYUNIT")
        stress = u.si("PRESSUREUNIT")
        e_si = _float(mech.get("YoungModulus")) * pressure
        g_si = _float(mech.get("ShearModulus")) * pressure
        nu = _float(mech.get("PoissonRatio"))
        rho_si = _float(common.get("MassDensity")) * u.mass_density_si()
        fy_si = _float(steel.get("YieldStress")) * stress
        fc_si = _float(concrete.get("CompressiveStrength")) * stress
        defaulted = e_si <= 0
        e_si = e_si if e_si > 0 else defaults["E"]
        nu = nu if 0 < nu < 0.5 else (e_si / (2 * g_si) - 1 if g_si > 0 else defaults["nu"])
        nu = min(max(nu, 0.0), 0.499)
        g_si = g_si if g_si > 0 else e_si / (2 * (1 + nu))
        rho_si = rho_si if rho_si > 0 else defaults["density"]
        result = _Material(
            name=name,
            kind=kind,
            E=u.from_si(e_si, -2, 1),
            G=u.from_si(g_si, -2, 1),
            nu=nu,
            unit_weight=u.from_si(rho_si * G_SI, -3, 1),
            rho=u.from_si(rho_si, -4, 1) * 1.0,  # kg/m³ → force·s²/length⁴
            fy=u.from_si(fy_si, -2, 1) if fy_si > 0 else None,
            fc=u.from_si(fc_si, -2, 1) if fc_si > 0 else None,
            defaulted=defaulted,
            studio=self._studio(psets),
        )
        if defaulted and not result.studio:
            label = "concrete" if kind == "concrete" else "steel"
            how = "" if known or material is None else " (its kind is not stated: taken as steel)"
            self.notes.append(
                f"Material '{name}' gives no elastic modulus: {label} defaults used{how}."
            )
        self.materials[name] = result
        return result

    def _studio(self, psets: dict[str, dict[str, Any]]) -> dict[str, float]:
        """This application's own exact values, converted from the system they were written in."""
        values = psets.get(STUDIO_PSET)
        if not values:
            return {}
        try:
            source = UnitSystem(values.get("Units"))
        except ValueError:
            return {}
        out: dict[str, float] = {}
        dims = {
            "E": (-2, 1),
            "G": (-2, 1),
            "A": (2, 0),
            "Iz": (4, 0),
            "Iy": (4, 0),
            "J": (4, 0),
            "UnitWeight": (-3, 1),
            "h": (1, 0),
            "nu": (0, 0),
            "rho": (-4, 1),
        }
        for key, (length, force) in dims.items():
            raw = values.get(key)
            if raw is None:
                continue
            si = float(raw) * metres_per_unit(source) ** length * newtons_per_unit(source) ** force
            out[key] = self.units.from_si(si, length, force)
        return out

    # ── frame sections ──
    def frame_section(
        self,
        names: Sequence[str | None],
        profile: Any | None,
        material: _Material,
        *,
        rotated: bool,
        ndm: int,
        truss: bool,
        mech: dict[str, Any] | None = None,
    ) -> tuple[Any, float]:
        """The section (or, for a truss, the area and material) of one member.

        Returns ``(section_or_material_id, area)``. Sections are shared by every
        member with the same profile, material and orientation.
        """
        label = (
            next((n for n in names if n), None)
            or (getattr(profile, "ProfileName", None) if profile is not None else None)
            or "IFC section"
        )
        key = (label, material.name, rotated, ndm, truss)
        if key in self.sections:
            return self.sections[key]
        studio = material.studio
        if not truss and not rotated and "A" in studio and "Iz" in studio:
            # Written by this application: the section exactly as it went out.
            section_id = len(self.section_list) + 1
            hint = _profile_shape(profile, self.units.length) if profile is not None else None
            if hint is not None and ndm == 2 and isinstance(hint, RectShape):
                hint = None  # an exported 2D rectangle is only the section's extent
            self.section_list.append(
                ElasticSection(
                    id=section_id,
                    name=label,
                    E=studio.get("E", material.E),
                    G=studio.get("G"),
                    A=studio["A"],
                    Iz=studio["Iz"],
                    Iy=studio.get("Iy"),
                    J=studio.get("J"),
                    shape=hint,
                    unit_weight=studio.get("UnitWeight", 0.0),
                )
            )
            self.sections[key] = (section_id, studio["A"])
            return self.sections[key]
        props = self._section_props(names, profile, material, mech)
        if truss:
            mat_id = self.truss_materials.get(material.name)
            if mat_id is None:
                mat_id = len(self.uniaxial) + 1
                self.uniaxial.append((mat_id, material))
                self.truss_materials[material.name] = mat_id
            self.sections[key] = (mat_id, studio.get("A", props.A))
            return self.sections[key]
        if ndm == 2:
            iz, iy = props.I_strong, props.I_weak
        else:
            # A 3D hint stands with its depth along local z: strong-axis bending is about y.
            iy, iz = props.I_strong, props.I_weak
            if rotated:
                iy, iz = iz, iy
        section_id = len(self.section_list) + 1
        name = label if not rotated else f"{label} (rotated 90°)"
        section = ElasticSection(
            id=section_id,
            name=name,
            E=material.studio.get("E", material.E),
            G=material.studio.get("G", material.G) if ndm == 3 else None,
            A=props.A,
            Iz=iz,
            Iy=iy if ndm == 3 else None,
            J=max(props.J, 1e-30) if ndm == 3 else None,
            shape=props.hint if not rotated else None,
            unit_weight=material.studio.get("UnitWeight", material.unit_weight),
        )
        self.section_list.append(section)
        self.sections[key] = (section_id, props.A)
        return self.sections[key]

    def _section_props(
        self,
        names: Sequence[str | None],
        profile: Any | None,
        material: _Material,
        mech: dict[str, Any] | None,
    ) -> _Props:
        studio = material.studio
        if "A" in studio and "Iz" in studio:
            # This application's values, met on a rotated member: Iy is the strong axis in 3D.
            return _Props(
                A=studio["A"],
                I_strong=studio.get("Iy") or studio["Iz"],
                I_weak=studio["Iz"],
                J=studio.get("J", 0.0),
                origin="OpenSees Studio values",
            )
        shape = _aisc_shape([*names, getattr(profile, "ProfileName", None)])
        if shape is not None:
            from opensees_studio.core.aisc import SOURCE_UNITS, shape_hint
            from opensees_studio.core.units import length_scale

            k = length_scale(SOURCE_UNITS, self.units.target)
            return _Props(
                A=shape.area * k**2,
                I_strong=shape.ix * k**4,
                I_weak=(shape.iy or shape.ix) * k**4,
                J=(shape.j or 0.0) * k**4,
                hint=shape_hint(shape, k),
                origin=f"AISC {shape.name}",
            )
        if mech:
            u = self.units
            area = _float(mech.get("CrossSectionArea")) * u.factor("AREAUNIT")
            iy = _float(mech.get("MomentOfInertiaY")) * u.factor("MOMENTOFINERTIAUNIT")
            iz = _float(mech.get("MomentOfInertiaZ")) * u.factor("MOMENTOFINERTIAUNIT")
            j = _float(mech.get("TorsionalConstantX")) * u.factor("MOMENTOFINERTIAUNIT")
            if area > 0 and iy > 0:
                hint = _profile_shape(profile, u.length) if profile is not None else None
                return _Props(
                    A=area,
                    I_strong=max(iy, iz),
                    I_weak=min(iy, iz) if iz > 0 else iy,
                    J=j,
                    hint=hint,
                    origin="Pset_ProfileMechanical",
                )
        if profile is not None:
            props = _props_from_profile(profile, self.units.length)
            if props is not None and props.A > 0:
                return props
            self.dropped[f"profile {profile.is_a()[3:]} (placeholder section used)"] += 1
        else:
            self.dropped["member without a profile (placeholder section used)"] += 1
        side = self.units.from_si(0.3, 1, 0)
        shape = RectShape(d=side, b=side)
        return _Props(
            A=side**2,
            I_strong=side**4 / 12,
            I_weak=side**4 / 12,
            J=_thin_wall_torsion(shape),
            hint=shape,
            origin="placeholder",
        )

    def shell_section(self, material: _Material, thickness: float) -> int:
        studio = material.studio
        h = studio.get("h", thickness)
        key = ("shell", material.name, round(h, 12))
        if key in self.sections:
            return int(self.sections[key][0])
        section_id = len(self.section_list) + 1
        self.section_list.append(
            ElasticMembranePlateSection(
                id=section_id,
                name=f"{material.name} t={h:g}",
                E=studio.get("E", material.E),
                nu=studio.get("nu", material.nu),
                h=h,
                rho=studio.get("rho", 0.0),
                unit_weight=studio.get("UnitWeight", material.unit_weight),
            )
        )
        self.sections[key] = (section_id, 0.0)
        return section_id

    # ── material and profile of a product or a structural member ──
    def profile_and_material(
        self, product: Any
    ) -> tuple[list[str | None], Any, Any, dict[str, Any]]:
        """``(names, profile, ifc material, profile pset)`` for a member, from whatever it carries."""
        util = self.ios.util.element
        names: list[str | None] = []
        profile = None
        material = None
        try:
            assigned = util.get_material(product, should_skip_usage=True)
        except Exception:
            assigned = None
        if assigned is not None:
            if assigned.is_a("IfcMaterialProfileSet") and assigned.MaterialProfiles:
                first = assigned.MaterialProfiles[0]
                profile = first.Profile
                material = first.Material
                names += [getattr(first, "Name", None), assigned.Name]
            elif assigned.is_a("IfcMaterialProfile"):
                profile, material = assigned.Profile, assigned.Material
                names.append(assigned.Name)
            elif assigned.is_a("IfcMaterial"):
                material = assigned
            elif assigned.is_a("IfcMaterialLayerSet") and assigned.MaterialLayers:
                material = assigned.MaterialLayers[0].Material
            elif assigned.is_a("IfcMaterialList") and assigned.Materials:
                material = assigned.Materials[0]
        try:
            element_type = util.get_type(product)
        except Exception:
            element_type = None
        if element_type is not None:
            names.append(element_type.Name)
        names.append(getattr(product, "ObjectType", None))
        mech: dict[str, Any] = {}
        if profile is not None:
            names.insert(0, getattr(profile, "ProfileName", None))
            try:
                mech = util.get_psets(profile).get("Pset_ProfileMechanical", {})
            except Exception:
                mech = {}
        return names, profile, material, mech

    # ── supports ──
    def _has_support(self, connection: Any) -> bool:
        condition = getattr(connection, "AppliedCondition", None)
        if condition is None or not condition.is_a("IfcBoundaryNodeCondition"):
            return False
        restraint, spring = self._condition(condition, (1.0, 1.0))
        return any(restraint) or any(k > 0 for k in spring)

    def _condition(
        self, condition: Any, scales: tuple[float, float]
    ) -> tuple[list[bool], list[float]]:
        """``(fixed, stiffness)`` per DOF of an ``IfcBoundaryNodeCondition``."""
        attrs = (
            "TranslationalStiffnessX",
            "TranslationalStiffnessY",
            "TranslationalStiffnessZ",
            "RotationalStiffnessX",
            "RotationalStiffnessY",
            "RotationalStiffnessZ",
        )
        fixed: list[bool] = []
        stiffness: list[float] = []
        for slot, attr in enumerate(attrs):
            raw = getattr(condition, attr, None)
            value = _value(raw)
            if isinstance(value, bool):
                fixed.append(value)
                stiffness.append(0.0)
                continue
            if value is None:
                fixed.append(False)
                stiffness.append(0.0)
                continue
            number = float(value)
            # IFC2x3 has no boolean: a negative or non-finite stiffness is the
            # usual way of writing "rigid".
            if number < 0 or not math.isfinite(number):
                fixed.append(True)
                stiffness.append(0.0)
            else:
                fixed.append(False)
                stiffness.append(number * scales[0 if slot < 3 else 1])
        return fixed, stiffness

    def _support_scales(self) -> tuple[float, float]:
        u = self.units
        return u.factor("LINEARSTIFFNESSUNIT"), u.factor("ROTATIONALSTIFFNESSUNIT")

    # ── load groups ──
    @staticmethod
    def _is_combination(group: Any) -> bool:
        return str(getattr(group, "PredefinedType", "")) in {
            "LOAD_COMBINATION",
            "LOAD_COMBINATION_GROUP",
        }

    @staticmethod
    def _is_load_case(group: Any) -> bool:
        if group.is_a("IfcStructuralLoadCase"):
            return True
        if group.is_a("IfcStructuralResultGroup") or not group.is_a("IfcStructuralLoadGroup"):
            return False
        return str(getattr(group, "PredefinedType", "")) == "LOAD_CASE"


# ──────────────────────────── analytical model ────────────────────────────
@dataclass
class _Member:
    ifc: Any
    i: int
    j: int
    truss: bool
    ref_id: int | None
    section_names: list[str | None]
    profile: Any
    material: Any
    mech: dict[str, Any]
    axis: Vec | None  # IFC local z, global, when the file gives one
    local_axis_angle: float | None = None
    """Explicit angle in degrees; None when the file predates the property."""
    geom_transf: str = "Linear"
    name: str = ""


def _ref_id(name: str | None, prefix: str) -> int | None:
    match = re.fullmatch(rf"{prefix}(\d+)", (name or "").strip())
    return int(match.group(1)) if match else None


def _studio_ids(items: Sequence[Any], prefix: str) -> dict[int, int] | None:
    """``id(ifc) -> tag`` when every item is named ``<prefix><n>`` and the tags are unique."""
    tags = {item.id(): _ref_id(getattr(item, "Name", None), prefix) for item in items}
    values = list(tags.values())
    if not values or any(v is None or v <= 0 for v in values) or len(set(values)) != len(values):
        return None
    return {k: int(v) for k, v in tags.items() if v is not None}


class _Analytical:
    """Translate the ``IfcStructuralAnalysisModel`` of a file."""

    def __init__(self, reader: _Reader) -> None:
        self.r = reader
        self.f = reader.f
        self.u = reader.units

    # ── vertices ──
    def _vertex(self, vertex: Any, matrix: np.ndarray) -> Vec | None:
        if vertex is None:
            return None
        geometry = getattr(vertex, "VertexGeometry", None)
        if geometry is None or not geometry.is_a("IfcCartesianPoint"):
            return None
        return self.r.to_model(_apply(matrix, _point(geometry)))

    def _topology(self, product: Any) -> list[Any]:
        rep = getattr(product, "Representation", None)
        if rep is None:
            return []
        return [item for r in rep.Representations for item in r.Items]

    def connection_point(self, connection: Any) -> Vec | None:
        matrix = self.r.placement(connection)
        for item in self._topology(connection):
            if item.is_a("IfcVertexPoint"):
                return self._vertex(item, matrix)
            if item.is_a("IfcCartesianPoint"):
                return self.r.to_model(_apply(matrix, _point(item)))
        return None

    def _edge_points(self, member: Any) -> tuple[Vec, Vec] | None:
        matrix = self.r.placement(member)
        for item in self._topology(member):
            edge = item.EdgeElement if item.is_a("IfcOrientedEdge") else item
            if edge.is_a("IfcEdge"):
                start = self._vertex(edge.EdgeStart, matrix)
                end = self._vertex(edge.EdgeEnd, matrix)
                if start is not None and end is not None:
                    if item.is_a("IfcOrientedEdge") and not item.Orientation:
                        start, end = end, start
                    return start, end
        return None

    def _face_points(self, member: Any) -> list[Vec] | None:
        matrix = self.r.placement(member)
        for item in self._topology(member):
            if not (item.is_a("IfcFaceSurface") or item.is_a("IfcFace")):
                continue
            for bound in item.Bounds:
                if not bound.is_a("IfcFaceOuterBound") and len(item.Bounds) > 1:
                    continue
                loop = bound.Bound
                points: list[Vec] = []
                if loop.is_a("IfcEdgeLoop"):
                    for oriented in loop.EdgeList:
                        edge = oriented.EdgeElement
                        vertex = edge.EdgeStart if oriented.Orientation else edge.EdgeEnd
                        p = self._vertex(vertex, matrix)
                        if p is None:
                            return None
                        points.append(p)
                elif loop.is_a("IfcPolyLoop"):
                    points = [self.r.to_model(_apply(matrix, _point(p))) for p in loop.Polygon]
                if not bound.Orientation:
                    points.reverse()
                return points
        return None

    # ── build ──
    def build(self) -> dict[str, Any]:
        r, u = self.r, self.u
        connections = r._by_type("IfcStructuralPointConnection")
        curves = r._by_type("IfcStructuralCurveMember")
        surfaces = r._by_type("IfcStructuralSurfaceMember") if r.options.include_shells else []
        if not r.options.include_shells and r._by_type("IfcStructuralSurfaceMember"):
            r.dropped["surface member (shells not requested)"] += len(
                r._by_type("IfcStructuralSurfaceMember")
            )
        points: dict[int, Vec] = {}
        for c in connections:
            p = self.connection_point(c)
            if p is None:
                r.dropped["point connection without a position"] += 1
                continue
            points[c.id()] = p
        everything = list(points.values())
        member_ends: dict[int, tuple[Vec, Vec]] = {}
        for m in curves:
            ends = self._edge_points(m)
            if ends is None:
                linked = [rel.RelatedStructuralConnection for rel in (m.ConnectedBy or [])]
                linked_points = [points[c.id()] for c in linked if c.id() in points]
                if len(linked_points) == 2:
                    ends = (linked_points[0], linked_points[1])
            if ends is None:
                r.dropped["curve member without two end points"] += 1
                continue
            member_ends[m.id()] = ends
            everything += list(ends)
        size = float(np.linalg.norm(np.ptp(np.array(everything), axis=0))) if everything else 1.0
        nodes = _Nodes(max(RELATIVE_TOLERANCE * size, 1e-9))
        self.nodes = nodes
        node_tags = _studio_ids([c for c in connections if c.id() in points], "N") or {}
        scales = r._support_scales()
        self.connection_node: dict[int, int] = {}
        for c in connections:
            if c.id() not in points:
                continue
            nid = nodes.add(points[c.id()], node_tags.get(c.id()))
            self.connection_node[c.id()] = nid
            condition = getattr(c, "AppliedCondition", None)
            if condition is not None and condition.is_a("IfcBoundaryNodeCondition"):
                fixed, spring = r._condition(condition, scales)
                nodes.restraint[nid] = [
                    a or b for a, b in zip(nodes.restraint[nid], fixed, strict=True)
                ]
                nodes.spring[nid] = [
                    max(a, b) for a, b in zip(nodes.spring[nid], spring, strict=True)
                ]
            elif condition is not None:
                r.dropped[f"support condition {condition.is_a()[3:]}"] += 1

        # 2D: the file says so, and every point is in the X-Z plane.
        model = next(iter(r._by_type("IfcStructuralAnalysisModel")), None)
        planar = str(getattr(model, "PredefinedType", "")) == "IN_PLANE_LOADING_2D"
        all_y0 = all(abs(p[1]) <= nodes.tolerance for p in nodes.coords.values())
        self.ndm = 2 if planar and all_y0 else 3
        if planar and not all_y0:
            r.notes.append(
                "The analysis model is declared 2D but its points are not in the X-Z plane: "
                "imported as a 3D model."
            )

        members: list[_Member] = []
        tags = _studio_ids([m for m in curves if m.id() in member_ends], "E") or {}
        for m in curves:
            ends = member_ends.get(m.id())
            if ends is None:
                continue
            i, j = nodes.add(ends[0]), nodes.add(ends[1])
            if i == j:
                r.dropped["curve member of zero length"] += 1
                continue
            if m.is_a("IfcStructuralCurveMemberVarying"):
                r.dropped["varying curve member (taken as prismatic)"] += 1
            names, profile, material, mech = self._member_section(m)
            truss = str(getattr(m, "PredefinedType", "")) in {
                "PIN_JOINED_MEMBER",
                "CABLE",
                "COMPRESSION_MEMBER",
                "TENSION_MEMBER",
            }
            axis = getattr(m, "Axis", None)
            members.append(
                _Member(
                    ifc=m,
                    i=i,
                    j=j,
                    truss=truss,
                    ref_id=tags.get(m.id()),
                    section_names=names,
                    profile=profile,
                    material=material,
                    mech=mech,
                    axis=None if axis is None else _direction(axis, (0, 0, 1)),
                    local_axis_angle=self._local_axis_angle(m),
                    geom_transf=self._geom_transf(m),
                    name=self._physical_name(m),
                )
            )
        shells: list[tuple[Any, list[int], float]] = []
        surface_tags = _studio_ids(surfaces, "E") or {}
        for s in surfaces:
            pts = self._face_points(s)
            if pts is None:
                r.dropped["surface member without a readable boundary"] += 1
                continue
            ids = [nodes.add(p) for p in pts]
            ids = [n for k, n in enumerate(ids) if n != ids[k - 1]] if len(ids) > 1 else ids
            if len(ids) != 4 or len(set(ids)) != 4:
                r.dropped[f"surface member with {len(set(ids))} corners (only quadrilaterals)"] += 1
                continue
            thickness = _float(getattr(s, "Thickness", None)) * u.length
            shells.append((s, ids, thickness))
        self.surface_tags = surface_tags
        return {"members": members, "shells": shells}

    def _geom_transf(self, member: Any) -> str:
        values = _pset_values(self.r.ios, member, STUDIO_MEMBER_PSET)
        value = values.get("GeomTransf")
        return value if value in ("Linear", "PDelta", "Corotational") else "Linear"

    def _local_axis_angle(self, member: Any) -> float | None:
        """The explicit local-axis angle of a member, or None for a file without it."""
        values = _pset_values(self.r.ios, member, STUDIO_MEMBER_PSET)
        if "LocalAxisAngle" not in values:
            return None
        return _float(values.get("LocalAxisAngle"), 0.0)

    def _physical_name(self, member: Any) -> str:
        """The name of the physical element a member is assigned to, unless it is a default one."""
        for rel in getattr(member, "HasAssignments", None) or []:
            if rel.is_a("IfcRelAssignsToProduct"):
                name = getattr(rel.RelatingProduct, "Name", None) or ""
                if not re.fullmatch(r"(Column|Beam|Member|Slab|Wall|Plate) \d+", name):
                    return name
        return ""

    def _member_section(self, member: Any) -> tuple[list[str | None], Any, Any, dict[str, Any]]:
        names, profile, material, mech = self.r.profile_and_material(member)
        if profile is not None and material is not None:
            return names, profile, material, mech
        # The analytical member may carry nothing: its physical twin does.
        for rel in getattr(member, "HasAssignments", None) or []:
            if rel.is_a("IfcRelAssignsToProduct"):
                product = rel.RelatingProduct
                n2, p2, m2, mech2 = self.r.profile_and_material(product)
                return (
                    names + n2,
                    profile or p2,
                    material or m2,
                    mech or mech2,
                )
        return names, profile, material, mech


# ──────────────────────────── physical model ────────────────────────────
@dataclass
class _Bar:
    product: Any
    start: Vec
    end: Vec
    half: float
    """Half the larger profile dimension, project units: how far a face is from the axis."""
    column: bool
    names: list[str | None]
    profile: Any
    material: Any
    mech: dict[str, Any]
    depth_dir: Vec | None
    local_axis_angle: float | None = None
    """Explicit angle in degrees; None when the file predates the property."""
    splits: list[float] = field(default_factory=list)


class _Physical:
    """Axes from solids, joined into a model."""

    def __init__(self, reader: _Reader) -> None:
        self.r = reader
        self.u = reader.units

    def _solid(self, product: Any) -> tuple[Any, np.ndarray] | None:
        """The extruded solid of a product's body, and its matrix in file coordinates."""
        rep = getattr(product, "Representation", None)
        if rep is None:
            return None
        base = self.r.placement(product)
        for representation in rep.Representations:
            if getattr(representation, "RepresentationIdentifier", None) not in (None, "Body"):
                continue
            for item in representation.Items:
                found = self._unwrap(item, np.eye(4))
                if found is not None:
                    solid, matrix = found
                    return solid, base @ matrix
        return None

    def _unwrap(self, item: Any, matrix: np.ndarray) -> tuple[Any, np.ndarray] | None:
        if item.is_a("IfcExtrudedAreaSolid"):
            return item, matrix @ _axis2_matrix(item.Position)
        if item.is_a("IfcBooleanResult"):
            return self._unwrap(item.FirstOperand, matrix)
        if item.is_a("IfcMappedItem"):
            source = item.MappingSource
            origin = _axis2_matrix(source.MappingOrigin)
            target = item.MappingTarget
            t = np.eye(4)
            if target is not None:
                t[:3, 3] = _point(target.LocalOrigin)
                x = _direction(target.Axis1, (1, 0, 0))
                y = _direction(target.Axis2, (0, 1, 0))
                z = _direction(getattr(target, "Axis3", None), tuple(np.cross(x, y)))
                scale = _float(getattr(target, "Scale", None), 1.0) or 1.0
                t[:3, 0], t[:3, 1], t[:3, 2] = x * scale, y * scale, z * scale
            for inner in source.MappedRepresentation.Items:
                found = self._unwrap(inner, matrix @ t @ origin)
                if found is not None:
                    return found
        return None

    def _axis_rep(self, product: Any) -> tuple[Vec, Vec] | None:
        rep = getattr(product, "Representation", None)
        if rep is None:
            return None
        for representation in rep.Representations:
            if getattr(representation, "RepresentationIdentifier", None) != "Axis":
                continue
            for item in representation.Items:
                if item.is_a("IfcPolyline") and len(item.Points) >= 2:
                    m = self.r.placement(product)
                    return _apply(m, _point(item.Points[0])), _apply(m, _point(item.Points[-1]))
        return None

    def _frame_angle(self, product: Any) -> float | None:
        """The explicit local-axis angle of a physical member, or None for an old file."""
        values = _pset_values(self.r.ios, product, STUDIO_FRAME_PSET)
        if "LocalAxisAngle" not in values:
            return None
        return _float(values.get("LocalAxisAngle"), 0.0)

    def bar(self, product: Any) -> _Bar | None:
        names, profile, material, mech = self.r.profile_and_material(product)
        found = self._solid(product)
        depth_dir: Vec | None = None
        if found is not None:
            solid, matrix = found
            profile = profile or solid.SweptArea
            ppos = _axis2_matrix(getattr(solid.SweptArea, "Position", None))
            origin2d = ppos[:3, 3]
            direction = _direction(solid.ExtrudedDirection, (0, 0, 1))
            depth = float(solid.Depth)
            start = _apply(matrix, origin2d)
            end = _apply(matrix, origin2d + direction * depth)
            depth_dir = matrix[:3, :3] @ ppos[:3, 1]
        axis = self._axis_rep(product)
        if axis is not None:
            start, end = axis
        elif found is None:
            return None
        start, end = self.r.to_model(start), self.r.to_model(end)
        if float(np.linalg.norm(end - start)) <= 0:
            return None
        props = _props_from_profile(profile, self.u.length) if profile is not None else None
        half = 0.5 * max(props.depth, props.width) if props is not None else 0.0
        axis_vec = end - start
        tilt = math.degrees(math.asin(min(1.0, abs(axis_vec[2]) / float(np.linalg.norm(axis_vec)))))
        return _Bar(
            product=product,
            start=start,
            end=end,
            half=half,
            column=product.is_a("IfcColumn") or tilt >= 90 - VERTICAL_TOLERANCE_DEG,
            names=names,
            profile=profile,
            material=material,
            mech=mech,
            depth_dir=None
            if depth_dir is None
            else depth_dir / max(float(np.linalg.norm(depth_dir)), 1e-30),
            local_axis_angle=self._frame_angle(product),
        )

    def plate(self, product: Any) -> tuple[list[Vec], float, Any] | None:
        """The mid-surface quadrilateral of a slab, wall or plate, and its thickness."""
        found = self._solid(product)
        if found is None:
            return None
        solid, matrix = found
        area = solid.SweptArea
        pts2: list[tuple[float, float]] | None
        if area.is_a("IfcRectangleProfileDef"):
            x, y = float(area.XDim) / 2, float(area.YDim) / 2
            pts2 = [(-x, -y), (x, -y), (x, y), (-x, y)]
        elif area.is_a("IfcArbitraryClosedProfileDef"):
            pts2 = _polygon_points(area.OuterCurve)
            if area.is_a("IfcArbitraryProfileDefWithVoids") and area.InnerCurves:
                self.r.dropped["opening in a slab or wall (ignored)"] += len(area.InnerCurves)
        else:
            pts2 = None
        if pts2 is None:
            return None
        pts2 = _drop_collinear(pts2)
        if len(pts2) != 4:
            self.r.dropped[
                f"slab or wall outline with {len(pts2)} corners (only quadrilaterals)"
            ] += 1
            return None
        ppos = _axis2_matrix(getattr(area, "Position", None))
        local = [ppos[:3, :3] @ np.array([p[0], p[1], 0.0]) + ppos[:3, 3] for p in pts2]
        direction = _direction(solid.ExtrudedDirection, (0, 0, 1)) * float(solid.Depth)
        depth = float(np.linalg.norm(direction))
        widths = _quad_widths(local)
        material = self.r.profile_and_material(product)[2]
        if depth <= min(widths):
            # A slab: the profile is the plan, the extrusion is the thickness.
            corners = [_apply(matrix, p + direction / 2) for p in local]
            thickness = depth
        else:
            # A wall: the profile is the footprint (length × thickness), extruded up.
            long_pair = _long_midline(local)
            if long_pair is None:
                self.r.dropped["wall footprint that is not a rectangle"] += 1
                return None
            a, b, thickness_file = long_pair
            corners = [
                _apply(matrix, a),
                _apply(matrix, b),
                _apply(matrix, b + direction),
                _apply(matrix, a + direction),
            ]
            thickness = thickness_file
        return [self.r.to_model(c) for c in corners], thickness * self.u.length, material


def _drop_collinear(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out = list(points)
    changed = True
    while changed and len(out) > 3:
        changed = False
        for k in range(len(out)):
            a, b, c = out[k - 1], out[k], out[(k + 1) % len(out)]
            cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
            scale = max(math.dist(a, b) * math.dist(b, c), 1e-30)
            if abs(cross) / scale < 1e-9:
                del out[k]
                changed = True
                break
    return out


def _quad_widths(points: list[Vec]) -> list[float]:
    """The two distances between opposite edges' midpoints of a quadrilateral."""
    mids = [(points[k] + points[(k + 1) % 4]) / 2 for k in range(4)]
    return [float(np.linalg.norm(mids[0] - mids[2])), float(np.linalg.norm(mids[1] - mids[3]))]


def _long_midline(points: list[Vec]) -> tuple[Vec, Vec, float] | None:
    """The midline of a rectangular footprint along its long side, and its short side."""
    edges = [float(np.linalg.norm(points[(k + 1) % 4] - points[k])) for k in range(4)]
    if edges[0] >= edges[1]:
        a = (points[0] + points[3]) / 2
        b = (points[1] + points[2]) / 2
        return a, b, (edges[1] + edges[3]) / 2
    a = (points[0] + points[1]) / 2
    b = (points[3] + points[2]) / 2
    return a, b, (edges[0] + edges[2]) / 2


def _closest_on_segment(p: Vec, a: Vec, b: Vec) -> tuple[float, float]:
    """``(t, distance)`` of the point of segment ``ab`` nearest ``p``."""
    ab = b - a
    length2 = float(ab @ ab)
    t = 0.0 if length2 == 0 else float(np.clip((p - a) @ ab / length2, 0.0, 1.0))
    return t, float(np.linalg.norm(a + t * ab - p))


def _segment_crossing(a: Vec, b: Vec, c: Vec, d: Vec) -> tuple[float, float, float] | None:
    """``(s, t, distance)`` of the closest points of two segments, interior only."""
    u, v, w = b - a, d - c, a - c
    aa, bb, cc, dd, ee = u @ u, u @ v, v @ v, u @ w, v @ w
    den = aa * cc - bb * bb
    if den <= 1e-12 * aa * cc:
        return None  # parallel
    s = (bb * ee - cc * dd) / den
    t = (aa * ee - bb * dd) / den
    if not (0 < s < 1 and 0 < t < 1):
        return None
    return float(s), float(t), float(np.linalg.norm(a + s * u - (c + t * v)))


def _join(bars: list[_Bar], tol: float) -> tuple[int, int]:
    """Move member ends onto the axes they stop at, and mark where members are split.

    Columns carry beams, beams carry beams: an end is joined only to a member of
    the same or a higher rank, columns first, so a column top is never dragged to
    a beam that stops beside it. Beams are joined to columns before they are
    joined to each other, so a secondary beam lands on its girder's final axis.
    Returns ``(ends moved, crossings split)``.
    """
    snapped = 0

    def join_end(bar: _Bar, end_name: str, targets: list[_Bar]) -> bool:
        nonlocal snapped
        p = getattr(bar, end_name)
        best: tuple[float, _Bar, float] | None = None
        for other in targets:
            if other is bar:
                continue
            reach = JOIN_MARGIN * max(other.half, bar.half) + tol
            t, d = _closest_on_segment(p, other.start, other.end)
            if d <= reach and (best is None or d < best[0]):
                best = (d, other, t)
        if best is None:
            return False
        d, other, t = best
        length = float(np.linalg.norm(other.end - other.start))
        near = JOIN_MARGIN * other.half + tol
        if t * length <= near:
            target = other.start.copy()
        elif (1 - t) * length <= near:
            target = other.end.copy()
        else:
            target = other.start + t * (other.end - other.start)
            other.splits.append(t)
        if float(np.linalg.norm(target - p)) > tol:
            snapped += 1
        setattr(bar, end_name, target)
        return True

    columns = [b for b in bars if b.column]
    others = [b for b in bars if not b.column]
    done: set[tuple[int, str]] = set()
    for bar in columns:
        for end_name in ("start", "end"):
            if join_end(bar, end_name, columns):
                done.add((id(bar), end_name))
    for bar in others:
        for end_name in ("start", "end"):
            if join_end(bar, end_name, columns):
                done.add((id(bar), end_name))
    for bar in others:
        for end_name in ("start", "end"):
            if (id(bar), end_name) not in done:
                join_end(bar, end_name, others)
    crossings = 0
    for k, a_bar in enumerate(bars):
        la = float(np.linalg.norm(a_bar.end - a_bar.start))
        for b_bar in bars[k + 1 :]:
            hit = _segment_crossing(a_bar.start, a_bar.end, b_bar.start, b_bar.end)
            if hit is None:
                continue
            s_a, t_b, d = hit
            lb = float(np.linalg.norm(b_bar.end - b_bar.start))
            interior = tol < s_a * la < la - tol and tol < t_b * lb < lb - tol
            if d <= tol and interior:
                a_bar.splits.append(s_a)
                b_bar.splits.append(t_b)
                crossings += 1
    return snapped, crossings


def _orientation(depth_dir: Vec | None, i: Vec, j: Vec) -> tuple[bool, bool]:
    """``(rotated, oblique)``: is the profile's depth along our local y instead of z?"""
    if depth_dir is None:
        return False, False
    axes = frame_local_axes(3, i.tolist(), j.tolist())
    if axes is None:
        return False, False
    x, y, z = axes
    d = depth_dir - (depth_dir @ x) * x
    norm = float(np.linalg.norm(d))
    if norm < 1e-9:
        return False, False
    d /= norm
    cz, cy = abs(float(d @ z)), abs(float(d @ y))
    rotated = cy > cz
    oblique = min(cz, cy) > math.sin(math.radians(5))
    return rotated, oblique


def _pset_values(ios: Any, product: Any, name: str) -> dict[str, Any]:
    """The properties of ``name`` on ``product``, or an empty dict."""
    try:
        return cast(dict[str, Any], ios.util.element.get_psets(product).get(name, {}))
    except Exception:
        return {}


# ──────────────────────────── loads ────────────────────────────
class _Loads:
    def __init__(
        self,
        reader: _Reader,
        ndm: int,
        ndf: int,
        coords: dict[int, Vec],
        connection_node: dict[int, int],
        member_of: dict[int, Any],
    ) -> None:
        self.r = reader
        self.u = reader.units
        self.ndm, self.ndf = ndm, ndf
        self.coords = coords
        self.connection_node = connection_node
        self.member_of = member_of  # id(ifc member) -> project element

    def _actions(self, group: Any, seen: set[int] | None = None) -> list[Any]:
        seen = seen if seen is not None else set()
        if group.id() in seen:
            return []
        seen.add(group.id())
        out: list[Any] = []
        for rel in getattr(group, "IsGroupedBy", None) or []:
            for obj in rel.RelatedObjects:
                if obj.is_a("IfcStructuralAction"):
                    out.append(obj)
                elif obj.is_a("IfcStructuralLoadGroup") and not _Reader._is_load_case(obj):
                    out += self._actions(obj, seen)
        return out

    def _target(self, action: Any) -> Any:
        for rel in getattr(action, "AssignedToStructuralItem", None) or []:
            return rel.RelatingElement
        return None

    def _ifc_axes(self, element: Any, member: Any) -> tuple[Vec, Vec, Vec]:
        pi, pj = self.coords[element.nodes[0]], self.coords[element.nodes[1]]
        x = (pj - pi) / float(np.linalg.norm(pj - pi))
        axis = getattr(member, "Axis", None)
        ours = frame_local_axes(
            self.ndm,
            pi.tolist(),
            pj.tolist(),
            float(getattr(element, "local_axis_angle", 0.0) or 0.0),
        )
        assert ours is not None
        if axis is None:
            return ours
        z = _direction(axis, (0, 0, 1))
        z = z - (z @ x) * x
        if float(np.linalg.norm(z)) < 1e-9:
            return ours
        z /= float(np.linalg.norm(z))
        return x, np.cross(z, x), z

    def _to_local(self, element: Any, member: Any, vector: Vec, local: bool) -> Vec:
        pi, pj = self.coords[element.nodes[0]], self.coords[element.nodes[1]]
        ours = frame_local_axes(
            self.ndm,
            pi.tolist(),
            pj.tolist(),
            float(getattr(element, "local_axis_angle", 0.0) or 0.0),
        )
        assert ours is not None
        if local:
            x, y, z = self._ifc_axes(element, member)
            vector = vector[0] * x + vector[1] * y + vector[2] * z
        return np.array([float(vector @ ours[0]), float(vector @ ours[1]), float(vector @ ours[2])])

    def pattern(self, pid: int, name: str, group: Any) -> PlainLoadPattern:
        u = self.u
        force, torque = u.factor("FORCEUNIT"), u.factor("TORQUEUNIT")
        linear, planar = u.factor("LINEARFORCEUNIT"), u.factor("PLANARFORCEUNIT")
        nodal: dict[int, list[float]] = {}
        imposed: list[ImposedDisplacement] = []
        uniform: list[UniformElementLoad] = []
        trapezoid: list[TrapezoidalElementLoad] = []
        points: list[PointElementLoad] = []
        surfaces: list[SurfaceLoad] = []
        slots = dof_indices(self.ndm, self.ndf)
        for action in self._actions(group):
            target = self._target(action)
            load = action.AppliedLoad
            local = str(getattr(action, "GlobalOrLocal", "GLOBAL_COORDS")) == "LOCAL_COORDS"
            if target is None or load is None:
                self.r.dropped["load action on nothing"] += 1
                continue
            if target.is_a("IfcStructuralPointConnection"):
                nid = self.connection_node.get(target.id())
                if nid is None:
                    self.r.dropped["load on a point connection that was not imported"] += 1
                    continue
                if load.is_a("IfcStructuralLoadSingleForce"):
                    values = [
                        _float(load.ForceX) * force,
                        _float(load.ForceY) * force,
                        _float(load.ForceZ) * force,
                        _float(load.MomentX) * torque,
                        _float(load.MomentY) * torque,
                        _float(load.MomentZ) * torque,
                    ]
                    current = nodal.setdefault(nid, [0.0] * 6)
                    for k in range(6):
                        if k in slots:
                            current[k] += values[k]
                        elif values[k]:
                            self.r.dropped["nodal load component outside the model's DOF"] += 1
                elif load.is_a("IfcStructuralLoadSingleDisplacement"):
                    values = [
                        _float(load.DisplacementX) * u.length,
                        _float(load.DisplacementY) * u.length,
                        _float(load.DisplacementZ) * u.length,
                        _float(load.RotationalDisplacementRX),
                        _float(load.RotationalDisplacementRY),
                        _float(load.RotationalDisplacementRZ),
                    ]
                    for slot, value in enumerate(values):
                        if value and slot in slots:
                            imposed.append(
                                ImposedDisplacement(
                                    node_id=nid, dof=slots.index(slot) + 1, value=value
                                )
                            )
                else:
                    self.r.dropped[f"{load.is_a()[3:]} on a point"] += 1
                continue
            element = self.member_of.get(target.id())
            if element is None:
                self.r.dropped["load on a member that was not imported"] += 1
                continue
            if isinstance(element, ShellMITC4Element):
                if not load.is_a("IfcStructuralLoadPlanarForce"):
                    self.r.dropped[f"{load.is_a()[3:]} on a surface"] += 1
                    continue
                vector = (
                    np.array(
                        [
                            _float(load.PlanarForceX),
                            _float(load.PlanarForceY),
                            _float(load.PlanarForceZ),
                        ]
                    )
                    * planar
                )
                if local:
                    if vector[0] or vector[1]:
                        self.r.dropped["in-plane surface load component"] += 1
                    if vector[2]:
                        surfaces.append(
                            SurfaceLoad(
                                element_id=element.id, value=float(vector[2]), direction="normal"
                            )
                        )
                else:
                    for k in range(3):
                        if vector[k]:
                            surfaces.append(
                                SurfaceLoad(
                                    element_id=element.id,
                                    value=float(vector[k]),
                                    direction=_GLOBAL_AXES[k],
                                )
                            )
                continue
            pi, pj = self.coords[element.nodes[0]], self.coords[element.nodes[1]]
            length = float(np.linalg.norm(pj - pi))
            if action.is_a("IfcStructuralPointAction"):
                if not load.is_a("IfcStructuralLoadSingleForce"):
                    self.r.dropped[f"{load.is_a()[3:]} at a point of a member"] += 1
                    continue
                vector = (
                    np.array([_float(load.ForceX), _float(load.ForceY), _float(load.ForceZ)])
                    * force
                )
                if any(_float(getattr(load, a)) for a in ("MomentX", "MomentY", "MomentZ")):
                    self.r.dropped["concentrated moment on a member"] += 1
                where = self._action_point(action)
                x = _closest_on_segment(where, pi, pj)[0] if where is not None else 0.5
                lv = self._to_local(element, target, vector, local)
                points.append(
                    PointElementLoad(element_id=element.id, px=lv[0], py=lv[1], pz=lv[2], x=x)
                )
                continue
            if not action.is_a("IfcStructuralCurveAction") and not action.is_a(
                "IfcStructuralLinearAction"
            ):
                self.r.dropped[f"{action.is_a()[3:]}"] += 1
                continue
            projected = str(getattr(action, "ProjectedOrTrue", "TRUE_LENGTH")) == "PROJECTED_LENGTH"
            pieces = self._linear_pieces(load, length)
            if pieces is None:
                self.r.dropped[f"{load.is_a()[3:]} along a member"] += 1
                continue
            converted = []
            for x0, w0, x1, w1 in pieces:
                v0 = self._line_vector(w0 * linear, element, target, local, projected)
                v1 = self._line_vector(w1 * linear, element, target, local, projected)
                converted.append((x0, v0, x1, v1))
            if (
                len(converted) == 1
                and converted[0][0] <= 1e-9
                and converted[0][2] >= 1 - 1e-9
                and np.allclose(converted[0][1], converted[0][3])
            ):
                v = converted[0][1]
                uniform.append(UniformElementLoad(element_id=element.id, wx=v[0], wy=v[1], wz=v[2]))
            else:
                for x0, v0, x1, v1 in converted:
                    trapezoid.append(
                        TrapezoidalElementLoad(
                            element_id=element.id,
                            x_start=x0,
                            x_end=x1,
                            wx_start=v0[0],
                            wx_end=v1[0],
                            wy_start=v0[1],
                            wy_end=v1[1],
                            wz_start=v0[2],
                            wz_end=v1[2],
                        )
                    )
        sw = getattr(group, "SelfWeightCoefficients", None)
        self_weight = 0.0
        if sw:
            coeffs = [float(c) for c in sw]
            self_weight = -coeffs[2] if len(coeffs) > 2 else 0.0
            if any(abs(c) > 0 for c in coeffs[:2]):
                self.r.dropped["horizontal self-weight coefficient"] += 1
        return PlainLoadPattern(
            id=pid,
            name=name,
            time_series_id=1,
            nodal_loads=[NodalLoad(node_id=n, forces=tuple(v)) for n, v in nodal.items()],  # type: ignore[arg-type]
            element_loads=uniform,
            point_loads=points,
            distributed_loads=trapezoid,
            surface_loads=surfaces,
            imposed_displacements=imposed,
            self_weight=self_weight,
        )

    def _action_point(self, action: Any) -> Vec | None:
        rep = getattr(action, "Representation", None)
        if rep is not None:
            for r in rep.Representations:
                for item in r.Items:
                    if item.is_a("IfcVertexPoint"):
                        return self.r.to_model(_point(item.VertexGeometry))
        if getattr(action, "ObjectPlacement", None) is not None:
            return self.r.to_model(self.r.placement(action)[:3, 3])
        return None

    def _linear_pieces(
        self, load: Any, length: float
    ) -> list[tuple[float, Vec, float, Vec]] | None:
        def vec(item: Any) -> Vec:
            return np.array(
                [_float(item.LinearForceX), _float(item.LinearForceY), _float(item.LinearForceZ)]
            )

        if load.is_a("IfcStructuralLoadLinearForce"):
            if any(
                _float(getattr(load, a))
                for a in ("LinearMomentX", "LinearMomentY", "LinearMomentZ")
            ):
                self.r.dropped["distributed moment on a member"] += 1
            w = vec(load)
            return [(0.0, w, 1.0, w)]
        if load.is_a("IfcStructuralLoadConfiguration"):
            values = [v for v in load.Values if v.is_a("IfcStructuralLoadLinearForce")]
            if len(values) < 2 or len(values) != len(values):
                return None
            locations = load.Locations or []
            if len(locations) != len(values):
                stations = [float(v) for v in np.linspace(0.0, 1.0, len(values))]
            else:
                stations = [
                    float(min(max(float(loc[0]) * self.u.length / max(length, 1e-30), 0.0), 1.0))
                    for loc in locations
                ]
            return [
                (stations[k], vec(values[k]), stations[k + 1], vec(values[k + 1]))
                for k in range(len(values) - 1)
                if stations[k + 1] > stations[k]
            ]
        return None

    def _line_vector(self, w: Vec, element: Any, member: Any, local: bool, projected: bool) -> Vec:
        if projected and not local:
            pi, pj = self.coords[element.nodes[0]], self.coords[element.nodes[1]]
            x = (pj - pi) / float(np.linalg.norm(pj - pi))
            w = np.array([w[k] * math.sqrt(max(0.0, 1 - x[k] ** 2)) for k in range(3)])
        return self._to_local(element, member, w, local)


# ──────────────────────────── assembly ────────────────────────────
def inspect_ifc(path: str | Path) -> IfcInventory:
    """What a file holds, before importing it."""
    return _Reader(Path(path), IfcImportOptions()).inventory()


def import_ifc(path: str | Path, options: IfcImportOptions | None = None) -> IfcImport:
    """Read ``path`` and build a new project from its analytical or physical model.

    Raises:
        IfcImportError: unreadable file, nothing structural in it, or a model
            the project refuses.
    """
    options = options or IfcImportOptions()
    reader = _Reader(Path(path), options)
    inventory = reader.inventory()
    source: Literal["analytical", "physical"] = (
        inventory.default_source() if options.source == "auto" else options.source
    )
    if source == "analytical" and not inventory.has_analytical:
        raise IfcImportError(f"{Path(path).name} has no structural analysis model.")
    if source == "physical" and inventory.physical_frames + inventory.physical_shells == 0:
        raise IfcImportError(
            f"{Path(path).name} has no columns, beams, members, slabs or walls to import."
        )
    if source == "analytical":
        project = _build_analytical(reader, Path(path))
    else:
        project = _build_physical(reader, Path(path))
    if inventory.physical and source == "analytical":
        reader.notes.append("Built from the analytical model; the physical model was not read.")
    return IfcImport(
        project=project,
        source=source,
        inventory=inventory,
        notes=reader.notes,
        dropped=reader.dropped,
    )


def _release(condition: Any, reader: _Reader, rotated: bool, ndm: int) -> EndRelease | None:
    if condition is None or not condition.is_a("IfcBoundaryNodeCondition"):
        return None
    fixed, spring = reader._condition(condition, reader._support_scales())
    names = ("T", "M2", "M3")
    released: list[str] = []
    springs: dict[str, float] = {}
    for k, name in enumerate(names):
        slot = 3 + k
        raw = getattr(
            condition,
            ("RotationalStiffnessX", "RotationalStiffnessY", "RotationalStiffnessZ")[k],
            None,
        )
        if raw is None or fixed[slot]:
            continue
        ours = name
        if rotated and name in ("M2", "M3"):
            ours = "M3" if name == "M2" else "M2"
        if ndm == 2 and ours != "M3":
            continue
        released.append(ours)
        if spring[slot] > 0:
            springs[ours] = spring[slot]
    if any(
        not fixed[k] and getattr(condition, a, None) is not None
        for k, a in enumerate(
            ("TranslationalStiffnessX", "TranslationalStiffnessY", "TranslationalStiffnessZ")
        )
    ):
        reader.dropped["translational end release"] += 1
    if not released:
        return None
    return EndRelease(released=tuple(sorted(released)), springs=springs)  # type: ignore[arg-type]


def _build_analytical(reader: _Reader, path: Path) -> Project:
    a = _Analytical(reader)
    built = a.build()
    members: list[_Member] = built["members"]
    shells = built["shells"]
    if not members and not shells:
        raise IfcImportError(f"{path.name}: no curve or surface member could be read.")
    ndm = a.ndm
    trusses_only = all(m.truss for m in members) and not shells
    ndf = (2 if ndm == 2 else 3) if trusses_only else (3 if ndm == 2 else 6)
    nodes = a.nodes
    elements: list[Any] = []
    member_of: dict[int, Any] = {}
    used_ids: set[int] = set()
    next_id = 1

    def take(wanted: int | None) -> int:
        nonlocal next_id
        if wanted is not None and wanted not in used_ids:
            used_ids.add(wanted)
            return wanted
        while next_id in used_ids:
            next_id += 1
        used_ids.add(next_id)
        return next_id

    oblique = 0
    rotated_count = 0
    for m in members:
        pi, pj = nodes.coords[m.i], nodes.coords[m.j]
        material = reader.material(m.material)
        explicit_angle = m.local_axis_angle is not None
        angle = m.local_axis_angle or 0.0
        rotated = obl = False
        if ndm == 3 and not m.truss and not explicit_angle:
            rotated, obl = _orientation(m.axis, pi, pj)
            oblique += obl
            rotated_count += rotated
        section_id, area = reader.frame_section(
            m.section_names,
            m.profile,
            material,
            rotated=rotated,
            ndm=ndm,
            truss=m.truss,
            mech=m.mech,
        )
        eid = take(m.ref_id)
        if m.truss:
            element: Any = TrussElement(
                id=eid,
                name=m.name,
                nodes=(m.i, m.j),
                area=area,
                material_id=section_id,
                unit_weight=material.studio.get("UnitWeight", material.unit_weight),
            )
        else:
            ends: dict[str, EndRelease] = {}
            for rel in m.ifc.ConnectedBy or []:
                nid = a.connection_node.get(rel.RelatedStructuralConnection.id())
                end = "i" if nid == m.i else "j" if nid == m.j else None
                release = _release(getattr(rel, "AppliedCondition", None), reader, rotated, ndm)
                if end is not None and release is not None:
                    ends[end] = release
            releases = FrameReleases()
            if ends:
                i_end, j_end = ends.get("i", EndRelease()), ends.get("j", EndRelease())
                if "T" in i_end.released and "T" in j_end.released:
                    j_end = EndRelease(
                        released=tuple(x for x in j_end.released if x != "T"),
                        springs={k: v for k, v in j_end.springs.items() if k != "T"},
                    )
                    reader.dropped["torsion release at both ends (kept at end i)"] += 1
                releases = FrameReleases(i=i_end, j=j_end)
            element = ElasticBeamColumn(
                id=eid,
                name=m.name,
                nodes=(m.i, m.j),
                section_id=section_id,
                releases=releases,
                geom_transf=m.geom_transf,  # type: ignore[arg-type]
                local_axis_angle=angle,
            )
        elements.append(element)
        member_of[m.ifc.id()] = element
    if rotated_count:
        reader.notes.append(
            f"{rotated_count} member(s) have their profile turned 90° from this application's "
            "local axes: their section was imported with Iy and Iz exchanged."
        )
    if oblique:
        reader.notes.append(
            f"{oblique} member(s) have a profile turned by an angle that is not a multiple of "
            "90°: imported with the nearest orientation."
        )
    for surface, ids, thickness in shells:
        _, _, material_ifc, _ = a._member_section(surface)
        material = reader.material(material_ifc)
        if thickness <= 0:
            thickness = material.studio.get("h", 0.0)
        if thickness <= 0:
            reader.dropped["surface member without a thickness"] += 1
            continue
        element = ShellMITC4Element(
            id=take(a.surface_tags.get(surface.id())),
            nodes=tuple(ids),
            section_id=reader.shell_section(material, thickness),
        )
        elements.append(element)
        member_of[surface.id()] = element
    patterns, cases, combinations = _loads(
        reader, ndm, ndf, nodes.coords, a.connection_node, member_of
    )
    return _project(reader, path, ndm, ndf, nodes, elements, patterns, cases, combinations)


def _loads(
    reader: _Reader,
    ndm: int,
    ndf: int,
    coords: dict[int, Vec],
    connection_node: dict[int, int],
    member_of: dict[int, Any],
) -> tuple[list[PlainLoadPattern], list[StaticCase], list[LoadCombination]]:
    if not reader.options.include_loads:
        return [], [], []
    loads = _Loads(reader, ndm, ndf, coords, connection_node, member_of)
    groups = reader._by_type("IfcStructuralLoadGroup")
    patterns: list[PlainLoadPattern] = []
    cases: list[StaticCase] = []
    case_of: dict[int, int] = {}
    for group in groups:
        if not reader._is_load_case(group):
            continue
        pid = len(patterns) + 1
        name = group.Name or f"Load case {pid}"
        try:
            pattern = loads.pattern(pid, name, group)
        except ValidationError as exc:
            reader.dropped[f"load case refused by the model ({exc.errors()[0]['msg']})"] += 1
            continue
        patterns.append(pattern)
        cases.append(StaticCase(id=pid, name=name, pattern_ids=[pid]))
        case_of[group.id()] = pid
    combinations: list[LoadCombination] = []
    combo_of: dict[int, int] = {}
    combos = [g for g in groups if reader._is_combination(g)]
    for group in combos:
        combo_of[group.id()] = len(combo_of) + 1
    for group in combos:
        terms: list[CombinationTerm] = []
        for rel in getattr(group, "IsGroupedBy", None) or []:
            factor = (
                float(getattr(rel, "Factor", 1.0) or 1.0)
                if rel.is_a("IfcRelAssignsToGroupByFactor")
                else 1.0
            )
            for obj in rel.RelatedObjects:
                if obj.id() in case_of:
                    terms.append(
                        CombinationTerm(source="case", ref_id=case_of[obj.id()], factor=factor)
                    )
                elif obj.id() in combo_of:
                    terms.append(
                        CombinationTerm(
                            source="combination", ref_id=combo_of[obj.id()], factor=factor
                        )
                    )
        kind = _COMBINATION_KIND.get(str(group.Description), "LinearAdd")
        combinations.append(
            LoadCombination(
                id=combo_of[group.id()],
                name=group.Name or f"Combination {combo_of[group.id()]}",
                combination_type=kind,
                terms=terms,
            )
        )
    return patterns, cases, combinations


def _build_physical(reader: _Reader, path: Path) -> Project:
    phys = _Physical(reader)
    bars: list[_Bar] = []
    for cls in ("IfcColumn", "IfcBeam", "IfcMember"):
        for product in reader._by_type(cls):
            bar = phys.bar(product)
            if bar is None:
                reader.dropped[f"{cls[3:]} without an extruded body or axis"] += 1
                continue
            bars.append(bar)
    plates: list[tuple[list[Vec], float, Any]] = []
    if reader.options.include_shells:
        for cls in ("IfcSlab", "IfcWall", "IfcWallStandardCase", "IfcPlate"):
            for product in reader._by_type(cls):
                if cls == "IfcWall" and product.is_a("IfcWallStandardCase"):
                    continue
                plate = phys.plate(product)
                if plate is None:
                    reader.dropped[f"{cls[3:]} whose shape is not a quadrilateral prism"] += 1
                    continue
                plates.append(plate)
    if not bars and not plates:
        raise IfcImportError(f"{path.name}: no member or plate geometry could be read.")
    everything = [p for b in bars for p in (b.start, b.end)] + [c for pl in plates for c in pl[0]]
    size = float(np.linalg.norm(np.ptp(np.array(everything), axis=0)))
    tol = max(RELATIVE_TOLERANCE * size, 1e-9)

    snapped, crossings = _join(bars, tol)
    nodes = _Nodes(tol)
    for bar in bars:
        nodes.add(bar.start)
        nodes.add(bar.end)
    elements: list[Any] = []
    oblique = rotated_count = 0
    for bar in bars:
        stations = sorted({0.0, 1.0, *(s for s in bar.splits if 1e-9 < s < 1 - 1e-9)})
        points = [bar.start + s * (bar.end - bar.start) for s in stations]
        ids = [nodes.add(p) for p in points]
        material = reader.material(bar.material)
        explicit_angle = bar.local_axis_angle is not None
        angle = bar.local_axis_angle or 0.0
        rotated = obl = False
        if not explicit_angle:
            rotated, obl = _orientation(bar.depth_dir, bar.start, bar.end)
            oblique += obl
            rotated_count += rotated
        section_id, _ = reader.frame_section(
            bar.names, bar.profile, material, rotated=rotated, ndm=3, truss=False, mech=bar.mech
        )
        for a_id, b_id in itertools.pairwise(ids):
            if a_id == b_id:
                continue
            elements.append(
                ElasticBeamColumn(
                    id=len(elements) + 1,
                    nodes=(a_id, b_id),
                    section_id=section_id,
                    local_axis_angle=angle,
                )
            )
    if snapped or crossings:
        reader.notes.append(
            f"Axes joined: {snapped} member end(s) moved onto the axis of the member they "
            f"stop at, {crossings} crossing(s) split. Check the connections before running."
        )
    if rotated_count:
        reader.notes.append(
            f"{rotated_count} member(s) have their profile turned 90° from this application's "
            "local axes: their section was imported with Iy and Iz exchanged."
        )
    if oblique:
        reader.notes.append(
            f"{oblique} member(s) have a profile turned by an angle that is not a multiple of "
            "90°: imported with the nearest orientation."
        )
    # Plates: attach each corner to the nearest node within reach, else a new node.
    max_half = max((b.half for b in bars), default=0.0)
    attached = loose = 0
    frame_nodes = set(nodes.coords)
    for corners, thickness, material_ifc in plates:
        reach = thickness / 2 + max_half + tol
        ids = []
        for corner in corners:
            found = nodes.find(corner, reach) if frame_nodes else None
            if found is not None and found in frame_nodes:
                ids.append(found)
                attached += 1
            else:
                ids.append(nodes.add(corner))
                loose += 1
        if len(set(ids)) != 4:
            reader.dropped["slab or wall that collapsed onto fewer than four nodes"] += 1
            continue
        material = reader.material(material_ifc)
        if material.kind != "concrete" and material.defaulted and not material.studio:
            pass
        elements.append(
            ShellMITC4Element(
                id=len(elements) + 1,
                nodes=tuple(ids),  # type: ignore[arg-type]
                section_id=reader.shell_section(material, thickness),
            )
        )
    if plates:
        reader.notes.append(
            f"Slabs and walls: {attached} corner(s) attached to a member node, {loose} on new "
            "nodes. Each slab or wall is one shell: subdivide it with Edit → Mesh, which also "
            "connects the members along its edges."
        )
    if reader.options.fix_column_bases:
        bottoms = [min((bar.start, bar.end), key=lambda p: p[2]) for bar in bars if bar.column]
        if bottoms:
            lowest = min(float(p[2]) for p in bottoms)
            fixed = 0
            for p in bottoms:
                if abs(float(p[2]) - lowest) <= max(tol, 1e-6 * size):
                    nid = nodes.find(p)
                    if nid is not None:
                        nodes.restraint[nid] = [True] * 6
                        fixed += 1
            reader.notes.append(
                f"The physical model carries no supports: the {fixed} column base(s) at the "
                "lowest level were fixed."
            )
    else:
        reader.notes.append("The physical model carries no supports: assign them before running.")
    reader.notes.append("The physical model carries no loads.")
    return _project(reader, path, 3, 6, nodes, elements, [], [], [])


def _project(
    reader: _Reader,
    path: Path,
    ndm: int,
    ndf: int,
    nodes: _Nodes,
    elements: list[Any],
    patterns: list[PlainLoadPattern],
    cases: list[StaticCase],
    combinations: list[LoadCombination],
) -> Project:
    used = {n for e in elements for n in e.nodes}
    for pattern in patterns:
        used |= {nl.node_id for nl in pattern.nodal_loads}
        used |= {d.node_id for d in pattern.imposed_displacements}
    restrained_only = [
        nid
        for nid in nodes.coords
        if nid not in used and (any(nodes.restraint[nid]) or any(nodes.spring[nid]))
    ]
    used |= set(restrained_only)
    loose = [nid for nid in nodes.coords if nid not in used]
    if loose:
        reader.dropped["point connection on no member"] += len(loose)
    node_list = []
    for nid in sorted(used):
        p = nodes.coords[nid]
        coords = (float(p[0]), 0.0 if ndm == 2 else float(p[1]), float(p[2]))
        node_list.append(
            Node(
                id=nid,
                coords=coords,
                restraint=tuple(nodes.restraint[nid]),  # type: ignore[arg-type]
                spring=tuple(nodes.spring[nid]),  # type: ignore[arg-type]
            )
        )
    materials: list[Any] = []
    for mat_id, material in reader.uniaxial:
        materials.append(
            ElasticUniaxial(id=mat_id, name=material.name, E=material.studio.get("E", material.E))
        )
    next_material = len(materials) + 1
    for material in reader.materials.values():
        if material.kind == "steel" and material.fy:
            materials.append(
                Steel01(id=next_material, name=material.name, Fy=material.fy, E0=material.E, b=0.01)
            )
            next_material += 1
        elif material.kind == "concrete" and material.fc:
            fc = material.fc
            materials.append(
                Concrete01(
                    id=next_material,
                    name=material.name,
                    fpc=-fc,
                    epsc0=-0.002,
                    fpcu=-0.2 * fc,
                    epsU=-0.006,
                )
            )
            next_material += 1
    storeys: list[Storey] = []
    if ndm == 3 and node_list:
        # A storey at the lowest node is the base itself (``core.storeys.storey_levels``
        # gives it no row); the export writes one, and it is not a floor.
        base = min(n.coords[2] for n in node_list) + nodes.tolerance
        seen: set[float] = set()
        for storey in reader._by_type("IfcBuildingStorey"):
            elevation = getattr(storey, "Elevation", None)
            z = (
                float(elevation) * reader.units.length
                if elevation is not None
                else float(reader.placement(storey)[2, 3]) * reader.units.length
            )
            key = round(z, 9)
            if key in seen or z <= base:
                continue
            seen.add(key)
            storeys.append(
                Storey(
                    id=len(storeys) + 1,
                    name=storey.Name or f"Storey {len(storeys) + 1}",
                    elevation=z,
                )
            )
    try:
        project = Project(
            meta=ProjectMeta(
                name=path.stem,
                description=f"Imported from IFC ({path.name}, {reader.f.schema}).",
                units=reader.units.target,
            ),
            ndm=ndm,
            ndf=ndf,
            coord_systems=[default_global_system()],
            nodes=node_list,
            materials=materials,
            sections=list(reader.section_list),
            elements=elements,
            storeys=storeys,
            time_series=[LinearTimeSeries(id=1, name="Linear")] if patterns else [],
            load_patterns=[*patterns],
            analyses=[*cases],
            combinations=combinations,
        )
        project.validate_references()
    except (ValidationError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            first = exc.errors()[0]
            detail = f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}"
        else:
            detail = str(exc)
        raise IfcImportError(f"{path.name} does not make a valid project: {detail}") from exc
    return project
