"""Read and write the SAP2000 text format (``.s2k`` / ``.$2k``) for a frame model.

SAP2000 is a trademark of Computers and Structures, Inc. (CSI); OpenSees Studio
is not affiliated with CSI. This module is written from the publicly described
shape of the text format alone — plain tables of ``Key=Value`` records — without
any CSI software, library or documentation text, and it has not been checked
against SAP2000 itself.

The file. A table starts with ``TABLE:  "NAME"``; each following line is one
record of ``Key=Value`` pairs (a value with spaces is double-quoted), a line
ending in ``" _"`` continues on the next one, and ``END TABLE DATA`` ends the
file. Anything else (the ``File ... was saved`` banner) is ignored.

What is read: units (``PROGRAM CONTROL``), the active DOFs (a frame in the X-Z
plane whose joints only move in it is a 2D model), grid lines, joints and their
restraints, added joint masses and support springs, frames and their sections and
materials (rectangular, I, pipe, tube or general properties; another shape by its
properties), local-axis angles, end releases and partial fixity, per-frame
property modifiers, rigid diaphragms, load patterns
with their self-weight multiplier, joint forces, distributed and point frame
loads, temperature loads, ground displacements on supports, frame added mass,
linear static load cases (with the preload a case names), eigen modal cases,
response-spectrum cases with their tabulated spectra, combinations, and four-node
thin or thick shells with their sections. Every other table is counted in the
import report, never dropped silently.

Diagnostics. A record the reader cannot use names the table and the line it came
from (``Frame 3 (CONNECTIVITY - FRAME, line 57): joint 'C' is not defined``), and
a line inside a table that is not a ``Key=Value`` record is counted in the import
report instead of disappearing. A file with no joints is refused rather than
opened as an empty project, and every failure reaches the caller as
:class:`Sap2000TextError`: a damaged file must not take the window down.

Units. A file is in its ``CurrUnits`` (``"KN, m, C"``); the project gets the
nearest of our systems (or the one the caller picks) and every number is scaled
by its dimension with :class:`~opensees_studio.services.s3d_import.UnitScale`.

Local axes. SAP2000 gives a frame's local 2 the upward direction in the vertical
plane of the member (global +X for a vertical one), turned by the member's
local-axis angle, and 3 = 1 × 2. OpenSees picks ``vecxz`` from
:mod:`core.geometry.local_axes`. Per member the importer finds which OpenSees
axis SAP2000's local 2 lies on and maps ``I33``/``I22``, ``AS2``/``AS3`` and the
M2/M3 releases onto ``Iz``/``Iy``, ``As2``/``As3`` and our M2/M3 (about local y
and z). Frame loads are turned into vectors and projected onto the OpenSees
axes, so they keep their direction whatever the turn. The writer goes the other
way: every section is written with SAP2000's local 2 on OpenSees' local z (local
y in 2D) and each member gets the angle that makes that true.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np
from pydantic import ValidationError

from opensees_studio.core.analysis import (
    AnalysisCase,
    ModalCase,
    ResponseSpectrumCase,
    StaticCase,
)
from opensees_studio.core.combinations import CombinationTerm, CombinationType, LoadCombination
from opensees_studio.core.constraints import RigidDiaphragm
from opensees_studio.core.diaphragms import IN_PLANE_SLOTS, constrained_node_ids
from opensees_studio.core.geometry.elements import ElasticBeamColumn, ShellMITC4Element
from opensees_studio.core.geometry.frame_options import (
    EndRelease,
    FrameModifiers,
    FrameReleases,
)
from opensees_studio.core.geometry.grid import (
    CoordinateGridSystem,
    GridLine,
    GridSystem,
    default_global_system,
)
from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.geometry.node import Node
from opensees_studio.core.loads import (
    ImposedDisplacement,
    LinearTimeSeries,
    NodalLoad,
    PlainLoadPattern,
    PointElementLoad,
    ResponseSpectrum,
    TemperatureLoad,
    TrapezoidalElementLoad,
    UniformElementLoad,
)
from opensees_studio.core.project import Project, ProjectMeta
from opensees_studio.core.sections import (
    ElasticMembranePlateSection,
    ElasticSection,
    NonprismaticSection,
    NonprismaticSegment,
    PipeShape,
    RectShape,
    SectionShape,
    TubeShape,
    WideFlangeShape,
)
from opensees_studio.core.units import UnitSystem, gravity, metres_per_unit, newtons_per_unit
from opensees_studio.diagnostics.performance import perf
from opensees_studio.services.nonprismatic import materialize_nonprismatic
from opensees_studio.services.s3d_import import UnitScale

_KIP_N = 4448.2216152605
_LBF_N = 4.4482216152605
_KGF_N = 9.80665

#: Force unit of ``CurrUnits`` (lower case) → newtons.
FORCE_UNITS: dict[str, float] = {
    "lb": _LBF_N,
    "kip": _KIP_N,
    "n": 1.0,
    "kn": 1e3,
    "kgf": _KGF_N,
    "tonf": 1e3 * _KGF_N,
}

#: Length unit of ``CurrUnits`` (lower case) → metres.
LENGTH_UNITS: dict[str, float] = {
    "in": 0.0254,
    "ft": 0.3048,
    "mm": 1e-3,
    "cm": 1e-2,
    "m": 1.0,
}

#: The project system a file opens in, by its length unit (US forces get the US systems).
_DEFAULT_TARGET: dict[str, UnitSystem] = {
    "in": UnitSystem.US_IN_KIP,
    "ft": UnitSystem.US_FT_KIP,
    "mm": UnitSystem.SI_MM_N,
    "cm": UnitSystem.SI_M_N,
    "m": UnitSystem.SI_M_N,
}

#: ``CurrUnits`` the writer declares for each project system.
_WRITE_UNITS: dict[UnitSystem, str] = {
    UnitSystem.SI_M_N: "N, m, C",
    UnitSystem.SI_MM_N: "N, mm, C",
    UnitSystem.US_FT_KIP: "Kip, ft, F",
    UnitSystem.US_IN_KIP: "Kip, in, F",
}

#: What a file without a ``PROGRAM CONTROL`` table is taken to be in.
DEFAULT_UNITS = "KN, m, C"

#: Tables read by the importer (the rest are reported).
READ_TABLES: frozenset[str] = frozenset(
    {
        "PROGRAM CONTROL",
        "ACTIVE DEGREES OF FREEDOM",
        "GRID LINES",
        "JOINT COORDINATES",
        "JOINT RESTRAINT ASSIGNMENTS",
        "JOINT ADDED MASS ASSIGNMENTS",
        "JOINT SPRING ASSIGNMENTS 1 - UNCOUPLED",
        "CONSTRAINT DEFINITIONS - DIAPHRAGM",
        "JOINT CONSTRAINT ASSIGNMENTS",
        "MASS SOURCE",
        "CONNECTIVITY - FRAME",
        "FRAME SECTION ASSIGNMENTS",
        "FRAME PROPERTY MODIFIERS",
        "FRAME LOCAL AXES ASSIGNMENTS 1 - TYPICAL",
        "FRAME RELEASE ASSIGNMENTS 1 - GENERAL",
        "FRAME RELEASE ASSIGNMENTS 2 - PARTIAL FIXITY",
        "MATERIAL PROPERTIES 01 - GENERAL",
        "MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES",
        "FRAME SECTION PROPERTIES 01 - GENERAL",
        "FRAME SECTION PROPERTIES 05 - NONPRISMATIC",
        "LOAD PATTERN DEFINITIONS",
        "JOINT LOADS - FORCE",
        "JOINT LOADS - GROUND DISPLACEMENT",
        "JOINT PATTERN ASSIGNMENTS",
        "FRAME LOADS - DISTRIBUTED",
        "FRAME LOADS - POINT",
        "FRAME LOADS - TEMPERATURE",
        "FRAME ADDED MASS ASSIGNMENTS",
        "LOAD CASE DEFINITIONS",
        "CASE - STATIC 1 - LOAD ASSIGNMENTS",
        "CASE - MODAL 1 - GENERAL",
        "FUNCTION - RESPONSE SPECTRUM - USER",
        "CASE - RESPONSE SPECTRUM 1 - GENERAL",
        "CASE - RESPONSE SPECTRUM 2 - LOAD ASSIGNMENTS",
        "COMBINATION DEFINITIONS",
        "CONNECTIVITY - AREA",
        "AREA SECTION ASSIGNMENTS",
        "AREA SECTION PROPERTIES",
    }
)

_DOF_KEYS = ("U1", "U2", "U3", "R1", "R2", "R3")
_FORCE_KEYS = ("F1", "F2", "F3", "M1", "M2", "M3")
#: A response-spectrum load assignment's global direction as a DOF number.
_DIRECTIONS: dict[str, int] = {key: index for index, key in enumerate(_DOF_KEYS, start=1)}
#: A joint mass record: the three translations, then the three mass moments of inertia.
_MASS_KEYS = ("Mass1", "Mass2", "Mass3", "MMI1", "MMI2", "MMI3")
#: A joint spring record: the three translations to ground, then the three rotations.
_SPRING_KEYS = ("U1", "U2", "U3", "R1", "R2", "R3")
#: Storage slots a 2D (X-Z) model keeps: Ux, Uz, Ry (see core.plane).
_SLOTS_2D = (0, 2, 4)

#: Cosine above which two local axes count as the same direction (about 0.06°).
_ALIGNED = 1.0 - 1e-6
#: SAP2000 calls a member vertical when the sine of its angle to Z is below this.
_VERTICAL_SINE = 1e-3

_COMBO_TYPES = {
    "linear add": "LinearAdd",
    "envelope": "Envelope",
    "abs add": "AbsoluteAdd",
    "absolute add": "AbsoluteAdd",
    "srss": "SRSS",
}
_COMBO_NAMES = {
    "LinearAdd": "Linear Add",
    "Envelope": "Envelope",
    "AbsoluteAdd": "Abs Add",
    "SRSS": "SRSS",
}


class Sap2000TextError(RuntimeError):
    """The file cannot be read as SAP2000 text, or does not make a valid project."""


# ──────────────────────────── units ────────────────────────────
def parse_units(text: str) -> tuple[str, str]:
    """``"KN, m, C"`` → ``("kn", "m")``.

    Raises:
        Sap2000TextError: on a force or length unit this module does not know.
    """
    parts = [p.strip().lower() for p in text.split(",")]
    if len(parts) < 2 or parts[0] not in FORCE_UNITS or parts[1] not in LENGTH_UNITS:
        raise Sap2000TextError(
            f"Unknown units {text!r}: the force must be one of lb, Kip, N, KN, Kgf, Tonf and "
            "the length one of in, ft, mm, cm, m."
        )
    return parts[0], parts[1]


def unit_scale(units: str, target: UnitSystem) -> UnitScale:
    """Factors from the file's ``CurrUnits`` to the project system ``target``."""
    force, length = parse_units(units)
    return UnitScale(
        length=LENGTH_UNITS[length] / metres_per_unit(target),
        force=FORCE_UNITS[force] / newtons_per_unit(target),
    )


def default_target(units: str) -> UnitSystem:
    """The project system closest to the file's units."""
    force, length = parse_units(units)
    if length in ("m", "cm") and force in ("lb", "kip"):
        return UnitSystem.US_FT_KIP
    if length in ("in", "ft") and force not in ("lb", "kip"):
        return UnitSystem.SI_M_N
    return _DEFAULT_TARGET[length]


# ──────────────────────────── reading ────────────────────────────
_TABLE = re.compile(r'^TABLE:\s*"(?P<name>[^"]*)"\s*$', re.IGNORECASE)
_PAIR = re.compile(r'([^\s=]+)=("(?P<quoted>[^"]*)"|(?P<bare>\S*))')


class S2kRow(dict[str, str]):
    """One record of a table, and the line of the file it was read from.

    A plain ``dict`` so every reader that already took records keeps working;
    the line is what lets an error say *where* the record is, not only which
    joint or frame it named.
    """

    line: int

    def __init__(self, values: dict[str, str], line: int) -> None:
        super().__init__(values)
        self.line = line


def parse_tables(
    text: str, *, malformed: list[tuple[int, str]] | None = None
) -> dict[str, list[S2kRow]]:
    """Split SAP2000 text into ``{table name: [record, ...]}``, records as ``{key: value}``.

    ``malformed``, when given, is filled with the ``(line, text)`` of every line
    inside a table that is not a ``Key=Value`` record (or whose quotes do not
    balance): a file that is not SAP2000 text then says so instead of importing
    as an empty model.
    """
    tables: dict[str, list[S2kRow]] = {}
    current: list[S2kRow] | None = None
    pending = ""
    pending_line = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if line.endswith(" _"):
            pending_line = pending_line or number
            pending += line[:-2] + " "
            continue
        line = (pending + line).strip()
        if pending_line:  # a continued record is reported where it started
            number = pending_line
        pending_line = 0
        pending = ""
        if not line or line.startswith(("$", ";")):
            continue
        match = _TABLE.match(line)
        if match:
            current = tables.setdefault(match["name"].strip().upper(), [])
            continue
        if line.upper().startswith("END TABLE DATA"):
            break
        if current is None:
            continue  # the "File ... was saved on ..." banner
        record = {
            m.group(1): m.group("quoted") if m.group("quoted") is not None else m.group("bare")
            for m in _PAIR.finditer(line)
        }
        if record:
            current.append(S2kRow(record, number))
        if malformed is not None and (not record or line.count('"') % 2):
            malformed.append((number, line))
    return tables


@dataclass(frozen=True)
class S2kFile:
    """A SAP2000 text file, split into tables but not yet translated."""

    path: Path
    tables: dict[str, list[S2kRow]]
    malformed: tuple[tuple[int, str], ...] = ()
    """``(line, text)`` of every line inside a table that is not a record."""

    def rows(self, table: str) -> list[S2kRow]:
        return self.tables.get(table, [])

    @property
    def units(self) -> str:
        """``CurrUnits`` of the file (:data:`DEFAULT_UNITS` when it has none)."""
        for row in self.rows("PROGRAM CONTROL"):
            if row.get("CurrUnits"):
                return row["CurrUnits"]
        return DEFAULT_UNITS

    @property
    def has_units(self) -> bool:
        return any(row.get("CurrUnits") for row in self.rows("PROGRAM CONTROL"))

    def unsupported(self) -> dict[str, int]:
        """Tables the importer does not read, with their number of records."""
        return {name: len(rows) for name, rows in self.tables.items() if name not in READ_TABLES}


def read_s2k(path: str | Path) -> S2kFile:
    """Read ``path`` and split it into tables.

    Raises:
        Sap2000TextError: if the file is missing, unreadable or has no table.
    """
    source = Path(path)
    if not source.is_file():
        raise Sap2000TextError(f"No such file: {source}")
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise Sap2000TextError(f"{source.name} cannot be read ({exc}).") from exc
    with perf.span("s2k.read"):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        malformed: list[tuple[int, str]] = []
        tables = parse_tables(text, malformed=malformed)
        if not tables:
            raise Sap2000TextError(f"{source.name} has no SAP2000 table (no 'TABLE:' line).")
        return S2kFile(path=source, tables=tables, malformed=tuple(malformed))


# ──────────────────────────── local axes ────────────────────────────
def sap_local_axes(
    p_i: np.ndarray, p_j: np.ndarray, angle: float = 0.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """SAP2000's frame triad ``(1, 2, 3)``: 2 up in the member's vertical plane, turned by ``angle``°.

    A vertical member has 2 along global +X. The angle turns 2 and 3 about 1.
    """
    e1 = (p_j - p_i) / float(np.linalg.norm(p_j - p_i))
    up = np.array([0.0, 0.0, 1.0])
    if float(np.linalg.norm(np.cross(e1, up))) < _VERTICAL_SINE:
        e2 = np.array([1.0, 0.0, 0.0])
    else:
        e2 = up - float(np.dot(up, e1)) * e1
    e2 = e2 - float(np.dot(e2, e1)) * e1
    e2 /= float(np.linalg.norm(e2))
    e3 = np.cross(e1, e2)
    if angle:
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        e2, e3 = c * e2 + s * e3, -s * e2 + c * e3
    return e1, e2, e3


@dataclass(frozen=True)
class _Orientation:
    """Where SAP2000's local 2 and 3 of one member land on OpenSees' y and z."""

    two_on_y: bool
    """SAP2000's 2 is (±) OpenSees' y: I33 → Iz, AS2 → As2, M3 → M3. Else 2 is on z."""
    exact: bool
    """The triads agree up to that swap and signs; False for any other turn."""


def _orientation(ndm: int, p_i: np.ndarray, p_j: np.ndarray, angle: float) -> _Orientation:
    ours = frame_local_axes(ndm, p_i.tolist(), p_j.tolist())
    assert ours is not None  # zero-length members are refused before
    _, e2, _ = sap_local_axes(p_i, p_j, angle)
    on_y, on_z = abs(float(np.dot(e2, ours[1]))), abs(float(np.dot(e2, ours[2])))
    return _Orientation(two_on_y=on_y > on_z, exact=max(on_y, on_z) >= _ALIGNED)


def writer_angle(ndm: int, p_i: np.ndarray, p_j: np.ndarray) -> float:
    """The local-axis angle (degrees) that puts SAP2000's 2 on OpenSees' z (y in 2D)."""
    ours = frame_local_axes(ndm, p_i.tolist(), p_j.tolist())
    assert ours is not None
    target = ours[1] if ndm == 2 else ours[2]
    _, e2, e3 = sap_local_axes(p_i, p_j)
    angle = math.degrees(math.atan2(float(np.dot(target, e3)), float(np.dot(target, e2))))
    rounded = round(angle, 9)
    return 0.0 if rounded in (0.0, -0.0) else rounded


# ──────────────────────────── values ────────────────────────────
def _number(row: dict[str, str], key: str, default: float = 0.0, *, where: str = "") -> float:
    value = row.get(key)
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except ValueError:
        raise Sap2000TextError(f"{where}{key} must be a number, not {value!r}.") from None
    if not math.isfinite(number):
        raise Sap2000TextError(f"{where}{key} must be finite, not {value!r}.")
    return number


def _yes(row: dict[str, str], key: str) -> bool:
    return row.get(key, "").strip().lower() in ("yes", "true", "1")


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    where = ".".join(str(part) for part in error.get("loc", ()))
    return f"{where}: {error.get('msg')}" if where else str(error.get("msg"))


def _at(table: str, row: dict[str, str]) -> str:
    """Where a record came from, for an error message: ``JOINT COORDINATES, line 14``."""
    line: int = getattr(row, "line", 0)
    return f"{table}, line {line}" if line else table


def _by_frame(rows: list[S2kRow]) -> dict[str, S2kRow]:
    return {row.get("Frame", ""): row for row in rows}


def _ids(names: list[str]) -> tuple[dict[str, int], bool]:
    """Ids for object names: the names themselves when they are distinct positive integers."""
    try:
        numbered = {name: int(name) for name in names if name.isdigit()}
    except ValueError:
        # ``isdigit`` is true for characters ``int`` refuses (``²``), and CPython
        # caps integer conversion at 4 300 digits: a damaged name is renamed,
        # it must not crash the import.
        numbered = {}
    if (
        len(numbered) == len(names)
        and len(set(numbered.values())) == len(names)
        and all(value > 0 for value in numbered.values())
    ):
        return numbered, False
    return {name: k for k, name in enumerate(names, start=1)}, True


def _rect_props(d: float, b: float) -> dict[str, float]:
    long, short = max(d, b), min(d, b)
    j = long * short**3 * (1 / 3 - 0.21 * short / long * (1 - short**4 / (12 * long**4)))
    return {
        "A": d * b,
        "I33": b * d**3 / 12,
        "I22": d * b**3 / 12,
        "J": j,
        "AS2": 5 / 6 * d * b,
        "AS3": 5 / 6 * d * b,
    }


def _shape_props(shape: str, row: dict[str, str], where: str) -> dict[str, float] | None:
    """Closed-form properties from the dimensions, for a section without its property columns."""
    t3, t2 = _number(row, "t3", where=where), _number(row, "t2", where=where)
    tf, tw = _number(row, "tf", where=where), _number(row, "tw", where=where)
    if shape == "rectangular" and t3 > 0 and t2 > 0:
        return _rect_props(t3, t2)
    if shape == "pipe" and t3 > 0 and 0 < tw < t3 / 2:
        r_o, r_i = t3 / 2, t3 / 2 - tw
        i = math.pi / 4 * (r_o**4 - r_i**4)
        a = math.pi * (r_o**2 - r_i**2)
        return {"A": a, "I33": i, "I22": i, "J": 2 * i, "AS2": a / 2, "AS3": a / 2}
    if shape == "box/tube" and t3 > 2 * tf > 0 and t2 > 2 * tw > 0:
        a = t3 * t2 - (t3 - 2 * tf) * (t2 - 2 * tw)
        i33 = (t2 * t3**3 - (t2 - 2 * tw) * (t3 - 2 * tf) ** 3) / 12
        i22 = (t3 * t2**3 - (t3 - 2 * tf) * (t2 - 2 * tw) ** 3) / 12
        area_mid = (t3 - tf) * (t2 - tw)
        j = 4 * area_mid**2 / (2 * (t3 - tf) / tw + 2 * (t2 - tw) / tf)
        return {"A": a, "I33": i33, "I22": i22, "J": j, "AS2": 2 * t3 * tw, "AS3": 2 * t2 * tf}
    if shape == "i/wide flange" and t3 > 2 * tf > 0 and t2 > 0 and tw > 0:
        t2b = _number(row, "t2b", t2, where=where) or t2
        tfb = _number(row, "tfb", tf, where=where) or tf
        if not (math.isclose(t2b, t2) and math.isclose(tfb, tf)):
            return None
        hw = t3 - 2 * tf
        a = 2 * t2 * tf + hw * tw
        i33 = (t2 * t3**3 - (t2 - tw) * hw**3) / 12
        i22 = (2 * tf * t2**3 + hw * tw**3) / 12
        j = (2 * t2 * tf**3 + (t3 - tf) * tw**3) / 3
        return {"A": a, "I33": i33, "I22": i22, "J": j, "AS2": t3 * tw, "AS3": 5 / 3 * t2 * tf}
    return None


def _shape_hint(shape: str, row: dict[str, str], s: float) -> SectionShape | None:
    """The drawing hint of a SAP2000 shape, its depth (t3) along SAP2000's local 2."""
    t3, t2 = _number(row, "t3") * s, _number(row, "t2") * s
    tf, tw = _number(row, "tf") * s, _number(row, "tw") * s
    try:
        if shape == "rectangular":
            return RectShape(d=t3, b=t2)
        if shape == "pipe" and tw < t3 / 2:
            return PipeShape(od=t3, t=tw)
        if shape == "box/tube" and math.isclose(tf, tw):
            return TubeShape(d=t3, b=t2, t=tf)
        if shape == "i/wide flange":
            t2b, tfb = _number(row, "t2b", t2 / s) * s, _number(row, "tfb", tf / s) * s
            if math.isclose(t2b, t2) and math.isclose(tfb, tf):
                return WideFlangeShape(d=t3, bf=t2, tw=tw, tf=tf)
    except ValidationError:
        return None
    return None


# ──────────────────────────── translation ────────────────────────────
@dataclass
class Sap2000Import:
    """The project an import produced, the factors it used and what it left out."""

    project: Project
    source_units: str
    scale: UnitScale
    notes: list[str] = field(default_factory=list)
    dropped: Counter[str] = field(default_factory=Counter)
    unsupported_tables: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        project = self.project
        shells = sum(isinstance(e, ShellMITC4Element) for e in project.elements)
        text = (
            f"{len(project.nodes)} joint(s), {len(project.elements) - shells} frame(s), "
            f"{shells} shell(s), {len(project.sections)} section(s), "
            f"{len(project.load_patterns)} load pattern(s), "
            f"{len(project.analyses)} analysis case(s), {len(project.combinations)} combination(s)."
        )
        if self.dropped:
            items = ", ".join(f"{count} {what}" for what, count in sorted(self.dropped.items()))
            text += f" Not imported: {items}."
        if self.unsupported_tables:
            tables = ", ".join(
                f"{name} ({rows})" for name, rows in sorted(self.unsupported_tables.items())
            )
            text += f" Tables not read: {tables}."
        return text


@dataclass
class _Material:
    name: str
    e: float
    g: float
    nu: float
    weight: float  # per volume, project units
    mass: float  # per volume, project units
    alpha: float  # coefficient of thermal expansion, 1/degree


class _Translator:
    def __init__(
        self,
        s2k: S2kFile,
        target: UnitSystem,
        units: str,
        *,
        subdivisions: int = 12,
    ) -> None:
        self.s2k = s2k
        self.target = target
        self.scale = unit_scale(units, target)
        self.subdivisions = max(12, min(200, int(subdivisions)))
        self.notes: list[str] = []
        self.dropped: Counter[str] = Counter()
        self.ndm = 2 if self._is_planar() else 3
        self.points: dict[str, np.ndarray] = {}
        self.node_ids: dict[str, int] = {}
        self.nodes: list[Node] = []
        self.materials: dict[str, _Material] = {}
        self.frame_sections: dict[str, dict[str, str]] = {}
        #: A nonprismatic section's first segment names the section at its I end.
        self.nonprismatic: dict[str, str] = {}
        self._nonprismatic_rows: dict[str, list[S2kRow]] = {}
        self._nonprismatic_templates: dict[tuple[Any, ...], tuple[int, float]] = {}
        self._zero_torsion: set[str] = set()
        self._shapes_reported: set[str] = set()
        self._release_rows = _by_frame(s2k.rows("FRAME RELEASE ASSIGNMENTS 1 - GENERAL"))
        self._partial_rows = _by_frame(s2k.rows("FRAME RELEASE ASSIGNMENTS 2 - PARTIAL FIXITY"))
        self._frame_modifier_rows = _by_frame(s2k.rows("FRAME PROPERTY MODIFIERS"))
        self.sections: list[ElasticSection | ElasticMembranePlateSection | NonprismaticSection] = []
        self._section_keys: dict[tuple[Any, ...], int] = {}
        self.frames: dict[str, ElasticBeamColumn] = {}
        self.frame_ends: dict[str, tuple[str, str]] = {}
        self.angles: dict[str, float] = {}
        #: Per frame: the thermal expansion coefficient of its material and any added mass.
        self._frame_alpha: dict[str, float] = {}
        self._added_mass: dict[str, float] = {}
        self._added_mass_frames = 0
        #: Nonprismatic frames whose shear-area property modifiers are ignored.
        self._nonprismatic_shear_modifiers = 0
        #: ``(pattern, joint) -> value`` of the joint patterns a temperature load varies with.
        self._joint_patterns: dict[tuple[str, str], float] = {}
        self.shells: list[ShellMITC4Element] = []
        self.diaphragms: list[RigidDiaphragm] = []
        self._diaphragm_defs = {
            row.get("Name", ""): row
            for row in s2k.rows("CONSTRAINT DEFINITIONS - DIAPHRAGM")
            if row.get("Name")
        }
        self._constraint_joints: dict[str, list[str]] = {}
        self._non_diaphragm_constraints = 0
        for row in s2k.rows("JOINT CONSTRAINT ASSIGNMENTS"):
            constraint = row.get("Constraint", "")
            joint = row.get("Joint", "")
            if not constraint or not joint:
                continue
            if constraint in self._diaphragm_defs:
                self._constraint_joints.setdefault(constraint, []).append(joint)
            else:
                self._non_diaphragm_constraints += 1
        self.spectra: list[ResponseSpectrum] = []
        self._spectrum_ids: dict[tuple[str, float, float], int] = {}
        self._zero_period: set[str] = set()
        self.oblique = 0
        #: A mass source that excludes added masses makes those rows inert, as in SAP2000.
        self._added_masses = all(_yes(row, "Masses") for row in s2k.rows("MASS SOURCE"))
        #: A joint local system that is not global: masses and springs cannot be rotated here.
        self._rotated_joint_axes = any(
            rows for name, rows in s2k.tables.items() if name.startswith("JOINT LOCAL AXES")
        )

    # ── model kind ──
    def _is_planar(self) -> bool:
        """A frame in the X-Z plane whose joints move only in it is a 2D model."""
        dofs = self.s2k.rows("ACTIVE DEGREES OF FREEDOM")
        if not dofs:
            return False
        row = dofs[0]
        planar = all(_yes(row, k) for k in ("UX", "UZ", "RY")) and not any(
            _yes(row, k) for k in ("UY", "RX", "RZ")
        )
        if not planar:
            return False
        for joint in self.s2k.rows("JOINT COORDINATES"):
            if abs(self._coords(joint)[1]) > 1e-9:
                return False
        return True

    # ── joints ──
    def _coords(self, row: dict[str, str]) -> tuple[float, float, float]:
        where = f"Joint {row.get('Joint')} ({_at('JOINT COORDINATES', row)}): "
        if "GlobalX" in row:
            return tuple(_number(row, k, where=where) for k in ("GlobalX", "GlobalY", "GlobalZ"))  # type: ignore[return-value]
        system = row.get("CoordSys", "GLOBAL").upper()
        kind = row.get("CoordType", "Cartesian").lower()
        if system != "GLOBAL":
            raise Sap2000TextError(
                f"{where}coordinates in system {system!r} without GlobalX/Y/Z columns."
            )
        r, y, z = (_number(row, k, where=where) for k in ("XorR", "Y", "Z"))
        if kind == "cartesian":
            return (r, y, z)
        if kind == "cylindrical":
            theta = math.radians(_number(row, "T", where=where))
            return (r * math.cos(theta), r * math.sin(theta), z)
        raise Sap2000TextError(f"{where}{kind} coordinates without GlobalX/Y/Z columns.")

    def build_joints(self) -> None:
        rows = self.s2k.rows("JOINT COORDINATES")
        names = [row.get("Joint", "") for row in rows]
        if len(set(names)) != len(names):
            raise Sap2000TextError("A joint name appears twice in JOINT COORDINATES.")
        self.node_ids, renamed = _ids(names)
        if renamed:
            self.notes.append(
                "Joint names are not all positive integers: numbered 1… in file order."
            )
        restraints: dict[str, list[bool]] = {}
        for row in self.s2k.rows("JOINT RESTRAINT ASSIGNMENTS"):
            restraints[row.get("Joint", "")] = [_yes(row, k) for k in _DOF_KEYS]
        s = self.scale.length
        for row, name in zip(rows, names, strict=True):
            x, y, z = (v * s for v in self._coords(row))
            fixed = restraints.pop(name, [False] * 6)
            if self.ndm == 2:
                y = 0.0
                fixed = [f if k in _SLOTS_2D else False for k, f in enumerate(fixed)]
            try:
                self.nodes.append(
                    Node(id=self.node_ids[name], coords=(x, y, z), restraint=tuple(fixed))  # type: ignore[arg-type]
                )
            except ValidationError as exc:
                raise Sap2000TextError(
                    f"Joint {name} ({_at('JOINT COORDINATES', row)}): {_first_error(exc)}"
                ) from exc
            self.points[name] = np.array([x, y, z])
        if restraints:
            self.dropped["restraint on a missing joint"] += len(restraints)

    # ── joint masses and springs ──
    def build_joint_assignments(self) -> None:
        """Added joint masses and support springs (``JOINT ADDED MASS ASSIGNMENTS``,
        ``JOINT SPRING ASSIGNMENTS 1 - UNCOUPLED``).

        Both are given in SAP2000's joint local axes, which default to global; a file
        that assigns rotated joint axes is refused row by row rather than turned
        silently. The mass source decides whether added masses carry any weight.
        """
        by_id = {node.id: node for node in self.nodes}
        nodes = {name: by_id[identifier] for name, identifier in self.node_ids.items()}
        s = self.scale
        self._read_mass_source()

        if self._added_masses:
            table = "JOINT ADDED MASS ASSIGNMENTS"
            factors = (s.mass, s.mass, s.mass, s.mass_inertia, s.mass_inertia, s.mass_inertia)
            for row in self.s2k.rows(table):
                name = row.get("Joint", "")
                where = f"Joint {name} ({_at(table, row)}): "
                if name not in nodes:
                    self.dropped["added mass on a missing joint"] += 1
                    continue
                if not self._joint_axes_are_global(row, "added mass"):
                    continue
                values = tuple(
                    _number(row, key, where=where) * factor
                    for key, factor in zip(_MASS_KEYS, factors, strict=True)
                )
                if any(value < 0.0 for value in values):
                    raise Sap2000TextError(f"{where}an added mass must not be negative.")
                if any(values):  # SAP2000 writes an all-zero row after clearing one
                    self._assign(
                        nodes[name],
                        "mass",
                        self._in_plane(values, "out-of-plane added mass component"),
                        where,
                    )

        table = "JOINT SPRING ASSIGNMENTS 1 - UNCOUPLED"
        factors = (s.line_load, s.line_load, s.line_load, s.moment, s.moment, s.moment)
        for row in self.s2k.rows(table):
            name = row.get("Joint", "")
            where = f"Joint {name} ({_at(table, row)}): "
            if name not in nodes:
                self.dropped["support spring on a missing joint"] += 1
                continue
            if not self._joint_axes_are_global(row, "support spring"):
                continue
            values = tuple(
                _number(row, key, where=where) * factor
                for key, factor in zip(_SPRING_KEYS, factors, strict=True)
            )
            if any(value < 0.0 for value in values):
                raise Sap2000TextError(f"{where}a spring stiffness must not be negative.")
            if any(values):
                self._assign(
                    nodes[name],
                    "spring",
                    self._in_plane(values, "out-of-plane support spring component"),
                    where,
                )

    def _read_mass_source(self) -> None:
        """Report what the file's mass source includes that this import cannot."""
        rows = self.s2k.rows("MASS SOURCE")
        if not rows:
            return
        if not self._added_masses:
            self.notes.append(
                "The mass source excludes added joint masses: JOINT ADDED MASS ASSIGNMENTS "
                "was not read."
            )
        if not all(_yes(row, "Elements") for row in rows):
            self.notes.append(
                "The mass source excludes element masses; the imported frames still carry "
                "theirs (mass per length from the material's unit mass)."
            )
        if any(_yes(row, "Loads") for row in rows):
            self.notes.append(
                "The mass source turns load patterns into mass, which this import does not "
                "model: only added joint masses and the elements' own mass are imported."
            )

    def _joint_axes_are_global(self, row: dict[str, str], what: str) -> bool:
        """Whether a joint assignment's axes are the global ones (the only case read)."""
        system = row.get("CoordSys", "GLOBAL").strip().lower()
        if system not in ("global", "local", "joint local"):
            self.dropped[f"{what} in coordinate system {row.get('CoordSys')}"] += 1
            return False
        if system != "global" and self._rotated_joint_axes:
            self.dropped[f"{what} in rotated joint local axes"] += 1
            return False
        return True

    def _in_plane(self, values: tuple[float, ...], what: str) -> tuple[float, ...]:
        """Zero the components a 2D model cannot carry, counted once per record."""
        if self.ndm == 3:
            return values
        if any(value for slot, value in enumerate(values) if slot not in _SLOTS_2D):
            self.dropped[what] += 1
        return tuple(value if slot in _SLOTS_2D else 0.0 for slot, value in enumerate(values))

    @staticmethod
    def _assign(node: Node, field: str, values: tuple[float, ...], where: str) -> None:
        """Set a validated node field, naming the record when the model refuses it."""
        try:
            setattr(node, field, values)
        except ValidationError as exc:
            raise Sap2000TextError(f"{where}{_first_error(exc)}") from exc

    # ── materials and sections ──
    def build_materials(self) -> None:
        s = self.scale
        for row in self.s2k.rows("MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES"):
            name = row.get("Material", "")
            where = (
                f"Material {name} "
                f"({_at('MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES', row)}): "
            )
            e = _number(row, "E1", where=where) * s.stress
            g = _number(row, "G12", where=where) * s.stress
            nu = _number(row, "U12", 0.0, where=where)
            if g <= 0 and e > 0:
                g = e / (2 * (1 + nu))
            elif e > 0 and not row.get("U12"):
                nu = e / (2 * g) - 1
            self.materials[name] = _Material(
                name=name,
                e=e,
                g=g,
                nu=nu,
                weight=_number(row, "UnitWeight", where=where) * s.force / s.length**3,
                mass=_number(row, "UnitMass", where=where) * s.density,
                alpha=_number(row, "A1", 0.0, where=where),
            )
        for row in self.s2k.rows("JOINT PATTERN ASSIGNMENTS"):
            pattern = row.get("Pattern", "")
            joint = row.get("Joint", "")
            self._joint_patterns[(pattern, joint)] = _number(
                row,
                "Value",
                where=f"Joint pattern {pattern} ({_at('JOINT PATTERN ASSIGNMENTS', row)}): ",
            )
        for row in self.s2k.rows("FRAME ADDED MASS ASSIGNMENTS"):
            self._added_mass[row.get("Frame", "")] = _number(
                row,
                "MassPerLen",
                where=f"Frame {row.get('Frame')} ({_at('FRAME ADDED MASS ASSIGNMENTS', row)}): ",
            )
        for row in self.s2k.rows("FRAME SECTION PROPERTIES 01 - GENERAL"):
            self.frame_sections[row.get("SectionName", "")] = row
        for row in self.s2k.rows("FRAME SECTION PROPERTIES 05 - NONPRISMATIC"):
            name = row.get("SectionName", "")
            if not name:
                continue
            self._nonprismatic_rows.setdefault(name, []).append(row)
            if name not in self.nonprismatic:
                self.nonprismatic[name] = row.get("StartSect", "")

    def _material(self, name: str, where: str) -> _Material:
        material = self.materials.get(name)
        if material is None:
            raise Sap2000TextError(f"{where}material {name!r} has no basic mechanical properties.")
        if material.e <= 0:
            raise Sap2000TextError(f"{where}material {name!r} has no modulus of elasticity.")
        return material

    def _section_row(self, name: str, seen: tuple[str, ...] = ()) -> dict[str, str]:
        """The properties row of a section, resolving a nonprismatic one to its start section.

        The start section gives the material and the sanity checks; the actual
        subdivision is built by :meth:`_nonprismatic_template`.
        """
        row = self.frame_sections.get(name)
        if row is None:
            raise Sap2000TextError(
                f"Frame section {name}: not in FRAME SECTION PROPERTIES 01 - GENERAL."
            )
        if row.get("Shape", "").strip().lower() != "nonprismatic":
            return row
        start = self.nonprismatic.get(name)
        if not start or start in seen or start == name:
            raise Sap2000TextError(
                f"Frame section {name} ({_at('FRAME SECTION PROPERTIES 01 - GENERAL', row)}): "
                "a Nonprismatic section needs a start section of its own in FRAME SECTION "
                "PROPERTIES 05 - NONPRISMATIC."
            )
        return self._section_row(start, (*seen, name))

    def _ordered_nonprismatic(self, name: str) -> list[S2kRow]:
        """The nonprismatic rows in member order.

        SAP2000 writes the segments from the frame's I end to its J end, in
        table order.  Do not reorder them by section name or by following
        ``EndSect -> StartSect``: an advanced nonprismatic definition may have
        discontinuous steps, and the table order is the physical one.  Two
        identical rows are two identical segments, so they are kept.
        """
        rows = self._nonprismatic_rows.get(name, [])
        if not rows:
            raise Sap2000TextError(
                f"Frame section {name}: no rows in FRAME SECTION PROPERTIES 05 - NONPRISMATIC."
            )
        return list(rows)

    def _nonprismatic_template(
        self,
        name: str,
        material: _Material,
        orientation: _Orientation,
        shear: bool,
    ) -> tuple[int, float]:
        """The project ``NonprismaticSection`` for a SAP2000 section, and its mass/length."""
        key = (name, material.name, orientation.two_on_y, shear)
        cached = self._nonprismatic_templates.get(key)
        if cached is not None:
            return cached
        rows = self._ordered_nonprismatic(name)
        section_ids: dict[str, int] = {}
        segments: list[NonprismaticSegment] = []
        start_mass: float | None = None
        for index, row in enumerate(rows):
            start = row.get("StartSect", "")
            end = row.get("EndSect", "")
            for section_name in (start, end):
                if section_name in section_ids:
                    continue
                section_row = self.frame_sections.get(section_name)
                if section_row is None:
                    raise Sap2000TextError(
                        f"Frame section {name}: nonprismatic segment {index + 1} refers to "
                        f"{section_name!r}, which is not in FRAME SECTION PROPERTIES 01 - GENERAL."
                    )
                if section_row.get("Shape", "").strip().lower() == "nonprismatic":
                    raise Sap2000TextError(
                        f"Frame section {name}: nonprismatic segment {index + 1} refers to "
                        f"another nonprismatic section {section_name!r}."
                    )
                values, row_values = self._section_values(section_name)
                section_id, mass = self._frame_section(
                    section_name, (values, row_values), material, orientation, shear
                )
                section_ids[section_name] = section_id
                if index == 0 and section_name == start:
                    start_mass = mass
            length_type = row.get("LengthType", "Absolute").strip().lower()
            if length_type not in ("absolute", "relative"):
                raise Sap2000TextError(
                    f"Frame section {name}: segment {index + 1} has LengthType "
                    f"{row.get('LengthType')!r}; expected Absolute or Relative."
                )
            length_key = "AbsLength" if length_type == "absolute" else "RelLength"
            length = _number(
                row,
                length_key,
                where=f"Frame section {name} (FRAME SECTION PROPERTIES 05 - NONPRISMATIC): ",
            )
            variation = row.get("EI33Var", "Linear").strip().lower()
            if variation not in ("linear", "parabolic", "cubic"):
                raise Sap2000TextError(
                    f"Frame section {name}: segment {index + 1} has EI33Var "
                    f"{row.get('EI33Var')!r}; expected Linear, Parabolic or Cubic."
                )
            if row.get("EI22Var", row.get("EI33Var", "")).strip().lower() != variation:
                self.dropped["nonprismatic EI22 variation (EI33 variation used)"] += 1
            try:
                segment = NonprismaticSegment(
                    start_section_id=section_ids[start],
                    end_section_id=section_ids[end],
                    length_type=cast(Literal["absolute", "relative"], length_type),
                    length=length,
                    variation=cast(Literal["linear", "parabolic", "cubic"], variation),
                )
            except ValidationError as exc:
                raise Sap2000TextError(
                    f"Frame section {name}: segment {index + 1} is invalid: {_first_error(exc)}"
                ) from exc
            segments.append(segment)
        if start_mass is None:
            start_mass = 0.0
        try:
            template = NonprismaticSection(
                id=len(self.sections) + 1,
                name=f"{name} (nonprismatic)",
                segments=segments,
                subdivisions=self.subdivisions,
            )
        except ValidationError as exc:
            raise Sap2000TextError(
                f"Frame section {name}: the nonprismatic definition is invalid: {_first_error(exc)}"
            ) from exc
        self.sections.append(template)
        self._nonprismatic_templates[key] = (template.id, start_mass)
        return template.id, start_mass

    def _section_values(self, name: str) -> tuple[dict[str, float], dict[str, str]]:
        row = self._section_row(name)
        where = f"Frame section {name} ({_at('FRAME SECTION PROPERTIES 01 - GENERAL', row)}): "
        shape = row.get("Shape", "General").strip().lower()
        given = {
            "A": _number(row, "Area", where=where),
            "I33": _number(row, "I33", where=where),
            "I22": _number(row, "I22", where=where),
            "J": _number(row, "TorsConst", where=where),
            "AS2": _number(row, "AS2", where=where),
            "AS3": _number(row, "AS3", where=where),
        }
        # A 2D model uses one bending inertia; SAP2000 writes 0 in the other one and in J.
        # The member's in-plane inertia is checked in build_frames, where the local axes
        # are known. A 3D model needs both inertias.
        complete = given["A"] > 0
        if self.ndm == 3:
            complete = complete and given["I33"] > 0 and given["I22"] > 0
        else:
            complete = complete and (given["I33"] > 0 or given["I22"] > 0)
        if complete:
            values = given
            known = ("rectangular", "i/wide flange", "pipe", "box/tube", "general")
            if shape not in known and name not in self._shapes_reported:
                self._shapes_reported.add(name)
                self.dropped[f"'{row.get('Shape')}' section geometry (kept its properties)"] += 1
        else:
            computed = _shape_props(shape, row, where)
            if computed is None:
                raise Sap2000TextError(
                    f"{where}a {row.get('Shape')!r} section needs its Area, I33 and I22."
                )
            values = computed
        mods = {
            k: _number(row, m, 1.0, where=where)
            for k, m in (
                ("A", "AMod"),
                ("AS2", "A2Mod"),
                ("AS3", "A3Mod"),
                ("J", "JMod"),
                ("I22", "I2Mod"),
                ("I33", "I3Mod"),
                ("M", "MMod"),
                ("W", "WMod"),
            )
        }
        values["A0"] = values["A"]  # mass and weight take the unmodified area
        for key in ("A", "AS2", "AS3", "J", "I22", "I33"):
            values[key] *= mods[key]
        values["MMod"], values["WMod"] = mods["M"], mods["W"]
        return values, row

    def _frame_section(
        self,
        name: str,
        properties: tuple[dict[str, float], dict[str, str]],
        material: _Material,
        orientation: _Orientation,
        shear: bool,
    ) -> tuple[int, float]:
        """The project section of a SAP2000 section used this way, and the member's mass/length."""
        values, row = properties
        s = self.scale
        a = values["A"] * s.area
        mass = material.mass * values["MMod"] * values["A0"] * s.area
        key = (name, material.name, orientation.two_on_y, shear)
        if key in self._section_keys:
            return self._section_keys[key], mass
        i33, i22 = values["I33"] * s.inertia, values["I22"] * s.inertia
        as2, as3 = values["AS2"] * s.area, values["AS3"] * s.area
        if orientation.two_on_y:
            iz, iy, avy, avz = i33, i22, as2, as3
        else:
            iz, iy, avy, avz = i22, i33, as3, as2
        label = name
        if row.get("Material", "") != material.name:
            label += f" / {material.name}"
        if orientation.two_on_y != (self.ndm == 2):
            label += " (axes 2-3)"
        if not shear and (as2 > 0 and as3 > 0):
            label += " (no shear)"
        fields: dict[str, Any] = {
            "id": len(self.sections) + 1,
            "name": label,
            "E": material.e,
            "A": a,
            "Iz": iz,
        }
        if self.ndm == 3:
            j = values["J"] * s.inertia
            if j <= 0.0:
                # OpenSees needs a torsional stiffness; SAP2000 allows J = 0. A tiny one
                # keeps the member from spinning about its own axis, and the report says so.
                if name not in self._zero_torsion:
                    self._zero_torsion.add(name)
                    self.dropped["zero torsional constant (a small one substituted)"] += 1
                j = 1e-6 * min(iz, iy)
            fields.update(Iy=iy, G=material.g, J=j)
        if shear:
            fields.update(G=material.g, As2=avy)
            if self.ndm == 3:
                fields["As3"] = avz
        if material.weight > 0:
            # The weight per length is γ · WMod · (unmodified area); the section carries γ · A.
            fields["unit_weight"] = material.weight * values["WMod"] * values["A0"] / values["A"]
        # The depth of a SAP2000 shape stands along its local 2: OpenSees z in 3D, y in 2D.
        if orientation.two_on_y == (self.ndm == 2):
            hint = _shape_hint(row.get("Shape", "").strip().lower(), row, s.length)
            if hint is not None:
                fields["shape"] = hint
        try:
            section = ElasticSection(**fields)
        except ValidationError as exc:
            raise Sap2000TextError(
                f"Frame section {name} "
                f"({_at('FRAME SECTION PROPERTIES 01 - GENERAL', row)}): {_first_error(exc)}"
            ) from exc
        self.sections.append(section)
        self._section_keys[key] = section.id
        return section.id, mass

    # ── frames ──
    def _releases(self, name: str, orientation: _Orientation) -> FrameReleases:
        row = self._release_rows.get(name)
        if row is None:
            return FrameReleases()
        springs_row: dict[str, str] = self._partial_rows.get(name, {})
        about2 = "M2" if orientation.two_on_y else "M3"
        about3 = "M3" if orientation.two_on_y else "M2"
        ends: list[EndRelease] = []
        for end in ("I", "J"):
            released: list[str] = []
            springs: dict[str, float] = {}
            for sap, ours in (("T", "T"), ("M2", about2), ("M3", about3)):
                if not _yes(row, f"{sap}{end}"):
                    continue
                if self.ndm == 2 and ours != "M3":
                    self.dropped["out-of-plane end release"] += 1
                    continue
                released.append(ours)
                k = _number(
                    springs_row,
                    f"{sap}{end}",
                    where=(
                        f"Frame {name} "
                        f"({_at('FRAME RELEASE ASSIGNMENTS 2 - PARTIAL FIXITY', springs_row)}): "
                    ),
                )
                if k > 0 and _yes(row, "PartialFix"):
                    springs[ours] = k * self.scale.moment
            for sap in ("P", "V2", "V3"):
                if _yes(row, f"{sap}{end}"):
                    self.dropped["axial or shear end release"] += 1
            ends.append(EndRelease(released=tuple(released), springs=springs))  # type: ignore[arg-type]
        if (
            "T" in ends[0].released
            and "T" in ends[1].released
            and not (ends[0].spring("T") or ends[1].spring("T"))
        ):
            ends[1] = EndRelease(
                released=tuple(r for r in ends[1].released if r != "T"),
                springs={k: v for k, v in ends[1].springs.items() if k != "T"},
            )
            self.notes.append(
                f"Frame {name}: torsion released at both ends; kept at end J (the member "
                "would spin about its own axis)."
            )
        return FrameReleases(i=ends[0], j=ends[1])

    def _frame_modifiers(self, name: str, orientation: _Orientation) -> FrameModifiers:
        """SAP2000's per-frame property modifiers, mapped to our local axes.

        SAP2000's axes 2/3 are not always ours, so the inertia and shear-area
        modifiers follow the same swap as the section properties.  SAP2000
        writes 0 in a shear-area modifier to mean "no shear deformation"; that
        is accepted.  A zero on A, J, I22 or I33 would create a mechanism, and
        is reported instead of being turned into a singular model.
        """
        row = self._frame_modifier_rows.get(name)
        if row is None:
            return FrameModifiers()
        mod_where = f"Frame {name} ({_at('FRAME PROPERTY MODIFIERS', row)}): "

        def value(key: str) -> float:
            return _number(row, key, 1.0, where=mod_where)

        area = value("AMod")
        torsion = value("JMod")
        if orientation.two_on_y:
            i33, i22 = value("I33Mod"), value("I22Mod")
            as2, as3 = value("AS2Mod"), value("AS3Mod")
        else:
            i33, i22 = value("I22Mod"), value("I33Mod")
            as2, as3 = value("AS3Mod"), value("AS2Mod")
        if min(area, torsion, i22, i33) <= 0.0:
            raise Sap2000TextError(
                f"{mod_where}a zero or negative A, J, I22 or I33 modifier would leave "
                "the member without a usable stiffness."
            )
        try:
            return FrameModifiers(
                area=area,
                as2=as2,
                as3=as3,
                torsion=torsion,
                i22=i22,
                i33=i33,
                mass=value("MassMod"),
                weight=value("WeightMod"),
            )
        except ValidationError as exc:
            raise Sap2000TextError(f"{mod_where}{_first_error(exc)}") from exc

    def build_frames(self, non_uniform: set[str]) -> None:
        rows = self.s2k.rows("CONNECTIVITY - FRAME")
        names = [row.get("Frame", "") for row in rows]
        if len(set(names)) != len(names):
            raise Sap2000TextError("A frame name appears twice in CONNECTIVITY - FRAME.")
        ids, renamed = _ids(names)
        if renamed:
            self.notes.append(
                "Frame names are not all positive integers: numbered 1… in file order."
            )
        assigned = {r.get("Frame", ""): r for r in self.s2k.rows("FRAME SECTION ASSIGNMENTS")}
        self.angles = {
            r.get("Frame", ""): _number(
                r,
                "Angle",
                where=(
                    f"Frame {r.get('Frame')} "
                    f"({_at('FRAME LOCAL AXES ASSIGNMENTS 1 - TYPICAL', r)}): "
                ),
            )
            for r in self.s2k.rows("FRAME LOCAL AXES ASSIGNMENTS 1 - TYPICAL")
        }
        for row, name in zip(rows, names, strict=True):
            where = f"Frame {name} ({_at('CONNECTIVITY - FRAME', row)}): "
            ends = (row.get("JointI", ""), row.get("JointJ", ""))
            for joint in ends:
                if joint not in self.node_ids:
                    raise Sap2000TextError(f"{where}joint {joint!r} is not defined.")
            if _yes(row, "IsCurved"):
                self.dropped["curved frame (imported straight)"] += 1
            p_i, p_j = self.points[ends[0]], self.points[ends[1]]
            if float(np.linalg.norm(p_j - p_i)) < 1e-12:
                raise Sap2000TextError(f"{where}zero length.")
            assignment = assigned.get(name)
            if assignment is None:
                raise Sap2000TextError(f"{where}no section assigned (FRAME SECTION ASSIGNMENTS).")
            section = assignment.get("AnalSect") or assignment.get("DesignSect") or ""
            if section.lower() == "none":
                self.dropped["frame with section None"] += 1
                continue
            section_row = self.frame_sections.get(section)
            is_nonprismatic = (
                section_row is not None
                and section_row.get("Shape", "").strip().lower() == "nonprismatic"
            )
            values, sec_row = self._section_values(section)
            mat_name = assignment.get("MatProp", "Default")
            if not mat_name or mat_name.lower() == "default":
                mat_name = sec_row.get("Material", "")
            material = self._material(mat_name, where)
            self._frame_alpha[name] = material.alpha
            angle = self.angles.get(name, 0.0)
            orientation = _orientation(self.ndm, p_i, p_j, angle)
            # A 2D file may carry 0 in the axis it does not bend about; the one it does
            # must not be 0, or the member has no stiffness the model can use.
            in_plane = values["I33"] if orientation.two_on_y else values["I22"]
            if in_plane <= 0.0:
                raise Sap2000TextError(
                    f"{where}the section has no inertia about the member's in-plane axis "
                    f"(I33 = {values['I33']:g}, I22 = {values['I22']:g})."
                )
            symmetric = math.isclose(values["I33"], values["I22"], rel_tol=1e-9) and math.isclose(
                values["AS2"], values["AS3"], rel_tol=1e-9
            )
            if not orientation.exact and not symmetric:
                self.oblique += 1
            releases = self._releases(name, orientation)
            modifiers = self._frame_modifiers(name, orientation)
            if is_nonprismatic and (modifiers.as2 != 1.0 or modifiers.as3 != 1.0):
                # SAP2000 writes 0 shear modifiers on some nonprismatic frames, but
                # its own results keep the shear flexibility of the segment
                # sections. Let the segment shear areas govern here too.
                modifiers = modifiers.model_copy(update={"as2": 1.0, "as3": 1.0})
                self._nonprismatic_shear_modifiers += 1
            if self.ndm == 2:
                has_shear = (values["AS2"] if orientation.two_on_y else values["AS3"]) > 0
            else:
                has_shear = values["AS2"] > 0 and values["AS3"] > 0
            # OpenSees' ElasticTimoshenkoBeam takes no releases and only full-length uniform loads.
            shear = has_shear and not releases.any and name not in non_uniform
            if has_shear and not shear:
                self.dropped["shear deformation (frame with releases or a non-uniform load)"] += 1
            if is_nonprismatic:
                section_id, mass = self._nonprismatic_template(
                    section, material, orientation, shear
                )
            else:
                section_id, mass = self._frame_section(
                    section, (values, sec_row), material, orientation, shear
                )
            added = self._added_mass.get(name, 0.0) * self.scale.mass / self.scale.length
            if added > 0.0:
                self._added_mass_frames += 1
            self.frames[name] = ElasticBeamColumn(
                id=ids[name],
                nodes=(self.node_ids[ends[0]], self.node_ids[ends[1]]),
                section_id=section_id,
                rho=mass + added,
                releases=releases,
                modifiers=modifiers,
            )
            self.frame_ends[name] = ends
        if self._added_mass_frames:
            self.notes.append(
                f"{self._added_mass_frames} frame(s) carry added mass (FRAME ADDED MASS "
                "ASSIGNMENTS), included in the element mass per length."
            )
        if self._nonprismatic_shear_modifiers:
            self.notes.append(
                f"{self._nonprismatic_shear_modifiers} nonprismatic frame(s) carry shear-area "
                "property modifiers; they are ignored, because the section's own segment "
                "shear areas govern (as SAP2000's results do)."
            )

    # ── areas ──
    def build_areas(self) -> None:
        rows = self.s2k.rows("CONNECTIVITY - AREA")
        if not rows:
            return
        if self.ndm == 2:
            self.dropped["area (a 2D frame model has no plane elements)"] += len(rows)
            return
        properties = {r.get("Section", ""): r for r in self.s2k.rows("AREA SECTION PROPERTIES")}
        assigned = {r.get("Area", ""): r for r in self.s2k.rows("AREA SECTION ASSIGNMENTS")}
        names = [r.get("Area", "") for r in rows]
        ids, renamed = _ids(names)
        frame_ids = {f.id for f in self.frames.values()}
        offset = 0
        if renamed or frame_ids & set(ids.values()):
            offset = max(frame_ids, default=0)
            self.notes.append(
                f"Area ids clash with frame ids (one id space in OpenSees): area n became "
                f"element {offset} + n{' in file order' if renamed else ''}."
            )
        thin = 0
        kinds: Counter[str] = Counter()
        for row, name in zip(rows, names, strict=True):
            where = f"Area {name} ({_at('CONNECTIVITY - AREA', row)}): "
            # Only a four-joint area is read. The count is checked before it is
            # used as a loop bound: `NumJoints=1E9` in a damaged file used to
            # hang the import, and 2.7 was silently truncated to 2.
            if _number(row, "NumJoints", 0.0, where=where) != 4:
                self.dropped["area with other than four joints"] += 1
                continue
            joints = [row.get(f"Joint{k}", "") for k in range(1, 5)]
            if len(set(joints)) != 4:
                self.dropped["area with other than four joints"] += 1
                continue
            for joint in joints:
                if joint not in self.node_ids:
                    raise Sap2000TextError(f"{where}joint {joint!r} is not defined.")
            assignment = assigned.get(name)
            prop = properties.get(assignment.get("Section", "") if assignment else "")
            if prop is None:
                self.dropped["area without a section"] += 1
                continue
            if prop.get("AreaType", "Shell").lower() != "shell":
                self.dropped[f"{prop.get('AreaType')} area"] += 1
                continue
            kind = prop.get("Type", "Shell-Thin")
            kinds[kind] += 1
            thin += kind.lower() == "shell-thin"
            mat_name = assignment.get("MatProp", "Default") if assignment else "Default"
            if not mat_name or mat_name.lower() == "default":
                mat_name = prop.get("Material", "")
            section_id = self._shell_section(prop, self._material(mat_name, where))
            self.shells.append(
                ShellMITC4Element(
                    id=offset + ids[name],
                    nodes=tuple(self.node_ids[j] for j in joints),  # type: ignore[arg-type]
                    section_id=section_id,
                )
            )
        if thin:
            self.notes.append(
                f"{thin} Shell-Thin area(s) became ShellMITC4, which also deforms in shear "
                "(a thick-shell formulation)."
            )
        for kind, count in kinds.items():
            if kind.lower().startswith(("membrane", "plate")):
                self.notes.append(f"{count} {kind} area(s) became full shells.")

    def _shell_section(self, prop: dict[str, str], material: _Material) -> int:
        name = prop.get("Section", "")
        key = ("area", name, material.name)
        if key in self._section_keys:
            return self._section_keys[key]
        h = (
            _number(
                prop,
                "Thickness",
                where=f"Area section {name} ({_at('AREA SECTION PROPERTIES', prop)}): ",
            )
            * self.scale.length
        )
        bend = _number(prop, "BendThick", 0.0) * self.scale.length
        if bend > 0 and not math.isclose(bend, h, rel_tol=1e-9):
            self.dropped["area bending thickness different from its membrane thickness"] += 1
        try:
            section = ElasticMembranePlateSection(
                id=len(self.sections) + 1,
                name=name,
                E=material.e,
                nu=material.nu,
                h=h,
                rho=material.mass,
                unit_weight=material.weight,
            )
        except ValidationError as exc:
            raise Sap2000TextError(
                f"Area section {name} ({_at('AREA SECTION PROPERTIES', prop)}): {_first_error(exc)}"
            ) from exc
        self.sections.append(section)
        self._section_keys[key] = section.id
        return section.id

    # ── diaphragms ──
    def build_diaphragms(self) -> None:
        """Turn SAP2000 diaphragm definitions and joint assignments into ``RigidDiaphragm``.

        SAP2000 places a *master* joint at the centre of the floor; it often
        has no element (and carries the floor mass).  That joint is the right
        ``rigidDiaphragm`` retained node: the runner fixes its out-of-plane
        DOFs automatically.  Choosing a real floor joint instead would leave
        a floating made-only-of-mass joint with free out-of-plane rotations,
        which is the singular model the earlier prototype produced.
        """
        if self._non_diaphragm_constraints:
            self.dropped["joint constraint other than a diaphragm"] += (
                self._non_diaphragm_constraints
            )
        if not self._diaphragm_defs:
            return
        if self.ndm != 3:
            self.dropped["rigid diaphragm in a 2D model"] += len(self._diaphragm_defs)
            return
        used: set[int] = set()
        for frame in self.frames.values():
            used.update(frame.nodes)
        for shell in self.shells:
            used.update(shell.nodes)
        nodes = {node.id: node for node in self.nodes}
        axis_of = {"X": 1, "Y": 2, "Z": 3, "1": 1, "2": 2, "3": 3}
        for name, row in self._diaphragm_defs.items():
            perp = axis_of.get(row.get("Axis", "Z").strip().upper())
            if perp is None:
                self.dropped["diaphragm with an unknown axis"] += 1
                continue
            perp = cast(Literal[1, 2, 3], perp)
            if _yes(row, "MultiLevel"):
                # OpenSees' rigidDiaphragm is a single plane.
                self.dropped["multi-level rigid diaphragm"] += 1
                continue
            joints = self._constraint_joints.get(name, [])
            missing = [joint for joint in joints if joint not in self.node_ids]
            if missing:
                self.dropped["diaphragm on a missing joint"] += len(missing)
            ids = sorted({self.node_ids[joint] for joint in joints if joint in self.node_ids})
            if len(ids) < 2:
                self.dropped["rigid diaphragm with fewer than two joints"] += 1
                continue

            # The SAP master is the (normally floating) joint at the floor's
            # centre; use it as the plane reference when it exists.
            floating = [nid for nid in ids if nid not in used]
            reference = floating[0] if floating else ids[0]
            axis_index = perp - 1
            scale = max(
                1.0,
                max(abs(node.coords[axis_index]) for node in nodes.values()),
            )
            tolerance = 1e-6 * scale
            elevation = nodes[reference].coords[axis_index]
            in_plane = [
                nid for nid in ids if abs(nodes[nid].coords[axis_index] - elevation) <= tolerance
            ]
            if len(in_plane) < len(ids):
                self.dropped["diaphragm joint outside the floor plane"] += len(ids) - len(in_plane)
            slots = IN_PLANE_SLOTS[perp]
            # A support cannot also follow the floor.  SAP2000 allows the
            # assignment; OpenSees would silently ignore it.
            free = [
                nid for nid in in_plane if not any(nodes[nid].restraint[slot] for slot in slots)
            ]
            if len(free) < len(in_plane):
                self.dropped["diaphragm joint restrained in the plane (left out)"] += len(
                    in_plane
                ) - len(free)
            candidates = [nid for nid in free if nid in floating] or free
            if not candidates:
                self.dropped["rigid diaphragm with no free joint"] += 1
                continue
            retained = candidates[0]
            constrained = tuple(nid for nid in free if nid != retained)
            if not constrained:
                self.dropped["rigid diaphragm with no constrained joint"] += 1
                continue
            self.diaphragms.append(
                RigidDiaphragm(
                    id=len(self.diaphragms) + 1,
                    name=name,
                    perp_dirn=perp,
                    retained_node=retained,
                    constrained_nodes=constrained,
                )
            )

    # ── loads ──
    def non_uniform_frames(self) -> set[str]:
        """Frames with a load an ElasticTimoshenkoBeam cannot take (partial, varying or point)."""
        found = {r.get("Frame", "") for r in self.s2k.rows("FRAME LOADS - POINT")}
        for row in self.s2k.rows("FRAME LOADS - DISTRIBUTED"):
            a, b = _number(row, "RelDistA", 0.0), _number(row, "RelDistB", 1.0)
            w_a, w_b = _number(row, "FOverLA"), _number(row, "FOverLB")
            if a > 0 or b < 1 or not math.isclose(w_a, w_b):
                found.add(row.get("Frame", ""))
        return found

    def _direction(self, row: dict[str, str], name: str) -> np.ndarray | None:
        """The unit vector a frame load acts along, in global axes (None: not supported)."""
        direction = row.get("Dir", "Gravity").strip().lower()
        ends = self.frame_ends[name]
        p_i, p_j = self.points[ends[0]], self.points[ends[1]]
        local = sap_local_axes(p_i, p_j, self.angles.get(name, 0.0))
        vectors = {
            "gravity": np.array([0.0, 0.0, -1.0]),
            "x": np.array([1.0, 0.0, 0.0]),
            "y": np.array([0.0, 1.0, 0.0]),
            "z": np.array([0.0, 0.0, 1.0]),
            "1": local[0],
            "2": local[1],
            "3": local[2],
        }
        projected = direction.endswith(" projected") or direction.endswith(" proj")
        base = direction.split(" ")[0]
        if base not in vectors:
            return None
        vector = vectors[base]
        if projected:
            # A load per projected length: per member length it is w · (projected / true length).
            vector = vector * math.sqrt(max(0.0, 1.0 - float(np.dot(vector, local[0])) ** 2))
        return vector

    def _local(self, name: str, vector: np.ndarray) -> list[float]:
        ends = self.frame_ends[name]
        axes = frame_local_axes(
            self.ndm, self.points[ends[0]].tolist(), self.points[ends[1]].tolist()
        )
        assert axes is not None
        local = [float(np.dot(vector, axis)) for axis in axes]
        if self.ndm == 2 and abs(local[2]) > 1e-9:
            self.dropped["out-of-plane frame load component"] += 1
        if self.ndm == 2:
            local[2] = 0.0
        return [0.0 if abs(c) < 1e-12 else c for c in local]

    def _usable_frame_load(self, row: dict[str, str], kind: str) -> str | None:
        name = row.get("Frame", "")
        if name not in self.frames:
            self.dropped[f"{kind} load on a missing frame"] += 1
            return None
        if row.get("Type", "Force").lower() != "force":
            self.dropped[f"{kind} moment load"] += 1
            return None
        if row.get("CoordSys", "GLOBAL").upper() not in ("GLOBAL", "LOCAL"):
            self.dropped[f"{kind} load in another coordinate system"] += 1
            return None
        return name

    def build_patterns(self) -> dict[str, PlainLoadPattern]:
        patterns: dict[str, PlainLoadPattern] = {}
        for k, row in enumerate(self.s2k.rows("LOAD PATTERN DEFINITIONS"), start=1):
            pattern_name = row.get("LoadPat", f"LP{k}")
            if row.get("AutoLoad") and row["AutoLoad"].lower() not in ("none", ""):
                self.dropped[f"automatic {row['AutoLoad']} load"] += 1
            patterns[pattern_name] = PlainLoadPattern(
                id=k,
                name=pattern_name,
                time_series_id=1,
                self_weight=_number(
                    row,
                    "SelfWtMult",
                    where=(
                        f"Load pattern {pattern_name} ({_at('LOAD PATTERN DEFINITIONS', row)}): "
                    ),
                ),
            )
        s = self.scale

        def pattern_of(row: dict[str, str], what: str) -> PlainLoadPattern | None:
            pattern = patterns.get(row.get("LoadPat", ""))
            if pattern is None:
                self.dropped[f"{what} in an undefined load pattern"] += 1
            return pattern

        for row in self.s2k.rows("JOINT LOADS - FORCE"):
            pattern = pattern_of(row, "joint load")
            joint = row.get("Joint", "")
            if pattern is None:
                continue
            if joint not in self.node_ids:
                self.dropped["load on a missing joint"] += 1
                continue
            if row.get("CoordSys", "GLOBAL").upper() != "GLOBAL":
                self.dropped["joint load in a local coordinate system"] += 1
                continue
            forces = [
                _number(row, key, where=f"Joint {joint} ({_at('JOINT LOADS - FORCE', row)}): ")
                * (s.force if k < 3 else s.moment)
                for k, key in enumerate(_FORCE_KEYS)
            ]
            if self.ndm == 2:
                if any(forces[k] for k in range(6) if k not in _SLOTS_2D):
                    self.dropped["out-of-plane joint load component"] += 1
                forces = [f if k in _SLOTS_2D else 0.0 for k, f in enumerate(forces)]
            pattern.nodal_loads.append(
                NodalLoad(node_id=self.node_ids[joint], forces=tuple(forces))  # type: ignore[arg-type]
            )

        uniform: dict[tuple[str, int], list[float]] = {}
        trapezoids: dict[tuple[str, int, float, float], list[float]] = {}
        for row in self.s2k.rows("FRAME LOADS - DISTRIBUTED"):
            pattern = pattern_of(row, "frame load")
            name = self._usable_frame_load(row, "distributed")
            if pattern is None or name is None:
                continue
            vector = self._direction(row, name)
            if vector is None:
                self.dropped[f"distributed load along {row.get('Dir')}"] += 1
                continue
            where = f"Frame {name} ({_at('FRAME LOADS - DISTRIBUTED', row)}): "
            local = self._local(name, vector)
            a, b = (
                _number(row, "RelDistA", 0.0, where=where),
                _number(row, "RelDistB", 1.0, where=where),
            )
            if "RelDistA" not in row and "AbsDistA" in row:
                length = float(np.linalg.norm(self._span(name))) / s.length
                a = _number(row, "AbsDistA", where=where) / length
                b = _number(row, "AbsDistB", where=where) / length
            w_a = _number(row, "FOverLA", where=where) * s.line_load
            w_b = _number(row, "FOverLB", w_a / s.line_load, where=where) * s.line_load
            if not 0 <= a < b <= 1:
                self.dropped["distributed load with an empty or out-of-member span"] += 1
                continue
            element_id = self.frames[name].id
            if a == 0 and b == 1 and math.isclose(w_a, w_b):
                total = uniform.setdefault((pattern.name, element_id), [0.0, 0.0, 0.0])
                for k in range(3):
                    total[k] += local[k] * w_a
            else:
                total = trapezoids.setdefault((pattern.name, element_id, a, b), [0.0] * 6)
                for k in range(3):
                    total[k] += local[k] * w_a
                    total[3 + k] += local[k] * w_b
        for (pattern_name, element_id), (wx, wy, wz) in uniform.items():
            patterns[pattern_name].element_loads.append(
                UniformElementLoad(element_id=element_id, wx=wx, wy=wy, wz=wz)
            )
        for (pattern_name, element_id, a, b), w in trapezoids.items():
            patterns[pattern_name].distributed_loads.append(
                TrapezoidalElementLoad(
                    element_id=element_id,
                    x_start=a,
                    x_end=b,
                    wx_start=w[0],
                    wy_start=w[1],
                    wz_start=w[2],
                    wx_end=w[3],
                    wy_end=w[4],
                    wz_end=w[5],
                )
            )

        # Rows on one frame, pattern and span (one per direction) add up to one load.
        points: dict[tuple[str, int, float], list[float]] = {}
        for row in self.s2k.rows("FRAME LOADS - POINT"):
            pattern = pattern_of(row, "frame load")
            name = self._usable_frame_load(row, "point")
            if pattern is None or name is None:
                continue
            vector = self._direction(row, name)
            if vector is None or row.get("Dir", "").lower().endswith(("projected", "proj")):
                self.dropped[f"point load along {row.get('Dir')}"] += 1
                continue
            where = f"Frame {name} ({_at('FRAME LOADS - POINT', row)}): "
            local = self._local(name, vector)
            x = _number(row, "RelDist", -1.0, where=where)
            if x < 0:
                length = float(np.linalg.norm(self._span(name))) / s.length
                x = _number(row, "AbsDist", where=where) / length
            if not 0 <= x <= 1:
                self.dropped["point load off its member"] += 1
                continue
            p = _number(row, "Force", where=where) * s.force
            total = points.setdefault((pattern.name, self.frames[name].id, x), [0.0, 0.0, 0.0])
            for k in range(3):
                total[k] += local[k] * p
        for (pattern_name, element_id, x), (px, py, pz) in points.items():
            patterns[pattern_name].point_loads.append(
                PointElementLoad(element_id=element_id, px=px, py=py, pz=pz, x=x)
            )

        # Ground displacements: a support settlement, OpenSees' `sp`, in the pattern.
        slots = _SLOTS_2D if self.ndm == 2 else tuple(range(6))
        nodes_by_id = {node.id: node for node in self.nodes}
        for row in self.s2k.rows("JOINT LOADS - GROUND DISPLACEMENT"):
            pattern = pattern_of(row, "ground displacement")
            joint = row.get("Joint", "")
            if pattern is None:
                continue
            if joint not in self.node_ids:
                self.dropped["ground displacement on a missing joint"] += 1
                continue
            if row.get("CoordSys", "GLOBAL").strip().upper() != "GLOBAL":
                self.dropped["ground displacement in a local coordinate system"] += 1
                continue
            where = f"Joint {joint} ({_at('JOINT LOADS - GROUND DISPLACEMENT', row)}): "
            values = [
                _number(row, key, where=where) * (s.length if k < 3 else 1.0)
                for k, key in enumerate(_DOF_KEYS)
            ]
            if self.ndm == 2 and any(values[k] for k in range(6) if k not in _SLOTS_2D):
                self.dropped["out-of-plane ground displacement component"] += 1
            node = nodes_by_id[self.node_ids[joint]]
            for position, slot in enumerate(slots):
                if not values[slot]:
                    continue
                if not node.restraint[slot]:
                    # SAP moves the ground end of a spring support; this model's support
                    # spring is a stiffness to a fixed point, so the load cannot be carried.
                    self.dropped["ground displacement on a non-restrained DOF"] += 1
                    continue
                pattern.imposed_displacements.append(
                    ImposedDisplacement(
                        node_id=self.node_ids[joint], dof=position + 1, value=values[slot]
                    )
                )

        # Temperature: uniform, a joint-pattern variation along the member (its mean is
        # used) and a gradient along each local axis (SAP gives it per unit length).
        for row in self.s2k.rows("FRAME LOADS - TEMPERATURE"):
            pattern = pattern_of(row, "temperature load")
            name = row.get("Frame", "")
            if pattern is None:
                continue
            if name not in self.frames:
                self.dropped["temperature load on a missing frame"] += 1
                continue
            where = f"Frame {name} ({_at('FRAME LOADS - TEMPERATURE', row)}): "
            element = self.frames[name]
            if element.releases.any or not element.end_offsets.is_default():
                self.dropped["temperature load on a frame with releases or offsets"] += 1
                continue
            alpha = self._frame_alpha.get(name, 0.0)
            if alpha <= 0.0:
                self.dropped["temperature load on a material without thermal expansion"] += 1
                continue
            temperature = _number(row, "Temp", where=where)
            joint_pattern = row.get("JtPattern", "None").strip()
            if joint_pattern and joint_pattern.lower() not in ("none", ""):
                # With a joint pattern, SAP2000 takes the temperatures from the pattern
                # (a linear variation along the member) and its ``Temp`` is the reference.
                ends = self.frame_ends[name]
                pattern_values = [
                    self._joint_patterns.get((joint_pattern, joint), 0.0) for joint in ends
                ]
                temperature = sum(pattern_values) / len(pattern_values)
                self.dropped["temperature varying along the member (mean used)"] += 1
            grad2 = _number(row, "TempGrad2", where=where)
            grad3 = _number(row, "TempGrad3", where=where)
            gradient_y = gradient_z = 0.0
            if grad2 or grad3:
                ends = self.frame_ends[name]
                p_i, p_j = self.points[ends[0]], self.points[ends[1]]
                sap = sap_local_axes(p_i, p_j, self.angles.get(name, 0.0))
                ours = frame_local_axes(self.ndm, p_i.tolist(), p_j.tolist())
                assert ours is not None
                if grad2:  # SAP gives the gradient per unit length along local 2
                    gradient_y += float(np.dot(sap[1], ours[1])) * grad2
                    gradient_z += float(np.dot(sap[1], ours[2])) * grad2
                if grad3:  # and along local 3
                    gradient_y += float(np.dot(sap[2], ours[1])) * grad3
                    gradient_z += float(np.dot(sap[2], ours[2])) * grad3
            if self.ndm == 2 and abs(gradient_z) > 1e-12:
                self.dropped["out-of-plane temperature gradient"] += 1
                gradient_z = 0.0
            if temperature or gradient_y or gradient_z:
                pattern.temperature_loads.append(
                    TemperatureLoad(
                        element_id=element.id,
                        alpha=alpha,
                        uniform=temperature,
                        gradient_y=gradient_y,
                        gradient_z=gradient_z,
                    )
                )
        return patterns

    def _span(self, name: str) -> np.ndarray:
        ends = self.frame_ends[name]
        span: np.ndarray = self.points[ends[1]] - self.points[ends[0]]
        return span

    # ── cases and combinations ──
    def build_cases(
        self, patterns: dict[str, PlainLoadPattern]
    ) -> tuple[list[PlainLoadPattern], list[AnalysisCase]]:
        definitions = self.s2k.rows("LOAD CASE DEFINITIONS")
        extra: list[PlainLoadPattern] = []
        cases: list[AnalysisCase] = []
        if not definitions:
            for pattern in patterns.values():
                cases.append(
                    StaticCase(id=len(cases) + 1, name=pattern.name, pattern_ids=[pattern.id])
                )
            if cases:
                self.notes.append(
                    "The file has no load cases: one linear static case per load pattern."
                )
            return extra, cases
        assignments: dict[str, list[dict[str, str]]] = {}
        for row in self.s2k.rows("CASE - STATIC 1 - LOAD ASSIGNMENTS"):
            assignments.setdefault(row.get("Case", ""), []).append(row)
        next_pattern = len(patterns) + 1
        scaled: dict[tuple[str, float], int] = {}
        modal_cases: dict[str, ModalCase] = {}
        pending_preloads: list[tuple[StaticCase, str]] = []
        for row in definitions:
            name = row.get("Case", "")
            kind = row.get("Type", "")
            if kind.lower() == "linmodal":
                modal = self._modal_case(row, name, len(cases) + 1)
                if modal is not None:
                    cases.append(modal)
                    modal_cases[name] = modal
                continue
            if kind.lower() == "linrespspec":
                continue  # second pass: its modal case must have an id first
            if kind.lower() != "linstatic":
                self.dropped[f"{kind or 'untyped'} load case"] += 1
                continue
            initial = row.get("InitialCond", "Zero").strip()
            pattern_ids: list[int] = []
            for load in assignments.get(name, []):
                if load.get("LoadType", "Load pattern").lower() != "load pattern":
                    self.dropped[f"{load.get('LoadType')} in a static case"] += 1
                    continue
                used = patterns.get(load.get("LoadName", ""))
                if used is None:
                    self.dropped["undefined load pattern in a static case"] += 1
                    continue
                factor = _number(
                    load,
                    "LoadSF",
                    1.0,
                    where=(f"Case {name} ({_at('CASE - STATIC 1 - LOAD ASSIGNMENTS', load)}): "),
                )
                if math.isclose(factor, 1.0):
                    pattern_ids.append(used.id)
                    continue
                key = (used.name, factor)
                if key not in scaled:
                    clone = _scaled(used, factor, next_pattern)
                    next_pattern += 1
                    scaled[key] = clone.id
                    extra.append(clone)
                pattern_ids.append(scaled[key])
            if not pattern_ids:
                self.dropped["static case with no load pattern"] += 1
                continue
            case = StaticCase(id=len(cases) + 1, name=name, pattern_ids=pattern_ids)
            cases.append(case)
            if initial.lower() not in ("zero", "", "none"):
                pending_preloads.append((case, initial))
        for row in definitions:
            if row.get("Type", "").lower() != "linrespspec":
                continue
            spectrum = self._response_spectrum_case(row, len(cases) + 1, modal_cases)
            if spectrum is not None:
                cases.append(spectrum)
        by_name = {case.name: case for case in cases}
        for case, initial in pending_preloads:
            preload = by_name.get(initial)
            if isinstance(preload, StaticCase):
                case.preload_case_ids = [preload.id]
            else:
                self.dropped["static case starting from another case (run from zero)"] += 1
        if scaled:
            self.notes.append(
                f"{len(scaled)} load pattern(s) scaled by a case's factor became pattern(s) of "
                "their own (named 'pattern x factor')."
            )
        return extra, cases

    def _modal_case(self, definition: S2kRow, name: str, case_id: int) -> ModalCase | None:
        """A ``LinModal`` case from its ``CASE - MODAL 1 - GENERAL`` row, when it is an eigen one."""
        table = "CASE - MODAL 1 - GENERAL"
        row = next((r for r in self.s2k.rows(table) if r.get("Case", "") == name), None)
        if row is None:
            self.dropped["modal case without its general properties"] += 1
            return None
        mode = row.get("ModeType", "Eigen").strip()
        if mode.lower() != "eigen":
            self.dropped[f"{mode or 'untyped'} modal case"] += 1
            return None
        if definition.get("InitialCond", "Zero").lower() not in ("zero", ""):
            self.dropped["modal case starting from another case (run from zero)"] += 1
        where = f"Modal case {name} ({_at(table, row)}): "
        modes = _number(row, "MaxNumModes", 0.0, where=where)
        if modes < 1 or modes != int(modes):
            raise Sap2000TextError(
                f"{where}MaxNumModes must be a positive whole number, not {modes:g}."
            )
        # The case's solver is left on auto: this build routes dense/ARPACK itself.
        return ModalCase(id=case_id, name=name, n_modes=int(modes))

    def _response_spectrum_case(
        self, definition: S2kRow, case_id: int, modal_cases: dict[str, ModalCase]
    ) -> ResponseSpectrumCase | None:
        """A ``LinRespSpec`` case from its two tables, when it is one this model can run."""
        table = "CASE - RESPONSE SPECTRUM 1 - GENERAL"
        name = definition.get("Case", "")
        general = next((r for r in self.s2k.rows(table) if r.get("Case", "") == name), None)
        if general is None:
            self.dropped["spectrum case without its general properties"] += 1
            return None
        where = f"Spectrum case {name} ({_at(table, general)}): "
        rule = general.get("ModalCombo", "CQC").strip()
        rules: dict[str, Literal["SRSS", "CQC"]] = {"srss": "SRSS", "cqc": "CQC"}
        combination = rules.get(rule.lower())
        if combination is None:
            self.dropped[f"{rule or 'untyped'} modal combination"] += 1
            return None
        if _number(general, "EccenRatio", 0.0, where=where):
            self.dropped["spectrum case with accidental eccentricity"] += 1
            return None
        if _number(general, "GMCf2", 0.0, where=where):
            self.dropped["spectrum case with a second scale factor"] += 1
            return None

        loads = "CASE - RESPONSE SPECTRUM 2 - LOAD ASSIGNMENTS"
        rows = [r for r in self.s2k.rows(loads) if r.get("Case", "") == name]
        if len(rows) != 1:
            self.dropped[
                "spectrum case with no direction"
                if not rows
                else "spectrum case with more than one direction"
            ] += 1
            return None
        load = rows[0]
        load_where = f"Spectrum case {name} ({_at(loads, load)}): "
        if load.get("CoordSys", "GLOBAL").strip().upper() != "GLOBAL":
            self.dropped["spectrum in a user coordinate system"] += 1
            return None
        if _number(load, "Angle", 0.0, where=load_where):
            self.dropped["spectrum at a non-zero angle"] += 1
            return None
        direction = _DIRECTIONS.get(load.get("LoadName", "").strip().upper())
        if direction is None:
            self.dropped[f"spectrum along {load.get('LoadName')!r}"] += 1
            return None

        modal_name = general.get("ModalCase", "")
        modal = (
            modal_cases.get(modal_name) if modal_name else next(iter(modal_cases.values()), None)
        )
        if modal is None:
            self.dropped["spectrum case without a modal case"] += 1
            return None
        spectrum_id = self._spectrum(load, general, load_where)
        if spectrum_id is None:
            return None
        damping = _number(general, "ConstDamp", 0.0, where=where)
        if not 0.0 <= damping <= 1.0:
            raise Sap2000TextError(f"{where}ConstDamp must be between 0 and 1, not {damping:g}.")
        return ResponseSpectrumCase(
            id=case_id,
            name=name,
            modal_case_id=modal.id,
            spectrum_id=spectrum_id,
            direction=direction,
            combination=combination,
            damping_ratio=damping if damping > 0.0 else None,
        )

    def _spectrum(self, load: S2kRow, general: S2kRow, where: str) -> int | None:
        """The project spectrum a load assignment names, built once per function and scale."""
        table = "FUNCTION - RESPONSE SPECTRUM - USER"
        function = load.get("Function", "")
        rows = [r for r in self.s2k.rows(table) if r.get("Name", "") == function]
        if len(rows) < 2:
            self.dropped[f"spectrum function {function!r} with fewer than two points"] += 1
            return None
        # TransAccSF takes the tabulated ordinates (usually in g) to the file's length/s2;
        # a file that leaves it out is read as g, which is already in project units.
        factor = _number(load, "TransAccSF", 0.0, where=where)
        factor = gravity(self.target) if factor <= 0.0 else factor * self.scale.length
        factor *= _number(general, "GMCf1", 1.0, where=where)
        damping = min(max(_number(general, "ConstDamp", 0.05, where=where), 0.0), 1.0)
        key = (function, factor, damping)
        if key in self._spectrum_ids:
            return self._spectrum_ids[key]
        points: dict[float, float] = {}
        for row in rows:
            row_where = f"Spectrum {function} ({_at(table, row)}): "
            period = _number(row, "Period", where=row_where)
            if period < 0.0:
                raise Sap2000TextError(f"{row_where}a period must not be negative.")
            if period == 0.0:
                # SAP2000's T = 0 point is the PGA; the model wants a positive period.
                if function not in self._zero_period:
                    self._zero_period.add(function)
                    self.dropped["zero period in a response spectrum (read as 1e-6 s)"] += 1
                period = 1e-6
            points[period] = _number(row, "Accel", where=row_where) * factor
        ordered = sorted(points.items())
        if len(ordered) < 2:
            self.dropped[f"spectrum function {function!r} with fewer than two periods"] += 1
            return None
        name = function
        used = {spectrum.name for spectrum in self.spectra}
        while name in used:
            name = f"{function} ({len(self.spectra) + 1})"
        spectrum = ResponseSpectrum(
            id=len(self.spectra) + 1,
            name=name,
            periods=[period for period, _ in ordered],
            accelerations=[value for _, value in ordered],
            damping_ratio=damping,
        )
        self.spectra.append(spectrum)
        self._spectrum_ids[key] = spectrum.id
        return spectrum.id

    def build_combinations(self, cases: list[AnalysisCase]) -> list[LoadCombination]:
        rows = self.s2k.rows("COMBINATION DEFINITIONS")
        order: list[str] = []
        grouped: dict[str, list[S2kRow]] = {}
        for row in rows:
            name = row.get("ComboName", "")
            if name not in grouped:
                order.append(name)
            grouped.setdefault(name, []).append(row)
        combo_ids = {name: k for k, name in enumerate(order, start=1)}
        case_ids = {case.name: case.id for case in cases if isinstance(case, StaticCase)}
        combinations: list[LoadCombination] = []
        for name in order:
            kind = next((r["ComboType"] for r in grouped[name] if r.get("ComboType")), "Linear Add")
            combo_type = _COMBO_TYPES.get(kind.strip().lower())
            if combo_type is None:
                self.dropped[f"{kind} combination"] += 1
                continue
            terms: list[CombinationTerm] = []
            for row in grouped[name]:
                ref = row.get("CaseName", row.get("Case", ""))
                factor = _number(
                    row,
                    "ScaleFactor",
                    1.0,
                    where=f"Combination {name} ({_at('COMBINATION DEFINITIONS', row)}): ",
                )
                case_type = row.get("CaseType", "Linear Static").lower()
                if case_type == "response combo" and ref in combo_ids and ref != name:
                    terms.append(
                        CombinationTerm(source="combination", ref_id=combo_ids[ref], factor=factor)
                    )
                elif case_type != "response combo" and ref in case_ids:
                    terms.append(CombinationTerm(ref_id=case_ids[ref], factor=factor))
                else:
                    self.dropped["combination term on a case not imported"] += 1
            if not terms:
                self.dropped["empty combination"] += 1
                continue
            combinations.append(
                LoadCombination(
                    id=combo_ids[name],
                    name=name,
                    combination_type=cast(CombinationType, combo_type),
                    terms=terms,
                )
            )
        kept = {c.id for c in combinations}
        for combination in combinations:
            missing = [
                t for t in combination.terms if t.source == "combination" and t.ref_id not in kept
            ]
            if missing:
                self.dropped["combination term on a case not imported"] += len(missing)
                combination.terms = [t for t in combination.terms if t not in missing]
        return [c for c in combinations if c.terms]

    def grid(self) -> CoordinateGridSystem | None:
        lines: dict[str, dict[float, str]] = {"X": {}, "Y": {}, "Z": {}}
        for row in self.s2k.rows("GRID LINES"):
            if row.get("CoordSys", "GLOBAL").upper() != "GLOBAL":
                continue
            axis = row.get("AxisDir", "").upper()
            if axis in lines:
                ordinate = round(
                    _number(
                        row,
                        "XRYZCoord",
                        where=f"Grid line ({_at('GRID LINES', row)}): ",
                    )
                    * self.scale.length,
                    12,
                )
                label = row.get("GridID") or f"{axis}{len(lines[axis]) + 1}"
                lines[axis].setdefault(ordinate, label)
        if not any(lines.values()):
            return None

        def grid_lines(axis: str) -> list[GridLine]:
            return [GridLine(id=label, ordinate=v) for v, label in sorted(lines[axis].items())]

        return CoordinateGridSystem(
            name="Global",
            grid=GridSystem(
                x_grid_lines=grid_lines("X"),
                y_grid_lines=grid_lines("Y"),
                z_grid_lines=grid_lines("Z"),
            ),
        )


def _scaled(pattern: PlainLoadPattern, factor: float, new_id: int) -> PlainLoadPattern:
    """A copy of ``pattern`` with every load (and the self weight) times ``factor``."""

    def times(load: Any, keys: tuple[str, ...]) -> Any:
        return load.model_copy(update={k: getattr(load, k) * factor for k in keys})

    return pattern.model_copy(
        update={
            "id": new_id,
            "name": f"{pattern.name} x {factor:g}",
            "self_weight": pattern.self_weight * factor,
            "nodal_loads": [
                n.model_copy(update={"forces": tuple(f * factor for f in n.forces)})
                for n in pattern.nodal_loads
            ],
            "element_loads": [times(e, ("wx", "wy", "wz")) for e in pattern.element_loads],
            "point_loads": [times(p, ("px", "py", "pz")) for p in pattern.point_loads],
            "distributed_loads": [
                times(d, ("wx_start", "wx_end", "wy_start", "wy_end", "wz_start", "wz_end"))
                for d in pattern.distributed_loads
            ],
        },
        deep=True,
    )


def s2k_to_project(
    s2k: S2kFile,
    *,
    units: UnitSystem | None = None,
    source_units: str | None = None,
    nonprismatic_subdivisions: int | None = None,
) -> Sap2000Import:
    """Translate a parsed SAP2000 text file into a new project in ``units``.

    ``source_units`` overrides the file's ``CurrUnits``; ``units`` is the
    project's system, by default the one closest to the file's.

    Raises:
        Sap2000TextError: on unknown units, a broken reference, a value the
            project model refuses, or a file with no joints.
    """
    source = source_units or s2k.units
    target = units or default_target(source)
    translator = _Translator(
        s2k,
        target,
        source,
        subdivisions=nonprismatic_subdivisions or 12,
    )
    if not s2k.has_units and source_units is None:
        translator.notes.append(f"The file declares no units: read as {DEFAULT_UNITS!r}.")
    if s2k.malformed:
        first_line, first_text = s2k.malformed[0]
        translator.notes.append(
            f"{len(s2k.malformed)} line(s) in the file are not Key=Value records and were "
            f"skipped (first at line {first_line}: {first_text[:60]!r})."
        )
    with perf.span("s2k.joints"):
        translator.build_joints()
    if not translator.nodes:
        raise Sap2000TextError(
            f"{s2k.path.name} has no joints (JOINT COORDINATES is missing or empty): "
            "there is no model to import."
        )
    with perf.span("s2k.joint_assignments"):
        translator.build_joint_assignments()
    with perf.span("s2k.materials"):
        translator.build_materials()
    with perf.span("s2k.frames"):
        translator.build_frames(translator.non_uniform_frames())
    with perf.span("s2k.areas"):
        translator.build_areas()
    with perf.span("s2k.diaphragms"):
        translator.build_diaphragms()
    with perf.span("s2k.patterns"):
        patterns = translator.build_patterns()
    with perf.span("s2k.cases"):
        extra, cases = translator.build_cases(patterns)
    with perf.span("s2k.combinations"):
        combinations = translator.build_combinations(cases)
    if translator.oblique:
        translator.notes.append(
            f"{translator.oblique} frame(s) with an unsymmetric section have local axes turned by "
            "an angle other than a multiple of 90° from OpenSees'; their section was imported "
            "with the nearest orientation."
        )
    if translator.ndm == 2:
        translator.notes.append(
            "Only UX, UZ and RY are active and every joint is at Y = 0: imported as a 2D frame."
        )
    grid = translator.grid()
    elements: list[Any] = [*translator.frames.values(), *translator.shells]
    try:
        project = Project(
            meta=ProjectMeta(
                name=s2k.path.stem,
                description=f"Imported from SAP2000 text ({s2k.path.name}, {source}).",
                units=target,
            ),
            ndm=translator.ndm,
            ndf=3 if translator.ndm == 2 else 6,
            coord_systems=[grid if grid is not None else default_global_system()],
            nodes=translator.nodes,
            sections=[*translator.sections],
            elements=elements,
            diaphragms=[*translator.diaphragms],
            time_series=[LinearTimeSeries(id=1, name="Linear")],
            load_patterns=[*patterns.values(), *extra],
            spectra=[*translator.spectra],
            analyses=[*cases],
            combinations=combinations,
        )
        with perf.span("s2k.nonprismatic"):
            materialization = materialize_nonprismatic(
                project, subdivisions=nonprismatic_subdivisions
            )
        if materialization.members:
            pieces = sorted(set(materialization.subdivisions.values()))
            piece_text = "/".join(str(n) for n in pieces) or "12"
            translator.notes.append(
                f"{materialization.members} nonprismatic frame(s) subdivided into "
                f"{materialization.elements} elastic elements ({piece_text} pieces per "
                "member). The subdivision count can be edited in Define > Section Library; "
                "members already subdivided keep the number of pieces they were built with."
            )
        with perf.span("s2k.validate"):
            project.validate_references()
    except (ValidationError, ValueError) as exc:
        detail = _first_error(exc) if isinstance(exc, ValidationError) else str(exc)
        raise Sap2000TextError(f"{s2k.path.name} does not make a valid project: {detail}") from exc
    perf.gauge("s2k.nodes", len(project.nodes))
    perf.gauge("s2k.elements", len(project.elements))
    perf.gauge("s2k.sections", len(project.sections))
    perf.gauge("s2k.load_patterns", len(project.load_patterns))
    perf.gauge("s2k.analyses", len(project.analyses))
    return Sap2000Import(
        project=project,
        source_units=source,
        scale=translator.scale,
        notes=translator.notes,
        dropped=translator.dropped,
        unsupported_tables=s2k.unsupported(),
    )


def import_s2k(
    path: str | Path,
    *,
    units: UnitSystem | None = None,
    source_units: str | None = None,
    nonprismatic_subdivisions: int | None = None,
) -> Sap2000Import:
    """:func:`read_s2k` then :func:`s2k_to_project`."""
    return s2k_to_project(
        read_s2k(path),
        units=units,
        source_units=source_units,
        nonprismatic_subdivisions=nonprismatic_subdivisions,
    )


# ──────────────────────────── writing ────────────────────────────
@dataclass
class Sap2000Export:
    """What an export wrote and what it had to leave out."""

    path: Path | None
    written: Counter[str] = field(default_factory=Counter)
    skipped: Counter[str] = field(default_factory=Counter)

    def summary(self) -> str:
        parts = [f"{count} {what}" for what, count in self.written.items() if count]
        text = "Wrote " + (", ".join(parts) if parts else "an empty model") + "."
        if self.skipped:
            items = ", ".join(f"{count} {what}" for what, count in sorted(self.skipped.items()))
            text += f" Not written (no counterpart in this export): {items}."
        return text


def _fmt(value: float) -> str:
    """Shortest text that reads back as the same double."""
    if value == 0:
        return "0"
    return repr(float(value))


def _quote(text: str) -> str:
    return f'"{text}"' if (not text or any(c.isspace() for c in text) or "=" in text) else text


class _Names:
    """Distinct names in one SAP2000 namespace (no quotes, at most 80 characters)."""

    def __init__(self) -> None:
        self.used: set[str] = set()

    def take(self, wanted: str, fallback: str) -> str:
        base = (wanted or fallback).replace('"', "'").strip()[:72] or fallback
        name, k = base, 2
        while name.upper() in self.used:
            name = f"{base} ({k})"
            k += 1
        self.used.add(name.upper())
        return name


class _Writer:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.report = Sap2000Export(path=None)
        self.lines: list[str] = []

    def table(self, name: str, rows: list[list[tuple[str, str]]]) -> None:
        if not rows:
            return
        self.lines.append(f'TABLE:  "{name}"')
        for row in rows:
            self.lines.append("   " + "   ".join(f"{k}={v}" for k, v in row))

    def write(self) -> str:
        p = self.project
        ndm = p.ndm
        self.lines.append("File written by OpenSees Studio in the SAP2000 text table format")
        self.lines.append("")
        self.table(
            "PROGRAM CONTROL",
            [[("ProgramName", "SAP2000"), ("CurrUnits", _quote(_WRITE_UNITS[p.meta.units]))]],
        )
        planar = [
            ("UX", "Yes"),
            ("UY", "No"),
            ("UZ", "Yes"),
            ("RX", "No"),
            ("RY", "Yes"),
            ("RZ", "No"),
        ]
        self.table(
            "ACTIVE DEGREES OF FREEDOM",
            [planar if ndm == 2 else [(k, "Yes") for k in ("UX", "UY", "UZ", "RX", "RY", "RZ")]],
        )
        self._grid()
        points = {n.id: np.array([float(c) for c in n.coords]) for n in p.nodes}
        self.table(
            "JOINT COORDINATES",
            [
                [
                    ("Joint", str(n.id)),
                    ("CoordSys", "GLOBAL"),
                    ("CoordType", "Cartesian"),
                    ("XorR", _fmt(n.coords[0])),
                    ("Y", _fmt(n.coords[1])),
                    ("Z", _fmt(n.coords[2])),
                ]
                for n in p.nodes
            ],
        )
        self.report.written["joint(s)"] = len(p.nodes)
        self.table(
            "JOINT RESTRAINT ASSIGNMENTS",
            [
                [("Joint", str(n.id))]
                + [(k, "Yes" if r else "No") for k, r in zip(_DOF_KEYS, n.restraint, strict=True)]
                for n in p.nodes
                if any(n.restraint)
            ],
        )
        mass_rows = [
            [("Joint", str(n.id)), ("CoordSys", _quote("Joint Local"))]
            + [(key, _fmt(value)) for key, value in zip(_MASS_KEYS, n.mass, strict=True)]
            for n in p.nodes
            if any(n.mass)
        ]
        self.table("JOINT ADDED MASS ASSIGNMENTS", mass_rows)
        spring_rows = [
            [("Joint", str(n.id)), ("CoordSys", "Local")]
            + [(key, _fmt(value)) for key, value in zip(_SPRING_KEYS, n.spring, strict=True)]
            for n in p.nodes
            if n.has_spring
        ]
        self.table("JOINT SPRING ASSIGNMENTS 1 - UNCOUPLED", spring_rows)
        self.report.written["joint mass"] = len(mass_rows)
        self.report.written["joint spring"] = len(spring_rows)

        sections = {s.id: s for s in p.sections}
        frames = [
            e
            for e in p.elements
            if isinstance(e, ElasticBeamColumn)
            and isinstance(sections.get(e.section_id), ElasticSection)
        ]
        shells = [
            e
            for e in p.elements
            if isinstance(e, ShellMITC4Element)
            and isinstance(sections.get(e.section_id), ElasticMembranePlateSection)
        ]
        written = {e.id for e in frames} | {e.id for e in shells}
        for e in p.elements:
            if e.id not in written:
                self.report.skipped[f"{e.type} element"] += 1

        materials = _Names()
        material_rows: dict[tuple[float, ...], str] = {}

        def material(e: float, g: float, nu: float, weight: float, mass: float) -> str:
            key = (e, g, nu, weight, mass)
            if key not in material_rows:
                material_rows[key] = materials.take(f"MAT{len(material_rows) + 1}", "MAT")
            return material_rows[key]

        section_names = _Names()
        frame_sections: dict[tuple[int, str], str] = {}
        section_rows: list[list[tuple[str, str]]] = []
        assignments: list[list[tuple[str, str]]] = []
        angles: list[list[tuple[str, str]]] = []
        releases: list[list[tuple[str, str]]] = []
        partial: list[list[tuple[str, str]]] = []
        modifier_rows: list[list[tuple[str, str]]] = []
        connectivity: list[list[tuple[str, str]]] = []
        frame_axes: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        os_axes: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        for el in frames:
            sec = sections[el.section_id]
            assert isinstance(sec, ElasticSection)
            p_i, p_j = points[el.nodes[0]], points[el.nodes[1]]
            g = sec.G or sec.E / 2.6
            mass = float(f"{el.rho / sec.A:.12g}")  # one material for equal densities
            mat = material(sec.E, g, sec.E / (2 * g) - 1, sec.unit_weight, mass)
            key = (sec.id, mat)
            if key not in frame_sections:
                frame_sections[key] = section_names.take(sec.name, f"FSEC{sec.id}")
                section_rows.append(self._section_row(frame_sections[key], mat, sec, ndm))
            connectivity.append(
                [
                    ("Frame", str(el.id)),
                    ("JointI", str(el.nodes[0])),
                    ("JointJ", str(el.nodes[1])),
                    ("IsCurved", "No"),
                ]
            )
            assignments.append(
                [
                    ("Frame", str(el.id)),
                    ("SectionType", "General"),
                    ("AutoSelect", "N.A."),
                    ("AnalSect", _quote(frame_sections[key])),
                    ("MatProp", "Default"),
                ]
            )
            angle = writer_angle(ndm, p_i, p_j)
            if angle:
                angles.append(
                    [("Frame", str(el.id)), ("Angle", _fmt(angle)), ("AdvanceAxes", "No")]
                )
            frame_axes[el.id] = sap_local_axes(p_i, p_j, angle)
            axes = frame_local_axes(ndm, p_i.tolist(), p_j.tolist())
            assert axes is not None
            os_axes[el.id] = axes
            if el.releases.any:
                row, springs = self._release_rows(el, frame_axes[el.id], axes)
                releases.append(row)
                if springs:
                    partial.append(springs)
            if not el.modifiers.is_default():
                modifier_rows.append(self._modifier_row(el, frame_axes[el.id], axes))
            for option in ("end_offsets", "insertion"):
                if not getattr(el, option).is_default():
                    self.report.skipped[f"frame {option.replace('_', ' ')}"] += 1
            if el.consistent_mass:
                self.report.skipped["consistent mass flag"] += 1
            if el.geom_transf != "Linear":
                self.report.skipped[f"{el.geom_transf} transformation"] += 1

        area_sections: dict[tuple[int, str], str] = {}
        area_rows: list[list[tuple[str, str]]] = []
        area_connectivity: list[list[tuple[str, str]]] = []
        area_assign: list[list[tuple[str, str]]] = []
        area_names = _Names()
        for shell in shells:
            sec = sections[shell.section_id]
            assert isinstance(sec, ElasticMembranePlateSection)
            mat = material(sec.E, sec.E / (2 * (1 + sec.nu)), sec.nu, sec.unit_weight, sec.rho)
            key = (sec.id, mat)
            if key not in area_sections:
                area_sections[key] = area_names.take(sec.name, f"ASEC{sec.id}")
                area_rows.append(
                    [
                        ("Section", _quote(area_sections[key])),
                        ("Material", mat),
                        ("MatAngle", "0"),
                        ("AreaType", "Shell"),
                        ("Type", "Shell-Thick"),
                        ("DrillDOF", "Yes"),
                        ("Thickness", _fmt(sec.h)),
                        ("BendThick", _fmt(sec.h)),
                    ]
                )
            area_connectivity.append(
                [("Area", str(shell.id)), ("NumJoints", "4")]
                + [(f"Joint{k}", str(n)) for k, n in enumerate(shell.nodes, start=1)]
            )
            area_assign.append(
                [
                    ("Area", str(shell.id)),
                    ("Section", _quote(area_sections[key])),
                    ("MatProp", "Default"),
                ]
            )

        diaphragm_rows: list[list[tuple[str, str]]] = []
        diaphragm_assignments: list[list[tuple[str, str]]] = []
        diaphragm_names = _Names()
        for diaphragm in p.diaphragms:
            constrained = constrained_node_ids(p, diaphragm)
            if not constrained:
                self.report.skipped["empty rigid diaphragm"] += 1
                continue
            name = diaphragm_names.take(diaphragm.name, f"DIAPH{diaphragm.id}")
            diaphragm_rows.append(
                [
                    ("Name", _quote(name)),
                    ("CoordSys", "GLOBAL"),
                    ("Axis", {1: "X", 2: "Y", 3: "Z"}[diaphragm.perp_dirn]),
                    ("MultiLevel", "No"),
                ]
            )
            for nid in sorted({diaphragm.retained_node, *constrained}):
                diaphragm_assignments.append([("Joint", str(nid)), ("Constraint", _quote(name))])

        self.table(
            "MATERIAL PROPERTIES 01 - GENERAL",
            [
                [("Material", name), ("Type", "Other"), ("SymType", "Isotropic")]
                for name in material_rows.values()
            ],
        )
        self.table(
            "MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES",
            [
                [
                    ("Material", name),
                    ("UnitWeight", _fmt(w)),
                    ("UnitMass", _fmt(m)),
                    ("E1", _fmt(e)),
                    ("G12", _fmt(g)),
                    ("U12", _fmt(nu)),
                    ("A1", "0"),
                ]
                for (e, g, nu, w, m), name in material_rows.items()
            ],
        )
        self.table("FRAME SECTION PROPERTIES 01 - GENERAL", section_rows)
        self.table("AREA SECTION PROPERTIES", area_rows)
        self.table("CONNECTIVITY - FRAME", connectivity)
        self.table("FRAME SECTION ASSIGNMENTS", assignments)
        self.table("FRAME PROPERTY MODIFIERS", modifier_rows)
        self.table("FRAME LOCAL AXES ASSIGNMENTS 1 - TYPICAL", angles)
        self.table("FRAME RELEASE ASSIGNMENTS 1 - GENERAL", releases)
        self.table("FRAME RELEASE ASSIGNMENTS 2 - PARTIAL FIXITY", partial)
        self.table("CONNECTIVITY - AREA", area_connectivity)
        self.table("AREA SECTION ASSIGNMENTS", area_assign)
        self.table("CONSTRAINT DEFINITIONS - DIAPHRAGM", diaphragm_rows)
        self.table("JOINT CONSTRAINT ASSIGNMENTS", diaphragm_assignments)
        self.report.written["frame(s)"] = len(frames)
        self.report.written["frame property modifier(s)"] = len(modifier_rows)
        self.report.written["shell(s)"] = len(shells)
        self.report.written["rigid diaphragm(s)"] = len(diaphragm_rows)
        self.report.written["section(s)"] = len(section_rows) + len(area_rows)
        self._loads(set(frame_axes), frame_axes, os_axes)
        for what, items in (
            ("rigid link", p.rigid_links),
            ("equalDOF constraint", p.mp_constraints),
        ):
            if items:
                self.report.skipped[what] += len(items)
        if p.mass_source is not None:
            # SAP2000's mass source can be written, but this writer does not model it:
            # say so instead of exporting a project whose mass changed silently.
            self.report.skipped["mass source"] += 1
        self.lines.append("")
        self.lines.append("END TABLE DATA")
        return "\n".join(self.lines) + "\n"

    def _grid(self) -> None:
        cs = next((c for c in self.project.coord_systems if c.name == "Global"), None)
        if cs is None:
            return
        rows = []
        for axis, lines in (
            ("X", cs.grid.x_grid_lines),
            ("Y", cs.grid.y_grid_lines),
            ("Z", cs.grid.z_grid_lines),
        ):
            for line in lines:
                rows.append(
                    [
                        ("CoordSys", "GLOBAL"),
                        ("AxisDir", axis),
                        ("GridID", _quote(line.id)),
                        ("XRYZCoord", _fmt(line.ordinate)),
                        ("LineType", "Primary"),
                        ("Visible", "Yes"),
                    ]
                )
        self.table("GRID LINES", rows)

    def _section_row(
        self, name: str, mat: str, sec: ElasticSection, ndm: int
    ) -> list[tuple[str, str]]:
        # Written with SAP2000's local 2 on OpenSees' z (3D) or y (2D): see writer_angle.
        iz, iy = sec.Iz, sec.Iy or sec.Iz
        if ndm == 2:
            i33, i22, as2, as3 = iz, iy, sec.As2 or 0.0, sec.As2 or 0.0
        else:
            i33, i22, as2, as3 = iy, iz, sec.As3 or 0.0, sec.As2 or 0.0
        if not sec.has_shear_deformation:
            as2 = as3 = 0.0
        j = sec.J or (iz + iy)
        shape = sec.shape
        dims: list[tuple[str, str]]
        if isinstance(shape, RectShape):
            kind, dims = "Rectangular", [("t3", _fmt(shape.d)), ("t2", _fmt(shape.b))]
        elif isinstance(shape, WideFlangeShape):
            kind, dims = (
                "I/Wide Flange",
                [
                    ("t3", _fmt(shape.d)),
                    ("t2", _fmt(shape.bf)),
                    ("tf", _fmt(shape.tf)),
                    ("tw", _fmt(shape.tw)),
                    ("t2b", _fmt(shape.bf)),
                    ("tfb", _fmt(shape.tf)),
                ],
            )
        elif isinstance(shape, PipeShape):
            kind, dims = "Pipe", [("t3", _fmt(shape.od)), ("tw", _fmt(shape.t))]
        elif isinstance(shape, TubeShape):
            kind, dims = (
                "Box/Tube",
                [
                    ("t3", _fmt(shape.d)),
                    ("t2", _fmt(shape.b)),
                    ("tf", _fmt(shape.t)),
                    ("tw", _fmt(shape.t)),
                ],
            )
        else:
            kind = "General"
            dims = [
                ("t3", _fmt(math.sqrt(12 * i33 / sec.A))),
                ("t2", _fmt(math.sqrt(12 * i22 / sec.A))),
            ]
        return [
            ("SectionName", _quote(name)),
            ("Material", mat),
            ("Shape", _quote(kind)),
            *dims,
            ("Area", _fmt(sec.A)),
            ("TorsConst", _fmt(j)),
            ("I33", _fmt(i33)),
            ("I22", _fmt(i22)),
            ("AS2", _fmt(as2)),
            ("AS3", _fmt(as3)),
        ]

    def _release_rows(
        self, el: ElasticBeamColumn, sap: tuple[np.ndarray, ...], ours: tuple[np.ndarray, ...]
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        # Our M2/M3 are about OpenSees y/z; find which SAP2000 axis each lies on.
        about = {"T": "T", "M2": "M2" if abs(float(np.dot(ours[1], sap[1]))) > 0.5 else "M3"}
        about["M3"] = "M3" if about["M2"] == "M2" else "M2"
        row: list[tuple[str, str]] = [("Frame", str(el.id))]
        springs: list[tuple[str, str]] = [("Frame", str(el.id))]
        any_spring = False
        for end, release in (("I", el.releases.i), ("J", el.releases.j)):
            sap_released = {about[r] for r in release.released}
            for dof in ("P", "V2", "V3", "T", "M2", "M3"):
                row.append((f"{dof}{end}", "Yes" if dof in sap_released else "No"))
            for dof in ("P", "V2", "V3", "T", "M2", "M3"):
                ours_dof = next((r for r in release.released if about[r] == dof), None)
                k = release.spring(ours_dof) if ours_dof else 0.0
                any_spring = any_spring or k > 0
                springs.append((f"{dof}{end}", _fmt(k)))
        row.append(("PartialFix", "Yes" if any_spring else "No"))
        return row, springs if any_spring else []

    def _modifier_row(
        self,
        el: ElasticBeamColumn,
        sap: tuple[np.ndarray, ...],
        ours: tuple[np.ndarray, ...],
    ) -> list[tuple[str, str]]:
        """SAP2000's per-frame property-modifier row, with the axes swapped as needed."""
        mods = el.modifiers
        two_on_y = abs(float(np.dot(ours[1], sap[1]))) > 0.5
        return [
            ("Frame", str(el.id)),
            ("AMod", _fmt(mods.area)),
            ("AS2Mod", _fmt(mods.as2 if two_on_y else mods.as3)),
            ("AS3Mod", _fmt(mods.as3 if two_on_y else mods.as2)),
            ("JMod", _fmt(mods.torsion)),
            ("I22Mod", _fmt(mods.i22 if two_on_y else mods.i33)),
            ("I33Mod", _fmt(mods.i33 if two_on_y else mods.i22)),
            ("MassMod", _fmt(mods.mass)),
            ("WeightMod", _fmt(mods.weight)),
        ]

    def _loads(
        self,
        frames: set[int],
        sap_axes: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]],
        os_axes: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]],
    ) -> None:
        p = self.project
        names = _Names()
        pattern_names: dict[int, str] = {}
        definitions, joint_loads, distributed, point = [], [], [], []

        def local_rows(element_id: int, w: tuple[float, float, float]) -> list[tuple[str, float]]:
            """Our local (x, y, z) components as SAP2000 local directions (1, 2, 3)."""
            vector = sum(c * a for c, a in zip(w, os_axes[element_id], strict=True))
            out = []
            for k, axis in enumerate(sap_axes[element_id], start=1):
                value = float(np.dot(vector, axis))
                if abs(value) > 1e-15 * max(1.0, *(abs(c) for c in w)):
                    out.append((str(k), value))
            return out

        for pattern in p.load_patterns:
            if not isinstance(pattern, PlainLoadPattern):
                self.report.skipped[f"{pattern.type} load pattern"] += 1
                continue
            name = names.take(pattern.name, f"LP{pattern.id}")
            pattern_names[pattern.id] = name
            definitions.append(
                [
                    ("LoadPat", _quote(name)),
                    ("DesignType", "Dead" if pattern.self_weight else "Other"),
                    ("SelfWtMult", _fmt(pattern.self_weight)),
                ]
            )
            for load in pattern.nodal_loads:
                joint_loads.append(
                    [
                        ("Joint", str(load.node_id)),
                        ("LoadPat", _quote(name)),
                        ("CoordSys", "GLOBAL"),
                    ]
                    + [(k, _fmt(v)) for k, v in zip(_FORCE_KEYS, load.forces, strict=True)]
                )
            uniform = [
                (u.element_id, 0.0, 1.0, (u.wx, u.wy, u.wz), (u.wx, u.wy, u.wz))
                for u in pattern.element_loads
            ]
            varying = [
                (d.element_id, d.x_start, d.x_end, d.start(), d.end())
                for d in pattern.distributed_loads
            ]
            for element_id, a, b, w_a, w_b in uniform + varying:
                if element_id not in frames:
                    self.report.skipped["frame load on an element not written"] += 1
                    continue
                at_a = dict(local_rows(element_id, w_a))
                at_b = dict(local_rows(element_id, w_b))
                for direction in sorted(set(at_a) | set(at_b)):
                    distributed.append(
                        [
                            ("Frame", str(element_id)),
                            ("LoadPat", _quote(name)),
                            ("CoordSys", "Local"),
                            ("Type", "Force"),
                            ("Dir", direction),
                            ("DistType", "RelDist"),
                            ("RelDistA", _fmt(a)),
                            ("RelDistB", _fmt(b)),
                            ("FOverLA", _fmt(at_a.get(direction, 0.0))),
                            ("FOverLB", _fmt(at_b.get(direction, 0.0))),
                        ]
                    )
            for point_load in pattern.point_loads:
                if point_load.element_id not in frames:
                    self.report.skipped["frame load on an element not written"] += 1
                    continue
                for direction, value in local_rows(
                    point_load.element_id, (point_load.px, point_load.py, point_load.pz)
                ):
                    point.append(
                        [
                            ("Frame", str(point_load.element_id)),
                            ("LoadPat", _quote(name)),
                            ("CoordSys", "Local"),
                            ("Type", "Force"),
                            ("Dir", direction),
                            ("DistType", "RelDist"),
                            ("RelDist", _fmt(point_load.x)),
                            ("Force", _fmt(value)),
                        ]
                    )
            for what, items in (
                ("surface load", pattern.surface_loads),
                ("floor load", pattern.floor_loads),
                ("imposed displacement", pattern.imposed_displacements),
                ("temperature load", pattern.temperature_loads),
            ):
                if items:
                    self.report.skipped[what] += len(items)
        self.table("LOAD PATTERN DEFINITIONS", definitions)
        self.table("JOINT LOADS - FORCE", joint_loads)
        self.table("FRAME LOADS - DISTRIBUTED", distributed)
        self.table("FRAME LOADS - POINT", point)
        self.report.written["load pattern(s)"] = len(definitions)

        spectrum_names = _Names()
        spectrum_of = {
            spectrum.id: spectrum_names.take(spectrum.name, f"RS{spectrum.id}")
            for spectrum in p.spectra
        }
        gravity_value = gravity(p.meta.units)
        spectrum_rows: list[list[tuple[str, str]]] = []
        for spectrum in p.spectra:
            name = spectrum_of[spectrum.id]
            for period, accel in zip(spectrum.periods, spectrum.accelerations, strict=True):
                spectrum_rows.append(
                    [
                        ("Name", _quote(name)),
                        ("Period", _fmt(period)),
                        # Back to g; 12 significant digits keep a second export identical.
                        ("Accel", _fmt(float(f"{accel / gravity_value:.12g}"))),
                        ("FuncDamp", _fmt(spectrum.damping_ratio)),
                    ]
                )
        self.table("FUNCTION - RESPONSE SPECTRUM - USER", spectrum_rows)
        self.report.written["response spectrum(s)"] = len(p.spectra)

        # Name every case first: a spectrum case refers to its modal case by id, and
        # that case may be written after it.
        case_names = _Names()
        case_of = {case.id: case_names.take(case.name, f"CASE{case.id}") for case in p.analyses}
        by_id = {case.id: case for case in p.analyses}
        cases, assignments = [], []
        modal_rows: list[list[tuple[str, str]]] = []
        spectrum_general: list[list[tuple[str, str]]] = []
        spectrum_loads: list[list[tuple[str, str]]] = []
        static_cases = 0
        spectra_by_id = {spectrum.id: spectrum for spectrum in p.spectra}
        for case in p.analyses:
            if isinstance(case, ResponseSpectrumCase):
                name = case_of[case.id]
                spectrum_name = spectrum_of.get(case.spectrum_id)
                modal = by_id.get(case.modal_case_id)
                if spectrum_name is None or not isinstance(modal, ModalCase):
                    self.report.skipped[
                        "spectrum case on a spectrum or modal case not written"
                    ] += 1
                    continue
                entry = spectra_by_id.get(case.spectrum_id)
                damping = (
                    case.damping_ratio
                    if case.damping_ratio is not None
                    else (entry.damping_ratio if entry is not None else 0.05)
                )
                cases.append(
                    [
                        ("Case", _quote(name)),
                        ("Type", "LinRespSpec"),
                        ("RunCase", "Yes"),
                    ]
                )
                spectrum_general.append(
                    [
                        ("Case", _quote(name)),
                        ("ModalCombo", _quote(case.combination)),
                        ("GMCf1", "1"),
                        ("GMCf2", "0"),
                        ("PerRigid", "SRSS"),
                        ("DirCombo", "SRSS"),
                        ("ConstDamp", _fmt(damping)),
                        ("EccenRatio", "0"),
                    ]
                )
                spectrum_loads.append(
                    [
                        ("Case", _quote(name)),
                        ("LoadName", _DOF_KEYS[case.direction - 1]),
                        ("CoordSys", "GLOBAL"),
                        ("Function", _quote(spectrum_name)),
                        ("Angle", "0"),
                        ("TransAccSF", _fmt(gravity_value)),
                    ]
                )
                continue
            if isinstance(case, ModalCase):
                name = case_of[case.id]
                cases.append(
                    [
                        ("Case", _quote(name)),
                        ("Type", "LinModal"),
                        ("InitialCond", "Zero"),
                        ("RunCase", "Yes"),
                    ]
                )
                modal_rows.append(
                    [
                        ("Case", _quote(name)),
                        ("ModeType", "Eigen"),
                        ("MaxNumModes", str(case.n_modes)),
                        ("MinNumModes", "1"),
                        ("EigenShift", "0"),
                        ("EigenCutoff", "0"),
                        ("EigenTol", "1E-09"),
                        ("AutoShift", "Yes"),
                    ]
                )
                continue
            if not (
                isinstance(case, StaticCase) and case.n_steps == 1 and case.algorithm == "Linear"
            ):
                self.report.skipped[f"{case.type} analysis case"] += 1
                continue
            if not all(pid in pattern_names for pid in case.pattern_ids):
                self.report.skipped["static case on a pattern not written"] += 1
                continue
            name = case_of[case.id]
            static_cases += 1
            initial = "Zero"
            if case.preload_case_ids:
                preload = by_id.get(case.preload_case_ids[0])
                if (
                    isinstance(preload, StaticCase)
                    and preload.n_steps == 1
                    and preload.algorithm == "Linear"
                ):
                    initial = case_of[preload.id]
                else:
                    self.report.skipped["static case on a preload not written"] += 1
            cases.append(
                [
                    ("Case", _quote(name)),
                    ("Type", "LinStatic"),
                    ("InitialCond", _quote(initial)),
                    ("RunCase", "Yes"),
                ]
            )
            for pid in case.pattern_ids:
                assignments.append(
                    [
                        ("Case", _quote(name)),
                        ("LoadType", '"Load pattern"'),
                        ("LoadName", _quote(pattern_names[pid])),
                        ("LoadSF", "1"),
                    ]
                )
        self.table("LOAD CASE DEFINITIONS", cases)
        self.table("CASE - STATIC 1 - LOAD ASSIGNMENTS", assignments)
        self.table("CASE - MODAL 1 - GENERAL", modal_rows)
        self.table("CASE - RESPONSE SPECTRUM 1 - GENERAL", spectrum_general)
        self.table("CASE - RESPONSE SPECTRUM 2 - LOAD ASSIGNMENTS", spectrum_loads)
        self.report.written["static case(s)"] = static_cases
        self.report.written["modal case(s)"] = len(modal_rows)
        self.report.written["response spectrum case(s)"] = len(spectrum_general)

        combo_of: dict[int, str] = {}
        for combination in p.combinations:
            combo_of[combination.id] = case_names.take(combination.name, f"COMB{combination.id}")
        rows = []
        for combination in p.combinations:
            first = True
            terms = []
            for term in combination.terms:
                ref = (case_of if term.source == "case" else combo_of).get(term.ref_id)
                if ref is None:
                    self.report.skipped["combination term on a case not written"] += 1
                    continue
                kind = "Linear Static" if term.source == "case" else "Response Combo"
                terms.append((ref, kind, term.factor))
            for ref, kind, factor in terms:
                row = [("ComboName", _quote(combo_of[combination.id]))]
                if first:
                    row.append(("ComboType", _quote(_COMBO_NAMES[combination.combination_type])))
                    first = False
                row += [
                    ("CaseType", _quote(kind)),
                    ("CaseName", _quote(ref)),
                    ("ScaleFactor", _fmt(factor)),
                ]
                rows.append(row)
        self.table("COMBINATION DEFINITIONS", rows)
        self.report.written["combination(s)"] = len({r[0][1] for r in rows})


def project_to_s2k(project: Project) -> tuple[str, Sap2000Export]:
    """The SAP2000 text of ``project`` (in its own units) and what was left out."""
    writer = _Writer(project)
    return writer.write(), writer.report


def export_s2k(project: Project, path: str | Path) -> Sap2000Export:
    """Write ``project`` to ``path`` as SAP2000 text.

    Raises:
        Sap2000TextError: when the file cannot be written.
    """
    from opensees_studio.services.persistence import _write_text_atomic

    target = Path(path)
    text, report = project_to_s2k(project)
    try:
        _write_text_atomic(target, text)
    except OSError as exc:
        raise Sap2000TextError(f"Could not write {target}: {exc}") from exc
    report.path = target
    return report
