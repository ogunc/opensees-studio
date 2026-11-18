"""Import a PORTICO model (``.s3d``) as a new project, scaled to our units.

PORTICO (``jpreyes/portico-core``) saves its models as JSON: nodes, frame
elements, materials, sections, load cases and combinations, plus areas,
diaphragms and links. This module reads the frame part of that file and builds
a :class:`Project` out of it, in the unit system the caller picks.

Units. PORTICO never converts: the ``units`` label of a file says which
consistent system its numbers are in (``kN-m`` with mass in tonnes, the
``kip-in`` of a SAP2000 benchmark, ...). Every quantity is scaled from that
system to the target one by its dimension — lengths, forces, moments, stresses,
masses (force·s²/length), densities, spring stiffnesses — so a ``kN-m`` file
opened as ``SI (m, N, kg)`` has its forces multiplied by 1000 and its densities
in kg/m³. The factors are in :class:`UnitScale` and shown to the user.

Local axes. PORTICO builds a member's triad as ``z = x × ref`` and
``y = z × x`` (``ref`` global Z, or global X for a member within 2° of
vertical), so a beam has its local y up. OpenSees takes ``vecxz`` from
:mod:`core.geometry.local_axes`, which gives a 3D beam its local z up. The two
triads share local x and differ by a turn about it, so per member the importer
works out whether PORTICO's y is OpenSees' y (``direct``) or OpenSees' z
(``swapped``) and maps the section (``Iz`` / ``Iy``, ``Avy`` / ``Avz``) and the
end releases accordingly. Distributed loads are projected onto the OpenSees
axes as vectors, which is exact for any turn. A member whose triads are turned
by some other angle keeps the nearest orientation and is reported when its
section is not symmetric.

What does not come across is counted and reported, never dropped silently:
areas, diaphragms, links, the mass source, temperature loads, response
spectrum cases, translational end releases, and the nonlinear flags
(``cable`` / ``compressionOnly``).
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import ValidationError

from opensees_studio.core.analysis import StaticCase
from opensees_studio.core.combinations import CombinationTerm, LoadCombination
from opensees_studio.core.constraints import EqualDOFConstraint, RigidDiaphragm, RigidLink
from opensees_studio.core.geometry.elements import (
    ElasticBeamColumn,
    ShellMITC4Element,
    TrussElement,
)
from opensees_studio.core.geometry.frame_options import EndRelease, FrameReleases
from opensees_studio.core.geometry.grid import (
    CoordinateGridSystem,
    GridSystem,
    default_global_system,
    make_grid_lines,
)
from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.geometry.node import Node
from opensees_studio.core.loads import (
    ImposedDisplacement,
    LinearTimeSeries,
    NodalLoad,
    PlainLoadPattern,
    TemperatureLoad,
    TrapezoidalElementLoad,
    UniformElementLoad,
)
from opensees_studio.core.mass_source import MassSource, MassSourcePattern
from opensees_studio.core.materials import ElasticUniaxial
from opensees_studio.core.project import Project, ProjectMeta
from opensees_studio.core.sections import ElasticMembranePlateSection, ElasticSection
from opensees_studio.core.units import UnitSystem, gravity, metres_per_unit, newtons_per_unit

_KIP_N = 4448.2216152605
_LBF_N = 4.4482216152605
_KGF_N = 9.80665

#: PORTICO unit label → (metres per length unit, newtons per force unit).
SOURCE_UNITS: dict[str, tuple[float, float]] = {
    "kN-m": (1.0, 1e3),
    "N-m": (1.0, 1.0),
    "kN-mm": (1e-3, 1e3),
    "N-mm": (1e-3, 1.0),
    "kN-cm": (1e-2, 1e3),
    "ton-m": (1.0, 1e3 * _KGF_N),
    "kgf-m": (1.0, _KGF_N),
    "kgf-cm": (1e-2, _KGF_N),
    "kip-in": (0.0254, _KIP_N),
    "kip-ft": (0.3048, _KIP_N),
    "lb-in": (0.0254, _LBF_N),
    "lb-ft": (0.3048, _LBF_N),
}

#: The project unit system a file opens in unless the caller picks another one.
DEFAULT_TARGET: dict[str, UnitSystem] = {
    "kN-m": UnitSystem.SI_M_N,
    "N-m": UnitSystem.SI_M_N,
    "kN-mm": UnitSystem.SI_MM_N,
    "N-mm": UnitSystem.SI_MM_N,
    "kN-cm": UnitSystem.SI_M_N,
    "ton-m": UnitSystem.SI_M_N,
    "kgf-m": UnitSystem.SI_M_N,
    "kgf-cm": UnitSystem.SI_M_N,
    "kip-in": UnitSystem.US_IN_KIP,
    "kip-ft": UnitSystem.US_FT_KIP,
    "lb-in": UnitSystem.US_IN_KIP,
    "lb-ft": UnitSystem.US_FT_KIP,
}

#: PORTICO's own default when a file carries no label.
DEFAULT_SOURCE_UNITS = "kN-m"

#: PORTICO's threshold for a "vertical" member: |x · Z| above it uses global X as reference.
_PORTICO_VERTICAL = 0.9994

#: Cosine above which two local axes count as the same direction (about 0.06°).
_ALIGNED = 1.0 - 1e-6

_DOF_NAMES = ("ux", "uy", "uz", "rx", "ry", "rz")
_MASS_KEYS = ("mx", "my", "mz", "irx", "iry", "irz")
_SPRING_KEYS = ("kux", "kuy", "kuz", "krx", "kry", "krz")

#: Storage slot → OpenSees DOF number for a 2D frame (Ux, Uz, Ry, see core.plane).
_DOF_2D = {0: 1, 2: 2, 4: 3}


class S3dImportError(RuntimeError):
    """The file cannot be read as a PORTICO model, or does not make a valid project."""


@dataclass(frozen=True)
class UnitScale:
    """Factors taking a quantity from the file's unit system to the project's."""

    length: float
    force: float

    @property
    def moment(self) -> float:
        return self.force * self.length

    @property
    def stress(self) -> float:
        return self.force / self.length**2

    @property
    def area(self) -> float:
        return self.length**2

    @property
    def inertia(self) -> float:
        return self.length**4

    @property
    def line_load(self) -> float:
        """Force per length: a distributed load or a translational spring."""
        return self.force / self.length

    @property
    def mass(self) -> float:
        """Coherent mass, force·s²/length (tonnes in ``kN-m``, kg in ``N-m``)."""
        return self.force / self.length

    @property
    def mass_inertia(self) -> float:
        return self.mass * self.length**2

    @property
    def density(self) -> float:
        return self.mass / self.length**3

    @property
    def is_identity(self) -> bool:
        return math.isclose(self.length, 1.0) and math.isclose(self.force, 1.0)


def unit_scale(source: str, target: UnitSystem) -> UnitScale:
    """Factors from the PORTICO system ``source`` to the project system ``target``."""
    try:
        metres, newtons = SOURCE_UNITS[source]
    except KeyError:
        known = ", ".join(SOURCE_UNITS)
        raise S3dImportError(
            f"Unknown PORTICO unit system {source!r} (known: {known}). Pick the file's "
            "units by hand."
        ) from None
    return UnitScale(
        length=metres / metres_per_unit(target), force=newtons / newtons_per_unit(target)
    )


# ──────────────────────────── reading ────────────────────────────
_COLLECTIONS = (
    "nodes",
    "elements",
    "areas",
    "materials",
    "sections",
    "diaphragms",
    "links",
    "loadCases",
    "combinations",
)


@dataclass(frozen=True)
class S3dFile:
    """A PORTICO file, parsed and checked for shape but not yet translated."""

    path: Path
    data: dict[str, Any]

    @property
    def units(self) -> str:
        """The file's own unit label (PORTICO's default when it has none)."""
        return str(self.data.get("units") or DEFAULT_SOURCE_UNITS)

    @property
    def mode(self) -> str:
        return "2D" if self.data.get("mode") == "2D" else "3D"

    def items(self, key: str) -> list[dict[str, Any]]:
        return list(self.data.get(key) or [])

    def counts(self) -> dict[str, int]:
        return {key: len(self.items(key)) for key in _COLLECTIONS}

    def summary(self) -> str:
        counts = self.counts()
        parts = [
            f"{counts['nodes']} node(s)",
            f"{counts['elements']} frame element(s)",
            f"{counts['loadCases']} load case(s)",
            f"{counts['combinations']} combination(s)",
        ]
        others = [
            f"{counts[key]} {label}"
            for key, label in (
                ("areas", "area(s)"),
                ("diaphragms", "diaphragm(s)"),
                ("links", "link(s)"),
            )
            if counts[key]
        ]
        text = f"{self.mode} model in {self.units}: " + ", ".join(parts)
        if others:
            text += "; " + ", ".join(others)
        return text + "."


def read_s3d(path: str | Path) -> S3dFile:
    """Parse ``path`` and check that it has the shape of a PORTICO model.

    Raises:
        S3dImportError: if the file is missing, is not JSON, or its collections
            are not lists of objects.
    """
    source = Path(path)
    if not source.is_file():
        raise S3dImportError(f"No such file: {source}")
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise S3dImportError(f"{source.name} is not a readable PORTICO file ({exc}).") from exc
    if not isinstance(data, dict):
        raise S3dImportError(f"{source.name}: a PORTICO file is a JSON object.")
    for key in _COLLECTIONS:
        value = data.get(key)
        if value is None:
            continue
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise S3dImportError(f"{source.name}: {key!r} must be a list of objects.")
    return S3dFile(path=source, data=data)


# ──────────────────────────── translation ────────────────────────────
@dataclass
class S3dImport:
    """The project an import produced, the factors it used and what it left out."""

    project: Project
    source_units: str
    scale: UnitScale
    notes: list[str] = field(default_factory=list)
    dropped: Counter[str] = field(default_factory=Counter)

    def summary(self) -> str:
        project = self.project
        shells = sum(isinstance(e, ShellMITC4Element) for e in project.elements)
        text = (
            f"{len(project.nodes)} node(s), {len(project.elements) - shells} member(s), "
            f"{shells} shell(s), {len(project.sections)} section(s), "
            f"{len(project.analyses)} static case(s), {len(project.combinations)} combination(s)"
        )
        extras = [
            f"{len(items)} {label}"
            for items, label in (
                (project.diaphragms, "diaphragm(s)"),
                (project.rigid_links, "rigid link(s)"),
                (project.mp_constraints, "equalDOF constraint(s)"),
            )
            if items
        ]
        if project.mass_source is not None:
            extras.append("a mass source")
        text += (", " + ", ".join(extras) if extras else "") + "."
        if self.dropped:
            items = ", ".join(f"{count} {what}" for what, count in sorted(self.dropped.items()))
            text += f" Not imported: {items}."
        return text


def _number(item: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = item.get(key, default)
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise S3dImportError(f"{key!r} must be a number, not {value!r}.") from None
    if not math.isfinite(number):
        raise S3dImportError(f"{key!r} must be finite, not {value!r}.")
    return number


def _entity_id(item: dict[str, Any], kind: str) -> int:
    value = item.get("id")
    if isinstance(value, bool) or not isinstance(value, int | float) or value != int(value):
        raise S3dImportError(f"A {kind} has no integer id ({value!r}).")
    if int(value) < 1:
        raise S3dImportError(f"{kind.capitalize()} id {int(value)} is not positive.")
    return int(value)


def _by_id(items: list[dict[str, Any]], kind: str) -> dict[int, dict[str, Any]]:
    table: dict[int, dict[str, Any]] = {}
    for item in items:
        key = _entity_id(item, kind)
        if key in table:
            raise S3dImportError(f"{kind.capitalize()} id {key} appears twice.")
        table[key] = item
    return table


def portico_local_axes(
    p_i: np.ndarray, p_j: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """PORTICO's member triad ``(x, y, z)`` (``localAxes`` in its ``timoshenko.js``)."""
    x = (p_j - p_i) / float(np.linalg.norm(p_j - p_i))
    ref = np.array([1.0, 0.0, 0.0]) if abs(x[2]) > _PORTICO_VERTICAL else np.array([0.0, 0.0, 1.0])
    z = np.cross(x, ref)
    z /= float(np.linalg.norm(z))
    return x, np.cross(z, x), z


@dataclass(frozen=True)
class _Orientation:
    """How a member's PORTICO local y and z land on the OpenSees ones."""

    swapped: bool
    """PORTICO's y is (±) OpenSees' z: Iz/Iy, Avy/Avz and ry/rz trade places."""
    exact: bool
    """The triads agree up to the swap and signs; False for any other turn."""


def _orientation(ndm: int, p_i: np.ndarray, p_j: np.ndarray) -> _Orientation:
    ours = frame_local_axes(ndm, p_i.tolist(), p_j.tolist())
    if ours is None:
        raise S3dImportError("zero-length member")
    _, y_p, _ = portico_local_axes(p_i, p_j)
    along_y = abs(float(np.dot(y_p, ours[1])))
    along_z = abs(float(np.dot(y_p, ours[2])))
    swapped = along_z > along_y
    return _Orientation(swapped=swapped, exact=max(along_y, along_z) >= _ALIGNED)


def _load_vector(load: dict[str, Any], p_i: np.ndarray, p_j: np.ndarray) -> np.ndarray:
    """Unit direction a PORTICO distributed load acts along, in global axes."""
    direction = str(load.get("dir") or "gravity")
    x_p, y_p, z_p = portico_local_axes(p_i, p_j)
    vectors = {
        "localX": x_p,
        "localY": y_p,
        "localZ": z_p,
        "globalX": np.array([1.0, 0.0, 0.0]),
        "globalY": np.array([0.0, 1.0, 0.0]),
        # Positive w on gravity (and the legacy globalZ) points down.
        "gravity": np.array([0.0, 0.0, -1.0]),
        "globalZ": np.array([0.0, 0.0, -1.0]),
    }
    if direction not in vectors:
        raise S3dImportError(f"unknown load direction {direction!r}")
    return vectors[direction]


class _Translator:
    def __init__(self, s3d: S3dFile, target: UnitSystem, source_units: str) -> None:
        self.s3d = s3d
        self.target = target
        self.source_units = source_units
        self.scale = unit_scale(source_units, target)
        self.ndm = 2 if s3d.mode == "2D" else 3
        self.notes: list[str] = []
        self.dropped: Counter[str] = Counter()
        self.nodes: dict[int, Node] = {}
        self.points: dict[int, np.ndarray] = {}
        self.materials = _by_id(s3d.items("materials"), "material")
        self.raw_sections = _by_id(s3d.items("sections"), "section")
        self.sections: list[ElasticSection] = []
        self._section_keys: dict[tuple[int, int, bool, bool], int] = {}
        self._materials_of: dict[int, set[int]] = {}
        for item in s3d.items("elements"):
            sec_id, mat_id = int(item.get("secId", 0)), int(item.get("matId", 0))
            self._materials_of.setdefault(sec_id, set()).add(mat_id)
        self.elements: list[ElasticBeamColumn | TrussElement] = []
        self.truss_materials: list[ElasticUniaxial] = []
        self._one_way_materials: dict[tuple[int, bool], int] = {}
        self.one_way = 0
        self.area_sections: list[ElasticMembranePlateSection] = []
        self.area_elements: list[ShellMITC4Element] = []
        self.oblique = 0

    # ── nodes ──
    def build_nodes(self) -> None:
        s = self.scale
        for item in self.s3d.items("nodes"):
            node_id = _entity_id(item, "node")
            if node_id in self.nodes:
                raise S3dImportError(f"Node id {node_id} appears twice.")
            x, y, z = (_number(item, axis) * s.length for axis in ("x", "y", "z"))
            if self.ndm == 2 and abs(y) > 1e-9 * max(1.0, abs(x), abs(z)):
                raise S3dImportError(
                    f"Node {node_id} is off the X-Z plane (y = {y:g}) in a 2D model."
                )
            if self.ndm == 2:
                y = 0.0
            restraints = item.get("restraints") or {}
            restraint = [bool(restraints.get(name)) for name in _DOF_NAMES]
            if self.ndm == 2:
                # PORTICO restrains a 2D model's out-of-plane DOFs itself; here they do not exist.
                restraint = [restraint[k] if k in _DOF_2D else False for k in range(6)]
            masses = item.get("nodeMass") or {}
            mass = tuple(
                _number(masses, key) * (s.mass if k < 3 else s.mass_inertia)
                for k, key in enumerate(_MASS_KEYS)
            )
            springs = item.get("springs") or {}
            spring = tuple(
                _number(springs, key) * (s.line_load if k < 3 else s.moment)
                for k, key in enumerate(_SPRING_KEYS)
            )
            if self.ndm == 2:
                mass = tuple(m if k in _DOF_2D else 0.0 for k, m in enumerate(mass))
                spring = tuple(v if k in _DOF_2D else 0.0 for k, v in enumerate(spring))
            for extra in ("springUni", "springK", "soilSpring"):
                if item.get(extra):
                    self.dropped[f"node {extra}"] += 1
            try:
                self.nodes[node_id] = Node(
                    id=node_id,
                    coords=(x, y, z),
                    restraint=tuple(restraint),  # type: ignore[arg-type]
                    mass=mass,  # type: ignore[arg-type]
                    spring=spring,  # type: ignore[arg-type]
                )
            except ValidationError as exc:
                raise S3dImportError(f"Node {node_id}: {_first_error(exc)}") from exc
            self.points[node_id] = np.array([x, y, z])

    def imposed_displacements(self) -> list[ImposedDisplacement]:
        imposed: list[ImposedDisplacement] = []
        for item in self.s3d.items("nodes"):
            prescribed = item.get("prescDisp") or {}
            node_id = _entity_id(item, "node")
            for slot, name in enumerate(_DOF_NAMES):
                value = _number(prescribed, name)
                if value == 0.0:
                    continue
                if self.ndm == 2 and slot not in _DOF_2D:
                    self.dropped["out-of-plane prescribed displacement"] += 1
                    continue
                dof = _DOF_2D[slot] if self.ndm == 2 else slot + 1
                scaled = value * self.scale.length if slot < 3 else value
                imposed.append(ImposedDisplacement(node_id=node_id, dof=dof, value=scaled))
        return imposed

    # ── sections and members ──
    def _section(self, sec_id: int, mat_id: int, swapped: bool, shear: bool) -> int:
        key = (sec_id, mat_id, swapped, shear)
        if key in self._section_keys:
            return self._section_keys[key]
        sec = self.raw_sections[sec_id]
        mat = self.materials[mat_id]
        s = self.scale
        mod = sec.get("mod") or {}
        a = _number(sec, "A") * _number(mod, "A", 1.0) * s.area
        iz = _number(sec, "Iz") * _number(mod, "Iz", 1.0) * s.inertia
        iy = _number(sec, "Iy") * _number(mod, "Iy", 1.0) * s.inertia
        j = _number(sec, "J") * _number(mod, "J", 1.0) * s.inertia
        # PORTICO scales the shear areas with the area modifier.
        avy = _number(sec, "Avy") * _number(mod, "A", 1.0) * s.area
        avz = _number(sec, "Avz") * _number(mod, "A", 1.0) * s.area
        if swapped:
            iz, iy, avy, avz = iy, iz, avz, avy
        e = _number(mat, "E") * s.stress
        g = _number(mat, "G") * s.stress
        if g <= 0.0:
            nu = _number(mat, "nu", 0.0)
            g = e / (2.0 * (1.0 + nu)) if e > 0 else 0.0
        unit_weight = _number(mat, "rho") * s.density * gravity(self.target)
        section_id = len(self.sections) + 1
        name = str(sec.get("name") or f"Section {sec_id}")
        if len(self._materials_of[sec_id]) > 1:
            # One PORTICO section with several materials becomes one section per material.
            name = f"{name} / {mat.get('name') or f'Material {mat_id}'}"
        if swapped:
            name += " (axes 2-3)"
        if not shear and (avy > 0 or avz > 0):
            name += " (no shear)"
        fields: dict[str, Any] = {"id": section_id, "name": name, "E": e, "A": a, "Iz": iz}
        if self.ndm == 3:
            fields.update(Iy=iy, G=g, J=j)
        if shear:
            fields.update(G=g, As2=avy)
            if self.ndm == 3:
                fields["As3"] = avz
        if unit_weight > 0:
            fields["unit_weight"] = unit_weight
        try:
            self.sections.append(ElasticSection(**fields))
        except ValidationError as exc:
            raise S3dImportError(
                f"Section {sec_id} with material {mat_id}: {_first_error(exc)}"
            ) from exc
        self._section_keys[key] = section_id
        return section_id

    def _releases(self, element_id: int, item: dict[str, Any], swapped: bool) -> FrameReleases:
        flags = list(item.get("releases") or [0] * 12)
        if len(flags) != 12:
            raise S3dImportError(f"Element {element_id}: 'releases' must have 12 entries.")
        springs = item.get("endSprings") or {}
        about_y, about_z = ("M3", "M2") if swapped else ("M2", "M3")
        rotation = {3: "T", 4: about_y, 5: about_z}
        ends: list[EndRelease] = []
        for end in (0, 1):
            released: list[str] = []
            end_springs: dict[str, float] = {}
            for local in range(6):
                dof = 6 * end + local
                if not flags[dof]:
                    continue
                if local < 3:
                    self.dropped["translational end release"] += 1
                    continue
                name = rotation[local]
                if self.ndm == 2 and name != "M3":
                    continue  # out of plane: a 2D frame has no such action
                released.append(name)
                k = springs.get(str(dof), springs.get(dof))
                if k:
                    end_springs[name] = float(k) * self.scale.moment
            ends.append(EndRelease(released=tuple(released), springs=end_springs))  # type: ignore[arg-type]
        for dof in springs:
            if not flags[int(dof)]:
                self.dropped["end spring on a fixed action"] += 1
        if "T" in ends[0].released and "T" in ends[1].released:
            ends[1] = EndRelease(
                released=tuple(r for r in ends[1].released if r != "T"),
                springs={k: v for k, v in ends[1].springs.items() if k != "T"},
            )
            self.notes.append(
                f"Element {element_id}: torsion released at both ends; kept at end j "
                "(the member would spin about its own axis)."
            )
        return FrameReleases(i=ends[0], j=ends[1])

    def build_elements(self, trapezoidal: set[int]) -> None:
        for item in self.s3d.items("elements"):
            element_id = _entity_id(item, "element")
            ni, nj = int(item.get("n1", 0)), int(item.get("n2", 0))
            for node_id in (ni, nj):
                if node_id not in self.nodes:
                    raise S3dImportError(f"Element {element_id} uses missing node {node_id}.")
            mat_id, sec_id = int(item.get("matId", 0)), int(item.get("secId", 0))
            if mat_id not in self.materials:
                raise S3dImportError(f"Element {element_id} uses missing material {mat_id}.")
            if sec_id not in self.raw_sections:
                raise S3dImportError(f"Element {element_id} uses missing section {sec_id}.")
            p_i, p_j = self.points[ni], self.points[nj]
            if float(np.linalg.norm(p_j - p_i)) < 1e-12:
                raise S3dImportError(f"Element {element_id} has zero length.")
            orientation = _orientation(self.ndm, p_i, p_j)
            sec = self.raw_sections[sec_id]
            if not orientation.exact and not _symmetric(sec):
                self.oblique += 1
            releases = self._releases(element_id, item, orientation.swapped)
            has_shear = _number(sec, "Avy") > 0 and (self.ndm == 2 or _number(sec, "Avz") > 0)
            # OpenSees' ElasticTimoshenkoBeam takes no releases and no trapezoidal load.
            shear = has_shear and not releases.any and element_id not in trapezoidal
            if has_shear and not shear:
                self.dropped["shear deformation (member with releases or a trapezoidal load)"] += 1
            mat = self.materials[mat_id]
            mod = sec.get("mod") or {}
            area = _number(sec, "A") * _number(mod, "A", 1.0) * self.scale.area
            rho = _number(mat, "rho") * self.scale.density * area
            if item.get("cable") or item.get("compressionOnly"):
                self.elements.append(
                    self._one_way_bar(element_id, (ni, nj), mat_id, area, bool(item.get("cable")))
                )
                continue
            self.elements.append(
                ElasticBeamColumn(
                    id=element_id,
                    nodes=(ni, nj),
                    section_id=self._section(sec_id, mat_id, orientation.swapped, shear),
                    rho=rho,
                    # PORTICO assembles a consistent mass matrix.
                    consistent_mass=rho > 0,
                    releases=releases,
                )
            )

    def _one_way_bar(
        self, element_id: int, nodes: tuple[int, int], mat_id: int, area: float, cable: bool
    ) -> TrussElement:
        """A tension-only (cable) or compression-only (strut) member, as a truss.

        PORTICO's cable and compression-only members are axial bars that go slack
        on the wrong side. Here: an elastic material with ``E`` on the working
        side and (next to) nothing on the other — ``Eneg = 0`` for a cable, and
        ``E * 1e-9`` in tension for a strut, since ``E`` must be positive.
        """
        mat = self.materials[mat_id]
        e = _number(mat, "E") * self.scale.stress
        key = (mat_id, cable)
        if key not in self._one_way_materials:
            material_id = len(self.truss_materials) + 1
            self._one_way_materials[key] = material_id
            name = f"{mat.get('name') or f'Material {mat_id}'} ({'tension' if cable else 'compression'} only)"
            self.truss_materials.append(
                ElasticUniaxial(id=material_id, name=name, E=e, Eneg=0.0)
                if cable
                else ElasticUniaxial(id=material_id, name=name, E=e * 1e-9, Eneg=e)
            )
        density = _number(mat, "rho") * self.scale.density
        self.one_way += 1
        return TrussElement(
            id=element_id,
            nodes=nodes,
            area=area,
            material_id=self._one_way_materials[key],
            rho=density * area,
            unit_weight=density * gravity(self.target),
        )

    # ── loads ──
    def trapezoidal_elements(self) -> set[int]:
        found: set[int] = set()
        for case in self.s3d.items("loadCases"):
            for load in case.get("loads") or []:
                varies = load.get("w2") is not None and _number(load, "w2") != _number(load, "w")
                if load.get("type") == "dist" and varies:
                    found.add(int(load.get("elemId", 0)))
        return found

    def _element_load(
        self, load: dict[str, Any], by_id: dict[int, ElasticBeamColumn | TrussElement]
    ) -> UniformElementLoad | TrapezoidalElementLoad | None:
        element_id = int(load.get("elemId", 0))
        element = by_id.get(element_id)
        if element is None:
            # PORTICO skips such a load without a word; here it is at least counted.
            self.dropped["load on a missing element"] += 1
            return None
        if isinstance(element, TrussElement):
            self.dropped["distributed load on a tension- or compression-only bar"] += 1
            return None
        p_i, p_j = self.points[element.nodes[0]], self.points[element.nodes[1]]
        axes = frame_local_axes(self.ndm, p_i.tolist(), p_j.tolist())
        assert axes is not None  # zero-length members were refused above
        try:
            direction = _load_vector(load, p_i, p_j)
        except S3dImportError as exc:
            raise S3dImportError(f"Element {element_id}: {exc}") from exc
        w_i = _number(load, "w") * self.scale.line_load
        w_j = _number(load, "w2", _number(load, "w")) * self.scale.line_load
        local = [float(np.dot(direction, axis)) for axis in axes]
        if self.ndm == 2 and abs(local[2]) > 1e-9:
            self.dropped["out-of-plane distributed load"] += 1
            local[2] = 0.0
        clean = [0.0 if abs(c) < 1e-12 else c for c in local]
        wx, wy, wz = clean
        if math.isclose(w_i, w_j):
            return UniformElementLoad(element_id=element_id, wx=wx * w_i, wy=wy * w_i, wz=wz * w_i)
        return TrapezoidalElementLoad(
            element_id=element_id,
            wx_start=wx * w_i,
            wx_end=wx * w_j,
            wy_start=wy * w_i,
            wy_end=wy * w_j,
            wz_start=wz * w_i,
            wz_end=wz * w_j,
        )

    def _temperature_load(
        self, load: dict[str, Any], by_id: dict[int, ElasticBeamColumn | TrussElement]
    ) -> TemperatureLoad | None:
        """A uniform temperature change of a member, with its material's α."""
        if load.get("areaId") is not None:
            self.dropped["temperature load on an area"] += 1
            return None
        element = by_id.get(int(load.get("elemId", 0)))
        if not isinstance(element, ElasticBeamColumn) or element.releases.any:
            self.dropped["temperature load on a bar or a member with releases"] += 1
            return None
        raw = next(
            (e for e in self.s3d.items("elements") if _entity_id(e, "element") == element.id), {}
        )
        alpha = _number(self.materials.get(int(raw.get("matId", 0)), {}), "alpha")
        if alpha <= 0.0:
            self.dropped["temperature load on a material without alpha"] += 1
            return None
        # α is per degree and ΔT in degrees: neither scales with the units.
        return TemperatureLoad(element_id=element.id, alpha=alpha, uniform=_number(load, "dT"))

    def _nodal_load(self, load: dict[str, Any]) -> NodalLoad | None:
        node_id = int(load.get("nodeId", 0))
        if node_id not in self.nodes:
            # PORTICO skips such a load without a word; here it is at least counted.
            self.dropped["load on a missing node"] += 1
            return None
        values = list(load.get("F") or [])
        values += [0.0] * (6 - len(values))
        forces = [
            float(values[k] or 0.0) * (self.scale.force if k < 3 else self.scale.moment)
            for k in range(6)
        ]
        if self.ndm == 2:
            if any(forces[k] for k in range(6) if k not in _DOF_2D):
                self.dropped["out-of-plane nodal load component"] += 1
            forces = [f if k in _DOF_2D else 0.0 for k, f in enumerate(forces)]
        return NodalLoad(node_id=node_id, forces=tuple(forces))  # type: ignore[arg-type]

    def build_cases(self) -> tuple[list[Any], list[PlainLoadPattern], list[StaticCase]]:
        series = [LinearTimeSeries(id=1, name="Linear")]
        by_id = {el.id: el for el in self.elements}
        patterns: list[PlainLoadPattern] = []
        cases: list[StaticCase] = []
        imposed = self.imposed_displacements()
        imposed_id: int | None = None
        static = [c for c in self.s3d.items("loadCases") if c.get("type", "static") == "static"]
        others = [c for c in self.s3d.items("loadCases") if c not in static]
        for case in others:
            self.dropped[f"{case.get('type')} load case"] += 1
        used = {_entity_id(case, "load case") for case in static}
        if imposed:
            imposed_id = max(used, default=0) + 1
        for case in static:
            case_id = _entity_id(case, "load case")
            name = str(case.get("name") or f"LC{case_id}")
            pattern = PlainLoadPattern(
                id=case_id,
                name=name,
                time_series_id=1,
                self_weight=1.0 if case.get("selfWeight") else 0.0,
            )
            for load in case.get("loads") or []:
                kind = load.get("type")
                if kind == "nodal":
                    nodal = self._nodal_load(load)
                    if nodal is not None:
                        pattern.nodal_loads.append(nodal)
                elif kind == "dist":
                    built = self._element_load(load, by_id)
                    if isinstance(built, UniformElementLoad):
                        pattern.element_loads.append(built)
                    elif built is not None:
                        pattern.distributed_loads.append(built)
                elif kind == "temp":
                    thermal = self._temperature_load(load, by_id)
                    if thermal is not None:
                        pattern.temperature_loads.append(thermal)
                else:
                    self.dropped[f"{kind} load"] += 1
            patterns.append(pattern)
            ids = [case_id] if imposed_id is None else [case_id, imposed_id]
            cases.append(self._static_case(case_id, name, ids))
        if imposed_id is not None:
            # PORTICO imposes a node's prescribed displacement in every static case.
            patterns.append(
                PlainLoadPattern(
                    id=imposed_id,
                    name="Prescribed displacements",
                    time_series_id=1,
                    imposed_displacements=imposed,
                )
            )
            if not static:
                # A model loaded only by its prescribed displacements (a patch test)
                # still gets the static case PORTICO would solve.
                cases.append(
                    self._static_case(imposed_id, "Prescribed displacements", [imposed_id])
                )
        return series, patterns, cases

    def _static_case(self, case_id: int, name: str, pattern_ids: list[int]) -> StaticCase:
        """A linear static case, or a Newton one when a bar goes slack on one side."""
        if not self.one_way:
            return StaticCase(id=case_id, name=name, pattern_ids=pattern_ids)
        return StaticCase(
            id=case_id,
            name=name,
            pattern_ids=pattern_ids,
            algorithm="Newton",
            tolerance=1e-10,
            max_iter=50,
        )

    def build_combinations(self, case_ids: set[int]) -> list[LoadCombination]:
        combinations: list[LoadCombination] = []
        for item in self.s3d.items("combinations"):
            combo_id = _entity_id(item, "combination")
            name = str(item.get("name") or f"Combo {combo_id}")
            terms: list[CombinationTerm] = []
            for factor in item.get("factors") or []:
                ref = int(factor.get("lcId", 0))
                if ref not in case_ids:
                    self.dropped["combination term on a case not imported"] += 1
                    continue
                terms.append(CombinationTerm(ref_id=ref, factor=_number(factor, "factor", 1.0)))
            if not terms:
                self.dropped["empty combination"] += 1
                continue
            combinations.append(LoadCombination(id=combo_id, name=name, terms=terms))
        return combinations

    def grid(self) -> CoordinateGridSystem | None:
        grids = self.s3d.data.get("grids")
        if not isinstance(grids, dict):
            return None
        lines: dict[str, list[float]] = {}
        for axis in ("x", "y", "z"):
            values = grids.get(axis) or []
            ordinates = sorted({round(float(v) * self.scale.length, 12) for v in values})
            lines[axis] = ordinates
        if not any(lines.values()):
            return None
        return CoordinateGridSystem(
            name="Global",
            grid=GridSystem(
                x_grid_lines=make_grid_lines("X", lines["x"]),
                y_grid_lines=make_grid_lines("Y", lines["y"]),
                z_grid_lines=make_grid_lines("Z", lines["z"]),
            ),
        )

    # ── areas, diaphragms, links, mass ──
    def build_areas(self) -> None:
        """QUAD areas as ``ShellMITC4`` with an elastic plate section per material and thickness.

        Area ids follow the frame elements' (one id space in OpenSees).
        """
        areas = self.s3d.items("areas")
        if not areas:
            return
        if self.ndm == 2:
            self.dropped["area element (a 2D frame model has no plane elements)"] += len(areas)
            return
        offset = max((el.id for el in self.elements), default=0)
        keys: dict[tuple[int, float], int] = {}
        kinds: Counter[str] = Counter()
        s = self.scale
        for item in areas:
            area_id = _entity_id(item, "area")
            nodes = [int(n) for n in item.get("nodes") or []]
            kind = str(item.get("kind") or ("CST" if len(nodes) == 3 else "QUAD"))
            if kind != "QUAD" or len(nodes) != 4 or len(set(nodes)) != 4:
                self.dropped["triangular or degenerate area (no 3-node shell)"] += 1
                continue
            missing = [n for n in nodes if n not in self.nodes]
            if missing:
                raise S3dImportError(f"Area {area_id} uses missing node {missing[0]}.")
            mat_id = int(item.get("matId", 0))
            if mat_id not in self.materials:
                raise S3dImportError(f"Area {area_id} uses missing material {mat_id}.")
            thickness = _number(item, "thickness") * s.length
            key = (mat_id, round(thickness, 12))
            if key not in keys:
                mat = self.materials[mat_id]
                rho = _number(mat, "rho") * s.density
                section_id = len(self.sections) + len(keys) + 1
                keys[key] = section_id
                try:
                    self.area_sections.append(
                        ElasticMembranePlateSection(
                            id=section_id,
                            name=f"{mat.get('name') or f'Material {mat_id}'} h = {thickness:g}",
                            E=_number(mat, "E") * s.stress,
                            nu=_number(mat, "nu", 0.2),
                            h=thickness,
                            rho=rho,
                            unit_weight=rho * gravity(self.target),
                        )
                    )
                except ValidationError as exc:
                    raise S3dImportError(f"Area {area_id}: {_first_error(exc)}") from exc
            behaviour = str(item.get("behavior") or "membrane")
            kinds[behaviour] += 1
            if item.get("planeStrain"):
                self.dropped["plane-strain flag of an area (a shell is plane stress)"] += 1
            self.area_elements.append(
                ShellMITC4Element(
                    id=offset + area_id,
                    nodes=(nodes[0], nodes[1], nodes[2], nodes[3]),
                    section_id=keys[key],
                )
            )
        if self.area_elements:
            self.notes.append(
                f"{len(self.area_elements)} area(s) imported as ShellMITC4, element id = "
                f"{offset} + the area id."
            )
        for behaviour, label in (
            ("membrane", "membrane areas gain bending stiffness"),
            ("plate", "plate areas gain membrane stiffness"),
        ):
            if kinds[behaviour]:
                self.notes.append(
                    f"{kinds[behaviour]} {behaviour} area(s) became full shells: {label}, which "
                    "PORTICO's element does not have."
                )

    def build_diaphragms(self) -> list[RigidDiaphragm]:
        """Rigid floors: the master is ``masterId`` (else the first node), as in PORTICO."""
        out: list[RigidDiaphragm] = []
        items = self.s3d.items("diaphragms")
        if items and self.ndm == 2:
            self.dropped["diaphragm (2D model)"] += len(items)
            return out
        for item in items:
            diaphragm_id = _entity_id(item, "diaphragm")
            nodes = [int(n) for n in item.get("nodes") or [] if int(n) in self.nodes]
            master = int(item.get("masterId") or (nodes[0] if nodes else 0))
            constrained = tuple(n for n in nodes if n != master)
            if master not in self.nodes or not constrained:
                self.dropped["diaphragm with fewer than two nodes"] += 1
                continue
            out.append(
                RigidDiaphragm(
                    id=diaphragm_id,
                    name=str(item.get("name") or f"D{diaphragm_id}"),
                    perp_dirn=3,
                    retained_node=master,
                    constrained_nodes=constrained,
                )
            )
            mass = item.get("mass") or {}
            m = _number(mass, "m") * self.scale.mass
            if m > 0:
                # PORTICO spreads the floor mass by beam tributary; here equally, on UX and UY.
                share = m / len(nodes)
                for node_id in nodes:
                    node = self.nodes[node_id]
                    mx, my, *rest = node.mass
                    node.mass = (mx + share, my + share, *rest)  # type: ignore[assignment]
                self.notes.append(
                    f"Diaphragm {item.get('name') or diaphragm_id}: its mass was spread equally "
                    "over its nodes (PORTICO uses the tributary of the beams)."
                )
            if _number(mass, "Icm") > 0:
                self.dropped["diaphragm rotational mass Icm"] += 1
            ecc = item.get("eccentricity") or {}
            if _number(ecc, "ex") or _number(ecc, "ey"):
                self.dropped["diaphragm accidental eccentricity"] += 1
        return out

    def build_links(self) -> tuple[list[RigidLink], list[EqualDOFConstraint]]:
        """``rigid`` links as rigid links (with the lever arm), the others as equalDOF."""
        rigid: list[RigidLink] = []
        equal: list[EqualDOFConstraint] = []
        for item in self.s3d.items("links"):
            master, slave = int(item.get("master", 0)), int(item.get("slave", 0))
            if master not in self.nodes or slave not in self.nodes or master == slave:
                raise S3dImportError(f"Link {item.get('id')} needs two existing, different nodes.")
            flags = item.get("dofs") or dict.fromkeys(_DOF_NAMES, 1)
            tied = [k for k, name in enumerate(_DOF_NAMES) if flags.get(name)]
            if item.get("rigid", True):
                if tied == [0, 1, 2, 3, 4, 5]:
                    rigid.append(
                        RigidLink(kind="beam", retained_node=master, constrained_node=slave)
                    )
                    continue
                if tied == [0, 1, 2]:
                    rigid.append(
                        RigidLink(kind="bar", retained_node=master, constrained_node=slave)
                    )
                    continue
                self.dropped["rigid link on a subset of DOFs (imported as a full rigid link)"] += 1
                rigid.append(RigidLink(kind="beam", retained_node=master, constrained_node=slave))
                continue
            if self.ndm == 2:
                dofs = tuple(_DOF_2D[k] for k in tied if k in _DOF_2D)
            else:
                dofs = tuple(k + 1 for k in tied)
            if dofs:
                equal.append(
                    EqualDOFConstraint(retained_node=master, constrained_node=slave, dofs=dofs)
                )
        return rigid, equal

    def mass_source(self, case_ids: set[int]) -> MassSource | None:
        source = self.s3d.data.get("massSource")
        if not isinstance(source, dict) or not source.get("enabled"):
            return None
        patterns = []
        for entry in source.get("entries") or []:
            ref = int(entry.get("lcId", 0))
            if ref not in case_ids:
                self.dropped["mass source entry on a case not imported"] += 1
                continue
            patterns.append(MassSourcePattern(pattern_id=ref, factor=_number(entry, "factor", 1.0)))
        # PORTICO puts the weight's mass on UX, UY and UZ of every node it lands on.
        return MassSource(
            element_self_mass=bool(source.get("selfWeight")),
            patterns=patterns,
            include_vertical=True,
            lump_at_diaphragms=False,
        )


def _symmetric(section: dict[str, Any]) -> bool:
    """Same stiffness about local y and z: the turn of the member does not matter."""
    return math.isclose(_number(section, "Iz"), _number(section, "Iy"), rel_tol=1e-9) and (
        math.isclose(_number(section, "Avy"), _number(section, "Avz"), rel_tol=1e-9)
    )


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    where = ".".join(str(part) for part in error.get("loc", ()))
    return f"{where}: {error.get('msg')}" if where else str(error.get("msg"))


def s3d_to_project(
    s3d: S3dFile,
    *,
    units: UnitSystem | None = None,
    source_units: str | None = None,
) -> S3dImport:
    """Translate a parsed PORTICO file into a new project in ``units``.

    ``source_units`` overrides the file's own label (for a file whose label is
    missing or wrong); ``units`` is the project's system, by default the one
    closest to the file's (:data:`DEFAULT_TARGET`).

    Raises:
        S3dImportError: on an unknown unit label, a broken reference or a value
            the project model refuses.
    """
    source = source_units or s3d.units
    target = units or DEFAULT_TARGET.get(source, UnitSystem.SI_M_N)
    translator = _Translator(s3d, target, source)
    translator.build_nodes()
    translator.build_elements(translator.trapezoidal_elements())
    translator.build_areas()
    diaphragms = translator.build_diaphragms()
    rigid_links, equal_dofs = translator.build_links()
    series, patterns, cases = translator.build_cases()
    case_ids = {case.id for case in cases}
    combinations = translator.build_combinations(case_ids)
    mass_source = translator.mass_source(case_ids)
    if translator.one_way:
        translator.notes.append(
            f"{translator.one_way} cable or compression-only member(s) became trusses that go "
            "slack on the other side; the static cases run with Newton, and their "
            "combinations are no longer an exact superposition."
        )
    if translator.oblique:
        translator.notes.append(
            f"{translator.oblique} member(s) with a non-symmetric section have local axes "
            "turned by an angle other than 90° from PORTICO's; their section was imported "
            "with the nearest principal orientation."
        )
    if SOURCE_UNITS[source][0] != 1.0 and any(
        case.get("selfWeight") for case in s3d.items("loadCases")
    ):
        translator.notes.append(
            f"Self weight is the density times g = {gravity(target):g} in the project's "
            f"units. PORTICO multiplies by 9.80665 whatever the units, so its own self "
            f"weight of this {source} model differs."
        )
    grid = translator.grid()
    try:
        project = Project(
            meta=ProjectMeta(
                name=s3d.path.stem,
                description=f"Imported from PORTICO ({s3d.path.name}, {source}).",
                units=target,
            ),
            ndm=translator.ndm,
            ndf=3 if translator.ndm == 2 else 6,
            coord_systems=[grid if grid is not None else default_global_system()],
            nodes=list(translator.nodes.values()),
            materials=[*translator.truss_materials],
            sections=[*translator.sections, *translator.area_sections],
            elements=[*translator.elements, *translator.area_elements],
            diaphragms=diaphragms,
            rigid_links=rigid_links,
            mp_constraints=equal_dofs,
            mass_source=mass_source,
            time_series=series,
            load_patterns=[*patterns],
            analyses=[*cases],
            combinations=combinations,
        )
        project.validate_references()
    except (ValidationError, ValueError) as exc:
        detail = _first_error(exc) if isinstance(exc, ValidationError) else str(exc)
        raise S3dImportError(f"{s3d.path.name} does not make a valid project: {detail}") from exc
    return S3dImport(
        project=project,
        source_units=source,
        scale=translator.scale,
        notes=translator.notes,
        dropped=translator.dropped,
    )


def import_s3d(
    path: str | Path, *, units: UnitSystem | None = None, source_units: str | None = None
) -> S3dImport:
    """:func:`read_s3d` then :func:`s3d_to_project`."""
    return s3d_to_project(read_s3d(path), units=units, source_units=source_units)
