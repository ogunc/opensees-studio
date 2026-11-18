"""Import a model from an OpenSees Tcl script.

OpenSees' native input is Tcl (or Python). The application models and runs
OpenSees through its typed :mod:`opensees_studio.core` model, so this module
translates the model-building part of a ``.tcl`` script into that model:

* nodes, restraints, masses, equalDOF, rigid links and diaphragms;
* uniaxial and isotropic materials, elastic and fibre sections, plate sections;
* truss, elastic, force-based, displacement-based, zero-length, quad and
  ``ShellMITC4`` elements;
* plain load patterns with nodal, uniform and point element loads, and the
  time series they reference.

Analysis commands (``system``, ``integrator``, ``analyze``, recorders …) are
not imported: the GUI defines and runs its own cases. Unsupported commands are
counted and reported instead of aborting the import.

The script is *interpreted*, not executed: only a safe subset of Tcl is
understood (``set``, ``expr``, ``foreach``, ``if``, ``proc``, ``source`` and
command substitution), and no shell, file or network command is ever run.
"""

from __future__ import annotations

import ast
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import ValidationError

from opensees_studio.core import (
    BeamWithHingesElement,
    CircularPatch,
    Concrete01,
    Concrete02,
    Concrete04,
    ConstantTimeSeries,
    CorotTrussElement,
    DispBeamColumn,
    ElasticBeamColumn,
    ElasticIsotropic,
    ElasticMembranePlateSection,
    ElasticPP,
    ElasticSection,
    ElasticUniaxial,
    EqualDOFConstraint,
    FiberSection,
    Fibre,
    ForceBeamColumn,
    Hardening,
    HystereticMaterial,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PathTimeSeries,
    PlainLoadPattern,
    PointElementLoad,
    Project,
    ProjectMeta,
    QuadElement,
    RectangularPatch,
    RigidDiaphragm,
    RigidLink,
    ShellMITC4Element,
    Steel01,
    Steel02,
    StraightLayer,
    TrigTimeSeries,
    TrussElement,
    UniformElementLoad,
    UnitSystem,
    ZeroLengthElement,
    ZeroLengthSectionElement,
    default_global_system,
)

#: Label the dialog and the log use for the file's own units.
TCL_SOURCE = "OpenSees Tcl"

_GeomTransf = Literal["Linear", "PDelta", "Corotational"]

#: Commands that only drive an analysis; the GUI has its own cases.
_ANALYSIS_COMMANDS = frozenset(
    {
        "algorithm",
        "analyze",
        "constraints",
        "eigen",
        "integrator",
        "loadConst",
        "modalDamping",
        "numberer",
        "printA",
        "rayleigh",
        "recorder",
        "remove",
        "reset",
        "system",
        "test",
        "wipeAnalysis",
    }
)

#: Commands that write to the terminal or ask the solver something.
_QUERY_COMMANDS = frozenset({"getTime", "print", "puts", "nodeDisp", "nodeReaction"})

_UNSUPPORTED_MESH = frozenset({"block3D"})

#: Tcl operators Python spells differently.
_OPERATOR_WORDS = (
    (re.compile(r"\beq\b"), "=="),
    (re.compile(r"\bne\b"), "!="),
    (re.compile(r"\btrue\b"), "1"),
    (re.compile(r"\bfalse\b"), "0"),
)


class TclImportError(ValueError):
    """The file cannot be read or its Tcl syntax is broken."""


@dataclass
class TclImport:
    """The translated project and what the reader had to leave out."""

    project: Project
    path: Path
    notes: list[str] = field(default_factory=list)
    ignored: Counter[str] = field(default_factory=Counter)
    dropped: Counter[str] = field(default_factory=Counter)
    source_units: str = TCL_SOURCE

    def summary(self) -> str:
        project = self.project
        return (
            f"{len(project.nodes)} node(s), {len(project.elements)} element(s), "
            f"{len(project.materials)} material(s), {len(project.sections)} section(s), "
            f"{len(project.load_patterns)} load pattern(s)"
        )


# ─────────────────────────── script lexer ───────────────────────────


@dataclass(frozen=True)
class _Word:
    """One Tcl word. Braced words are taken literally; the rest are expanded."""

    text: str
    braced: bool = False


class _Lexer:
    """Split a Tcl script into commands, following Tcl's brace/quote rules."""

    def __init__(self, text: str, source: str) -> None:
        self._text = text
        self._source = source
        self._pos = 0

    def commands(self) -> list[list[_Word]]:
        out: list[list[_Word]] = []
        while True:
            self._skip_separators()
            if self._pos >= len(self._text):
                return out
            words: list[_Word] = []
            while True:
                self._skip_inline_space()
                if self._pos >= len(self._text) or self._text[self._pos] in "\n;":
                    break
                words.append(self._read_word())
            if words:
                out.append(words)

    def _skip_separators(self) -> None:
        while self._pos < len(self._text):
            char = self._text[self._pos]
            if char in " \t\r\n;":
                self._pos += 1
            elif char == "#":
                end = self._text.find("\n", self._pos)
                self._pos = len(self._text) if end < 0 else end + 1
            else:
                return

    def _skip_inline_space(self) -> None:
        while self._pos < len(self._text) and self._text[self._pos] in " \t\r":
            self._pos += 1

    def _read_word(self) -> _Word:
        char = self._text[self._pos]
        if char == "{":
            return _Word(self._read_braced(), braced=True)
        if char == '"':
            return _Word(self._read_quoted())
        return _Word(self._read_bare())

    def _read_braced(self) -> str:
        start = self._pos
        self._pos += 1
        depth = 1
        while self._pos < len(self._text):
            char = self._text[self._pos]
            if char == "\\" and self._pos + 1 < len(self._text):
                self._pos += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    self._pos += 1
                    return self._text[start + 1 : self._pos - 1]
            self._pos += 1
        raise TclImportError(f"{self._source}: missing '}}' for the brace at offset {start}.")

    def _read_quoted(self) -> str:
        start = self._pos
        self._pos += 1
        while self._pos < len(self._text):
            char = self._text[self._pos]
            if char == "\\" and self._pos + 1 < len(self._text):
                self._pos += 2
                continue
            if char == '"':
                self._pos += 1
                return self._text[start + 1 : self._pos - 1]
            self._pos += 1
        raise TclImportError(f"{self._source}: missing '\"' for the quote at offset {start}.")

    def _read_bare(self) -> str:
        start = self._pos
        while self._pos < len(self._text):
            char = self._text[self._pos]
            if char == "\\" and self._pos + 1 < len(self._text):
                self._pos += 2
                continue
            if char == "[":
                self._pos = _matching(self._text, self._pos, "[", "]") + 1
                continue
            if char in " \t\r\n;":
                break
            self._pos += 1
        return self._text[start : self._pos]


def _matching(text: str, start: int, opening: str, closing: str) -> int:
    """Index of the ``closing`` that balances ``opening`` at ``start``.

    Inside ``[...]`` a braced string may contain a ``]`` and a quoted string
    may contain brackets, so both are skipped whole. Inside braces quotes are
    literal, which is why they are only special for the bracket case.
    """
    depth = 0
    quote = False
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if opening != "{":
            if quote:
                if char == '"':
                    quote = False
                index += 1
                continue
            if char == '"':
                quote = True
                index += 1
                continue
            if char == "{":
                index = _matching(text, index, "{", "}") + 1
                continue
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise TclImportError(f"unbalanced '{opening}' at offset {start}.")


def _split_list(text: str) -> list[str]:
    """A Tcl list as words, with braces and quotes removed."""
    words: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        while index < length and text[index] in " \t\r\n":
            index += 1
        if index >= length:
            break
        if text[index] == "{":
            end = _matching(text, index, "{", "}")
            words.append(text[index + 1 : end])
            index = end + 1
        elif text[index] == '"':
            start = index + 1
            index = start
            while index < length:
                if text[index] == "\\" and index + 1 < length:
                    index += 2
                    continue
                if text[index] == '"':
                    break
                index += 1
            words.append(text[start:index])
            index += 1
        else:
            start = index
            while index < length and text[index] not in " \t\r\n":
                if text[index] == "\\" and index + 1 < length:
                    index += 2
                    continue
                index += 1
            words.append(_unescape(text[start:index]))
    return words


def _unescape(text: str) -> str:
    escapes = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "$": "$", "[": "[", "]": "]"}
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            index += 1
            out.append(escapes.get(text[index], text[index]))
        else:
            out.append(char)
        index += 1
    return "".join(out)


# ─────────────────────────── expression evaluator ───────────────────────────


_ALLOWED_FUNCTIONS: dict[str, Any] = {
    "abs": abs,
    "acos": math.acos,
    "asin": math.asin,
    "atan": math.atan,
    "atan2": math.atan2,
    "ceil": math.ceil,
    "cos": math.cos,
    "cosh": math.cosh,
    "exp": math.exp,
    "floor": math.floor,
    "log": math.log,
    "log10": math.log10,
    "max": max,
    "min": min,
    "pow": pow,
    "sin": math.sin,
    "sinh": math.sinh,
    "sqrt": math.sqrt,
    "tan": math.tan,
    "tanh": math.tanh,
}

_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
)


def _arithmetic(text: str) -> str:
    """Evaluate the arithmetic subset of Tcl ``expr`` without ``eval``."""
    expression = text.strip()
    if not expression:
        return ""
    expression = expression.replace("^", "**")
    expression = re.sub(r"&&", " and ", expression)
    expression = re.sub(r"\|\|", " or ", expression)
    expression = re.sub(r"!(?!=)", " not ", expression)
    for pattern, replacement in _OPERATOR_WORDS:
        expression = pattern.sub(replacement, expression)
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return _string_expression(expression)
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            return _string_expression(expression)
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCTIONS
        ):
            return _string_expression(expression)
        if isinstance(node, ast.Name) and node.id not in _ALLOWED_FUNCTIONS:
            return _string_expression(expression)
    try:
        result = eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, _ALLOWED_FUNCTIONS)
    except (ArithmeticError, ValueError, TypeError):
        return _string_expression(expression)
    if isinstance(result, bool):
        return "1" if result else "0"
    if isinstance(result, float) and result.is_integer():
        return str(int(result))
    return str(result)


def _strip_quotes(text: str) -> str:
    value = text.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _string_expression(text: str) -> str:
    """Tcl conditions such as ``$kind == "quad"``, which mypy's grammar rejects."""
    expression = text.strip()
    for separator, want_all in (("||", False), ("&&", True)):
        if separator in expression:
            parts = [_truth(_arithmetic(part)) for part in expression.split(separator)]
            return "1" if (all(parts) if want_all else any(parts)) else "0"
    if expression.startswith("!") and not expression.startswith("!="):
        return "0" if _truth(_arithmetic(expression[1:])) else "1"
    match = re.match(r"^(.*?)\s*(==|!=|eq|ne)\s*(.*)$", expression)
    if match is None:
        return text.strip()
    left = _strip_quotes(match.group(1))
    right = _strip_quotes(match.group(3))
    try:
        equal = float(left) == float(right)
    except ValueError:
        equal = left == right
    positive = match.group(2) in {"==", "eq"}
    return "1" if equal == positive else "0"


def _truth(value: str) -> bool:
    try:
        return float(value) != 0.0
    except ValueError:
        return value.strip().lower() in {"true", "yes"}


def _is_on(value: str) -> bool:
    try:
        return float(value) != 0.0
    except ValueError:
        return value.strip().lower() in {"true", "yes"}


# ─────────────────────────── project builder ───────────────────────────


class _Builder:
    """The typed project being assembled, plus the tags the script uses."""

    def __init__(self, units: UnitSystem, path: Path) -> None:
        self.units = units
        self.path = path
        self.ndm = 3
        self.ndf = 6
        self.nodes: dict[int, Node] = {}
        self.restraints: dict[int, tuple[bool, bool, bool, bool, bool, bool]] = {}
        self.masses: dict[int, tuple[float, float, float, float, float, float]] = {}
        self.materials: dict[int, Any] = {}
        self.sections: dict[int, Any] = {}
        self.geom_transfs: dict[int, str] = {}
        self.elements: dict[int, Any] = {}
        self.time_series: dict[int, Any] = {}
        self.patterns: dict[int, PlainLoadPattern] = {}
        self.equal_dofs: list[EqualDOFConstraint] = []
        self.diaphragms: list[RigidDiaphragm] = []
        self.rigid_links: list[RigidLink] = []
        self._elastic_sections: dict[tuple[float, ...], int] = {}
        self.current_pattern: int | None = None
        self.notes: list[str] = []
        self._noted: set[str] = set()
        self._snapshot: dict[str, Any] | None = None
        self.dropped: Counter[str] = Counter()
        self.ignored: Counter[str] = Counter()

    # ── helpers ──────────────────────────────────────────────────────
    def note(self, text: str, *, key: str | None = None) -> None:
        """Add one note, at most once per ``key``."""
        token = key or text
        if token in self._noted:
            return
        self._noted.add(token)
        self.notes.append(text)

    def drop(self, reason: str) -> None:
        self.dropped[reason] += 1

    def ignore(self, command: str) -> None:
        self.ignored[command] += 1

    def wipe(self) -> None:
        if self.nodes:
            self._snapshot = {
                "ndm": self.ndm,
                "ndf": self.ndf,
                "nodes": dict(self.nodes),
                "restraints": dict(self.restraints),
                "masses": dict(self.masses),
                "materials": dict(self.materials),
                "sections": dict(self.sections),
                "geom_transfs": dict(self.geom_transfs),
                "elements": dict(self.elements),
                "time_series": dict(self.time_series),
                "patterns": dict(self.patterns),
                "equal_dofs": list(self.equal_dofs),
                "diaphragms": list(self.diaphragms),
                "rigid_links": list(self.rigid_links),
            }
        self.nodes.clear()
        self.restraints.clear()
        self.masses.clear()
        self.materials.clear()
        self.sections.clear()
        self.geom_transfs.clear()
        self.elements.clear()
        self.time_series.clear()
        self.patterns.clear()
        self.equal_dofs.clear()
        self.diaphragms.clear()
        self.rigid_links.clear()
        self.current_pattern = None

    def restore_last(self) -> None:
        """Bring back the model a trailing ``wipe`` erased."""
        snapshot = self._snapshot
        if snapshot is None:
            return
        self.ndm = snapshot["ndm"]
        self.ndf = snapshot["ndf"]
        self.nodes = dict(snapshot["nodes"])
        self.restraints = dict(snapshot["restraints"])
        self.masses = dict(snapshot["masses"])
        self.materials = dict(snapshot["materials"])
        self.sections = dict(snapshot["sections"])
        self.geom_transfs = dict(snapshot["geom_transfs"])
        self.elements = dict(snapshot["elements"])
        self.time_series = dict(snapshot["time_series"])
        self.patterns = dict(snapshot["patterns"])
        self.equal_dofs = list(snapshot["equal_dofs"])
        self.diaphragms = list(snapshot["diaphragms"])
        self.rigid_links = list(snapshot["rigid_links"])

    # ── geometry ─────────────────────────────────────────────────────
    def set_model(self, ndm: int, ndf: int) -> None:
        if (ndm, ndf) not in {(2, 1), (2, 2), (2, 3), (3, 3), (3, 6)}:
            raise TclImportError(f"Unsupported model: -ndm {ndm} -ndf {ndf}.")
        self.ndm = ndm
        self.ndf = ndf

    def coords(self, values: list[float]) -> tuple[float, float, float]:
        if self.ndm == 2:
            return (values[0], 0.0, values[1])
        return (values[0], values[1], values[2])

    def _node(
        self,
        tag: int,
        coords: tuple[float, float, float],
        restraint: tuple[bool, bool, bool, bool, bool, bool],
    ) -> Node:
        return Node(
            id=tag,
            coords=coords,
            restraint=restraint,
            mass=self.masses.get(tag, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
        )

    def add_node(self, tag: int, values: list[float], mass: list[float] | None) -> None:
        if tag <= 0:
            self.drop("node with a non-positive tag")
            return
        coords = self.coords(values)
        if mass is not None:
            self.masses[tag] = self.map_mass(mass)
        restraint = self.restraints.get(tag, (False, False, False, False, False, False))
        self.nodes[tag] = self._node(tag, coords, restraint)

    def map_restraint(self, flags: list[bool]) -> tuple[bool, bool, bool, bool, bool, bool]:
        slots = [False] * 6
        if self.ndm == 2:
            slots[0] = flags[0] if len(flags) > 0 else False
            slots[2] = flags[1] if len(flags) > 1 else False
            slots[4] = flags[2] if len(flags) > 2 else False
        else:
            for index, flag in enumerate(flags[: self.ndf]):
                slots[index] = flag
        return (slots[0], slots[1], slots[2], slots[3], slots[4], slots[5])

    def add_fix(self, tag: int, flags: list[bool]) -> None:
        restraint = self.map_restraint(flags)
        self.restraints[tag] = restraint
        if tag in self.nodes:
            node = self.nodes[tag]
            self.nodes[tag] = self._node(tag, node.coords, restraint)

    def map_mass(self, values: list[float]) -> tuple[float, float, float, float, float, float]:
        out = [0.0] * 6
        if self.ndm == 2:
            out[0] = values[0] if len(values) > 0 else 0.0
            out[2] = values[1] if len(values) > 1 else 0.0
            out[4] = values[2] if len(values) > 2 else 0.0
        else:
            for index, value in enumerate(values[:6]):
                out[index] = value
        return (out[0], out[1], out[2], out[3], out[4], out[5])

    def add_mass(self, tag: int, values: list[float]) -> None:
        mass = self.map_mass(values)
        self.masses[tag] = mass
        if tag in self.nodes:
            node = self.nodes[tag]
            self.nodes[tag] = Node(id=tag, coords=node.coords, restraint=node.restraint, mass=mass)

    # ── materials and sections ───────────────────────────────────────
    def add_material(self, tag: int, material: Any) -> None:
        if tag <= 0:
            self.drop("material with a non-positive tag")
            return
        self.materials[tag] = material

    def add_section(self, tag: int, section: Any) -> None:
        if tag <= 0:
            self.drop("section with a non-positive tag")
            return
        self.sections[tag] = section

    def elastic_section(
        self, e: float, area: float, iz: float, iy: float | None, g: float | None, j: float | None
    ) -> int:
        """Reuse (or create) the elastic section a raw elasticBeamColumn implies."""
        key = (e, area, iz, iy or 0.0, g or 0.0, j or 0.0)
        if key in self._elastic_sections:
            return self._elastic_sections[key]
        tag = 100_000 + len(self._elastic_sections) + 1
        while tag in self.sections:
            tag += 1
        self.sections[tag] = ElasticSection(id=tag, E=e, A=area, Iz=iz, Iy=iy, G=g, J=j)
        self._elastic_sections[key] = tag
        return tag

    # ── elements ─────────────────────────────────────────────────────
    def add_element(self, tag: int, element: Any, nodes: tuple[int, ...]) -> None:
        if tag <= 0:
            self.drop("element with a non-positive tag")
            return
        missing = [node for node in nodes if node not in self.nodes]
        if missing:
            self.drop(f"{element.type} with a missing node")
            return
        self.elements[tag] = element

    # ── loads ────────────────────────────────────────────────────────
    def ensure_pattern(self, tag: int | None = None, time_series_id: int = 1) -> PlainLoadPattern:
        if tag is None:
            tag = self.current_pattern
        if tag is None:
            tag = max(self.patterns, default=0) + 1
        if tag in self.patterns:
            return self.patterns[tag]
        if time_series_id not in self.time_series:
            self.time_series[time_series_id] = LinearTimeSeries(id=time_series_id)
        pattern = PlainLoadPattern(id=tag, name=f"Pattern {tag}", time_series_id=time_series_id)
        self.patterns[tag] = pattern
        self.current_pattern = tag
        return pattern

    def add_nodal_load(self, values: list[float], node: int) -> None:
        pattern = self.ensure_pattern()
        pattern.nodal_loads.append(NodalLoad(node_id=node, forces=self.map_load(values)))

    def map_load(self, values: list[float]) -> tuple[float, float, float, float, float, float]:
        out = [0.0] * 6
        if self.ndm == 2:
            out[0] = values[0] if len(values) > 0 else 0.0
            out[2] = values[1] if len(values) > 1 else 0.0
            out[4] = -(values[2] if len(values) > 2 else 0.0)
        else:
            for index, value in enumerate(values[:6]):
                out[index] = value
        return (out[0], out[1], out[2], out[3], out[4], out[5])

    # ── result ───────────────────────────────────────────────────────
    def project(self) -> Project:
        nodes = {node.id: node for node in self.nodes.values()}
        materials = {material.id: material for material in self.materials.values()}
        sections: dict[int, Any] = {}
        for section in self.sections.values():
            if self._section_ok(section, materials):
                sections[section.id] = section
            else:
                self.drop("section with a missing material")
        elements: dict[int, Any] = {}
        for element in self.elements.values():
            if self._element_ok(element, nodes, materials, sections):
                elements[element.id] = element
            else:
                self.drop(f"{element.type} with a missing reference")

        patterns: list[PlainLoadPattern] = []
        for pattern in self.patterns.values():
            pattern.nodal_loads = [
                load
                for load in pattern.nodal_loads
                if load.node_id in nodes or self._dropped_load("nodal load on a missing node")
            ]
            pattern.element_loads = [
                load
                for load in pattern.element_loads
                if load.element_id in elements
                or self._dropped_load("element load on a missing element")
            ]
            pattern.point_loads = [
                load
                for load in pattern.point_loads
                if load.element_id in elements
                or self._dropped_load("point load on a missing element")
            ]
            if self._has_loads(pattern):
                patterns.append(pattern)

        equal_dofs: list[EqualDOFConstraint] = []
        for constraint in self.equal_dofs:
            if (
                constraint.retained_node in nodes
                and constraint.constrained_node in nodes
                and all(1 <= dof <= self.ndf for dof in constraint.dofs)
            ):
                equal_dofs.append(constraint)
            else:
                self.drop("equalDOF with a missing node or DOF")
        diaphragms: list[RigidDiaphragm] = []
        for diaphragm in self.diaphragms:
            if diaphragm.retained_node in nodes and all(
                node in nodes for node in diaphragm.constrained_nodes
            ):
                diaphragms.append(diaphragm)
            else:
                self.drop("rigidDiaphragm with a missing node")
        rigid_links: list[RigidLink] = []
        for link in self.rigid_links:
            if link.retained_node in nodes and link.constrained_node in nodes:
                rigid_links.append(link)
            else:
                self.drop("rigidLink with a missing node")

        present = {pattern.time_series_id for pattern in patterns}
        series = [ts for tag, ts in self.time_series.items() if tag in present]
        project = Project(
            meta=ProjectMeta(
                name=self.path.stem,
                description=f"Imported from OpenSees Tcl ({self.path.name}).",
                units=self.units,
            ),
            ndm=self.ndm,
            ndf=self.ndf,
            coord_systems=[default_global_system()],
            nodes=sorted(nodes.values(), key=lambda node: node.id),
            materials=sorted(materials.values(), key=lambda material: material.id),
            sections=sorted(sections.values(), key=lambda section: section.id),
            elements=sorted(elements.values(), key=lambda element: element.id),
            mp_constraints=equal_dofs,
            diaphragms=diaphragms,
            rigid_links=rigid_links,
            time_series=sorted(series, key=lambda item: item.id),
            load_patterns=sorted(patterns, key=lambda pattern: pattern.id),
        )
        project.validate_references()
        return project

    def _dropped_load(self, reason: str) -> bool:
        self.drop(reason)
        return False

    @staticmethod
    def _section_ok(section: Any, materials: dict[int, Any]) -> bool:
        ids = set(materials)
        for name in ("patches", "layers", "fibres"):
            for item in getattr(section, name, ()):
                if getattr(item, "material_id", 0) not in ids:
                    return False
        material_id = getattr(section, "material_id", None)
        return material_id is None or material_id in ids

    @staticmethod
    def _element_ok(
        element: Any,
        nodes: dict[int, Any],
        materials: dict[int, Any],
        sections: dict[int, Any],
    ) -> bool:
        if any(node not in nodes for node in element.nodes):
            return False
        material_id = getattr(element, "material_id", None)
        if material_id is not None and material_id not in materials:
            return False
        if any(mid not in materials for mid in getattr(element, "material_ids", ())):
            return False
        for name in ("section_id", "section_i_id", "section_j_id"):
            section_id = getattr(element, name, None)
            if section_id is not None and section_id not in sections:
                return False
        return True

    @staticmethod
    def _has_loads(pattern: PlainLoadPattern) -> bool:
        return any(
            (
                pattern.nodal_loads,
                pattern.element_loads,
                pattern.point_loads,
                pattern.distributed_loads,
            )
        )


# ─────────────────────────── interpreter ───────────────────────────


class _Interpreter:
    def __init__(self, path: Path, units: UnitSystem) -> None:
        self.path = path
        self.builder = _Builder(units, path)
        self.scopes: list[dict[str, str]] = [{}]
        self.procs: dict[str, tuple[list[tuple[str, str | None]], str]] = {}
        self._current_section: int | None = None
        self._source_depth = 0

    # ── variables and expansion ──────────────────────────────────────
    def _get(self, name: str) -> str:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return ""

    def _set(self, name: str, value: str) -> str:
        self.scopes[-1][name] = value
        return value

    def _expand(self, text: str) -> str:
        out: list[str] = []
        index = 0
        while index < len(text):
            char = text[index]
            if char == "\\" and index + 1 < len(text):
                index += 1
                out.append(_unescape("\\" + text[index]))
            elif char == "$":
                index += 1
                if index < len(text) and text[index] == "{":
                    end = text.find("}", index)
                    if end < 0:
                        raise TclImportError(f"{self.path.name}: missing '}}' after '$'.")
                    name = text[index + 1 : end]
                    index = end + 1
                else:
                    match = re.match(r"[A-Za-z0-9_:]+", text[index:])
                    if match is None:
                        out.append("$")
                        continue
                    name = match.group(0)
                    index += len(name)
                out.append(self._get(name))
            elif char == "[":
                end = _matching(text, index, "[", "]")
                out.append(self.eval_script(text[index + 1 : end]).strip())
                index = end + 1
            else:
                out.append(char)
                index += 1
        return "".join(out)

    def _word(self, word: _Word) -> str:
        return word.text if word.braced else self._expand(word.text)

    def _expr(self, word: _Word) -> str:
        return _arithmetic(self._expand(word.text))

    def _raw(self, word: _Word) -> str:
        return word.text

    # ── script execution ─────────────────────────────────────────────
    def eval_script(self, text: str, source: Path | None = None) -> str:
        result = ""
        for words in _Lexer(text, str(source or self.path)).commands():
            result = self._command(words, source or self.path)
        return result

    def _command(self, words: list[_Word], source: Path) -> str:
        name = self._word(words[0])
        if name in self.procs:
            return self._call_proc(name, words[1:], source)
        control = getattr(self, f"_ctrl_{name}", None)
        if control is not None:
            return str(control(words[1:], source))
        if name in _ANALYSIS_COMMANDS or name in _QUERY_COMMANDS:
            self.builder.ignore(name)
            return ""
        if name in _UNSUPPORTED_MESH:
            self.builder.ignore(name)
            self.builder.note(
                "block3D meshes are not imported; draw or mesh the solid in the GUI.",
                key="block3d",
            )
            return ""
        handler = getattr(self, f"_cmd_{name}", None)
        if handler is None:
            self.builder.ignore(name)
            return ""
        return str(handler(words[1:], source))

    # ── Tcl control structures ───────────────────────────────────────
    def _ctrl_set(self, words: list[_Word], source: Path) -> str:
        if not words:
            return ""
        name = self._word(words[0])
        if len(words) == 1:
            return self._get(name)
        return self._set(name, self._word(words[1]))

    def _ctrl_pset(self, words: list[_Word], source: Path) -> str:
        return self._ctrl_set(words, source)

    def _ctrl_unset(self, words: list[_Word], source: Path) -> str:
        for word in words:
            self.scopes[-1].pop(self._word(word), None)
        return ""

    def _ctrl_incr(self, words: list[_Word], source: Path) -> str:
        name = self._word(words[0])
        amount = float(self._word(words[1])) if len(words) > 1 else 1.0
        value = float(self._get(name) or 0.0) + amount
        return self._set(name, str(int(value) if value.is_integer() else value))

    def _ctrl_append(self, words: list[_Word], source: Path) -> str:
        name = self._word(words[0])
        return self._set(name, self._get(name) + "".join(self._word(w) for w in words[1:]))

    def _ctrl_expr(self, words: list[_Word], source: Path) -> str:
        if not words:
            return ""
        if len(words) == 1:
            return self._expr(words[0])
        return _arithmetic(" ".join(self._expand(word.text) for word in words))

    def _ctrl_eval(self, words: list[_Word], source: Path) -> str:
        return self.eval_script(" ".join(self._word(word) for word in words), source)

    def _ctrl_if(self, words: list[_Word], source: Path) -> str:
        index = 0
        while index < len(words):
            keyword = self._raw(words[index])
            if keyword == "else":
                if index + 1 >= len(words):
                    return ""
                return self.eval_script(self._raw(words[index + 1]), source)
            if keyword == "elseif":
                index += 1
            if index + 1 >= len(words):
                return ""
            condition = _truth(self._expr(words[index]))
            body = self._raw(words[index + 1])
            index += 2
            if condition:
                return self.eval_script(body, source)
        return ""

    def _ctrl_foreach(self, words: list[_Word], source: Path) -> str:
        if len(words) < 3:
            return ""
        body = self._raw(words[-1])
        pairs = words[:-1]
        result = ""
        values: list[list[str]] = []
        names: list[str] = []
        for index in range(0, len(pairs) - 1, 2):
            names.append(self._word(pairs[index]))
            values.append(_split_list(self._word(pairs[index + 1])))
        if not values:
            return ""
        count = max(len(value) for value in values)
        for position in range(count):
            for name, value in zip(names, values, strict=False):
                self._set(name, value[position] if position < len(value) else "")
            result = self.eval_script(body, source)
        return result

    def _ctrl_proc(self, words: list[_Word], source: Path) -> str:
        if len(words) < 3:
            return ""
        name = self._word(words[0])
        params: list[tuple[str, str | None]] = []
        for item in _split_list(self._raw(words[1])):
            parts = _split_list(item)
            if not parts:
                continue
            params.append((parts[0], parts[1] if len(parts) > 1 else None))
        self.procs[name] = (params, self._raw(words[2]))
        return ""

    def _ctrl_return(self, words: list[_Word], source: Path) -> str:
        raise _ReturnError(self._word(words[0]) if words else "")

    def _ctrl_source(self, words: list[_Word], source: Path) -> str:
        if not words:
            return ""
        target = Path(self._word(words[0]))
        if not target.is_absolute():
            target = source.parent / target
        if not target.is_file():
            self.builder.note(
                f"source {target.name} was not found; its definitions were skipped.",
                key=f"source:{target}",
            )
            return ""
        if self._source_depth >= 10:
            raise TclImportError("source files nest more than 10 deep.")
        self._source_depth += 1
        try:
            return self.eval_script(target.read_text(encoding="utf-8", errors="replace"), target)
        finally:
            self._source_depth -= 1

    def _ctrl_while(self, words: list[_Word], source: Path) -> str:
        self.builder.ignore("while")
        self.builder.note(
            "while loops were skipped: they usually drive an analysis, not the model.",
            key="while",
        )
        return ""

    def _ctrl_for(self, words: list[_Word], source: Path) -> str:
        if len(words) < 4:
            return ""
        self.eval_script(self._raw(words[0]), source)
        result = ""
        for _ in range(10_000):
            if not _truth(_arithmetic(self._expand(self._raw(words[1])))):
                return result
            result = self.eval_script(self._raw(words[3]), source)
            self.eval_script(self._raw(words[2]), source)
        self.builder.note(
            "A for loop stopped after 10 000 iterations; check the script.",
            key="for-limit",
        )
        return result

    def _ctrl_switch(self, words: list[_Word], source: Path) -> str:
        self.builder.ignore("switch")
        return ""

    def _ctrl_error(self, words: list[_Word], source: Path) -> str:
        message = self._word(words[0]) if words else "the script raised an error."
        self.builder.drop(f"script error: {message}")
        return ""

    def _call_proc(self, name: str, words: list[_Word], source: Path) -> str:
        params, body = self.procs[name]
        scope: dict[str, str] = {}
        values = [self._word(word) for word in words]
        index = 0
        for param, default in params:
            if param == "args":
                scope[param] = " ".join(values[index:])
                break
            if index < len(values):
                scope[param] = values[index]
                index += 1
            else:
                scope[param] = default or ""
        self.scopes.append(scope)
        try:
            return self.eval_script(body, source)
        except _ReturnError as done:
            return done.value
        finally:
            self.scopes.pop()

    # ── model commands ───────────────────────────────────────────────
    def _cmd_wipe(self, words: list[_Word], source: Path) -> str:
        self.builder.wipe()
        return ""

    def _cmd_model(self, words: list[_Word], source: Path) -> str:
        values = [self._word(word) for word in words]
        ndm, ndf = 3, 6
        for index, value in enumerate(values):
            if value == "-ndm" and index + 1 < len(values):
                ndm = int(values[index + 1])
            elif value == "-ndf" and index + 1 < len(values):
                ndf = int(values[index + 1])
        self.builder.set_model(ndm, ndf)
        return ""

    def _cmd_node(self, words: list[_Word], source: Path) -> str:
        values = [self._word(word) for word in words]
        if len(values) < 1 + self.builder.ndm:
            raise TclImportError("node is missing its coordinates.")
        tag = int(values[0])
        coords = [float(value) for value in values[1 : 1 + self.builder.ndm]]
        mass: list[float] | None = None
        if "-mass" in values:
            index = values.index("-mass") + 1
            mass = [float(value) for value in values[index : index + self.builder.ndf]]
        self.builder.add_node(tag, coords, mass)
        return ""

    def _cmd_fix(self, words: list[_Word], source: Path) -> str:
        values = [self._word(word) for word in words]
        tag = int(values[0])
        flags = [_is_on(value) for value in values[1 : 1 + self.builder.ndf]]
        self.builder.add_fix(tag, flags)
        return ""

    def _cmd_mass(self, words: list[_Word], source: Path) -> str:
        values = [self._word(word) for word in words]
        tag = int(values[0])
        self.builder.add_mass(tag, [float(value) for value in values[1 : 1 + self.builder.ndf]])
        return ""

    def _cmd_uniaxialMaterial(self, words: list[_Word], source: Path) -> str:
        values = [self._word(word) for word in words]
        if len(values) < 2:
            raise TclImportError("uniaxialMaterial needs a type and a tag.")
        kind, tag = values[0], int(values[1])
        try:
            numbers = [float(value) for value in values[2:]]
        except ValueError:
            self.builder.drop(f"material {kind}")
            return ""
        material = _uniaxial(kind, tag, numbers, self.builder)
        if material is not None:
            self.builder.add_material(tag, material)
        return ""

    def _cmd_nDMaterial(self, words: list[_Word], source: Path) -> str:
        values = [self._word(word) for word in words]
        if len(values) < 2:
            raise TclImportError("nDMaterial needs a type and a tag.")
        kind, tag = values[0], int(values[1])
        try:
            numbers = [float(value) for value in values[2:]]
        except ValueError:
            self.builder.drop(f"nDMaterial {kind}")
            return ""
        material = _nd_material(kind, tag, numbers, self.builder)
        if material is not None:
            self.builder.add_material(tag, material)
        return ""

    def _cmd_section(self, words: list[_Word], source: Path) -> str:
        values = [self._word(word) for word in words]
        if len(values) < 2:
            raise TclImportError("section needs a type and a tag.")
        kind, tag = values[0].lower(), int(values[1])
        if kind in {"fiber", "fibersec"}:
            body = self._raw(words[-1]) if len(words) > 2 else ""
            section = FiberSection(id=tag)
            self.builder.add_section(tag, section)
            self._current_section = tag
            try:
                self.eval_script(body, source)
            finally:
                self._current_section = None
            return ""
        if kind == "aggregator":
            self._aggregator_section(tag, values[2:])
            return ""
        if kind not in {"elastic", "elasticmembraneplatesection"}:
            self.builder.drop(f"section {kind}")
            return ""
        try:
            numbers = [float(value) for value in values[2:]]
        except ValueError:
            self.builder.drop(f"section {kind}")
            return ""
        created = _section(kind, tag, numbers, self.builder)
        if created is not None:
            self.builder.add_section(tag, created)
        return ""

    def _aggregator_section(self, tag: int, values: list[str]) -> None:
        """Keep the base section of an Aggregator; its added terms are noted."""
        base = None
        for index, value in enumerate(values):
            if value == "-section" and index + 1 < len(values):
                base = int(values[index + 1])
                break
        section: Any | None = self.builder.sections.get(base) if base is not None else None
        if section is None:
            self.builder.drop("section Aggregator without a base section")
            return
        self.builder.add_section(tag, section.model_copy(update={"id": tag}))
        self.builder.note(
            "A section Aggregator is imported as its base section; added materials "
            "(for example torsion) are not preserved.",
            key="aggregator",
        )

    def _cmd_patch(self, words: list[_Word], source: Path) -> str:
        section = self._section()
        if section is None:
            self.builder.drop("patch outside a fibre section")
            return ""
        values = [self._word(word) for word in words]
        kind = values[0].lower()
        try:
            if kind == "rect" and len(values) >= 8:
                section.patches.append(
                    RectangularPatch(
                        material_id=int(values[1]),
                        n_fib_y=int(values[2]),
                        n_fib_z=int(values[3]),
                        y_i=float(values[4]),
                        z_i=float(values[5]),
                        y_j=float(values[6]),
                        z_j=float(values[7]),
                    )
                )
            elif kind == "circ" and len(values) >= 8:
                section.patches.append(
                    CircularPatch(
                        material_id=int(values[1]),
                        n_fib_circ=int(values[2]),
                        n_fib_rad=int(values[3]),
                        y_center=float(values[4]),
                        z_center=float(values[5]),
                        r_inner=float(values[6]),
                        r_outer=float(values[7]),
                    )
                )
            else:
                self.builder.drop(f"fibre patch '{kind}'")
        except (IndexError, ValueError, ValidationError):
            self.builder.drop(f"fibre patch '{kind}' with invalid numbers")
        return ""

    def _cmd_layer(self, words: list[_Word], source: Path) -> str:
        section = self._section()
        if section is None:
            self.builder.drop("layer outside a fibre section")
            return ""
        values = [self._word(word) for word in words]
        kind = values[0].lower()
        try:
            if kind == "straight" and len(values) >= 8:
                section.layers.append(
                    StraightLayer(
                        material_id=int(values[1]),
                        n_bars=int(values[2]),
                        bar_area=float(values[3]),
                        y_start=float(values[4]),
                        z_start=float(values[5]),
                        y_end=float(values[6]),
                        z_end=float(values[7]),
                    )
                )
            else:
                self.builder.drop(f"fibre layer '{kind}'")
        except (IndexError, ValueError, ValidationError):
            self.builder.drop(f"fibre layer '{kind}' with invalid numbers")
        return ""

    def _cmd_fiber(self, words: list[_Word], source: Path) -> str:
        section = self._section()
        if section is None:
            self.builder.drop("fiber outside a fibre section")
            return ""
        values = [self._word(word) for word in words]
        try:
            if len(values) >= 4:
                section.fibres.append(
                    Fibre(
                        y=float(values[0]),
                        z=float(values[1]),
                        area=float(values[2]),
                        material_id=int(values[3]),
                    )
                )
        except (IndexError, ValueError, ValidationError):
            self.builder.drop("fiber with invalid numbers")
        return ""

    def _section(self) -> FiberSection | None:
        if self._current_section is None:
            return None
        section = self.builder.sections.get(self._current_section)
        return section if isinstance(section, FiberSection) else None

    def _cmd_geomTransf(self, words: list[_Word], source: Path) -> str:
        values = [self._word(word) for word in words]
        if len(values) < 2:
            return ""
        kind, tag = values[0], int(values[1])
        if kind not in {"Linear", "PDelta", "Corotational"}:
            kind = "Linear"
        self.builder.geom_transfs[tag] = kind
        if self.builder.ndm == 3 and len(values) > 2:
            self.builder.note(
                "3D local axes are inferred from the member geometry; a geomTransf vecxz "
                "other than the default is not preserved.",
                key="vecxz",
            )
        return ""

    def _cmd_element(self, words: list[_Word], source: Path) -> str:
        values = [self._word(word) for word in words]
        if len(values) < 4:
            raise TclImportError("element needs a type, a tag and its nodes.")
        kind, tag = values[0], int(values[1])
        element, nodes = _element(kind, tag, values[2:], self.builder)
        if element is not None:
            self.builder.add_element(tag, element, nodes)
        return ""

    def _cmd_block2D(self, words: list[_Word], source: Path) -> str:
        """A four-node structured ``block2D`` mesh, with the same shape functions."""
        values = [self._word(word) for word in words]
        if len(values) < 7:
            self.builder.drop("block2D with too few arguments")
            return ""
        try:
            num_x, num_y, start_node, start_ele = (int(value) for value in values[:4])
        except ValueError:
            self.builder.drop("block2D with non-numeric mesh sizes")
            return ""
        if num_x < 1 or num_y < 1:
            self.builder.drop("block2D with an empty mesh")
            return ""
        element_type = values[4]
        element_args = _split_list(values[5])
        tokens = _split_list(self._raw(words[-1]))
        step = self.builder.ndm + 1
        corners: dict[int, tuple[float, float, float]] = {}
        for index in range(0, len(tokens) - step + 1, step):
            tag = int(tokens[index])
            numbers = [float(value) for value in tokens[index + 1 : index + step]]
            corners[tag] = (
                (numbers[0], 0.0, numbers[1])
                if self.builder.ndm == 2
                else (numbers[0], numbers[1], numbers[2])
            )
        if not all(tag in corners for tag in (1, 2, 3, 4)):
            self.builder.drop("block2D without its four corner nodes")
            return ""
        for tag, first, second in ((5, 1, 2), (6, 2, 3), (7, 3, 4), (8, 4, 1)):
            if tag not in corners:
                a, b = corners[first], corners[second]
                corners[tag] = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, (a[2] + b[2]) / 2.0)
        if 9 not in corners:
            corners[9] = (
                sum(corners[tag][0] for tag in (1, 2, 3, 4)) / 4.0,
                sum(corners[tag][1] for tag in (1, 2, 3, 4)) / 4.0,
                sum(corners[tag][2] for tag in (1, 2, 3, 4)) / 4.0,
            )

        def shape(s: float, t: float) -> list[float]:
            nx = [0.5 * s * (s - 1.0), 1.0 - s * s, 0.5 * s * (s + 1.0)]
            ny = [0.5 * t * (t - 1.0), 1.0 - t * t, 0.5 * t * (t + 1.0)]
            return [
                nx[0] * ny[0],
                nx[2] * ny[0],
                nx[2] * ny[2],
                nx[0] * ny[2],
                nx[1] * ny[0],
                nx[2] * ny[1],
                nx[1] * ny[2],
                nx[0] * ny[1],
                nx[1] * ny[1],
            ]

        for j in range(num_y + 1):
            for i in range(num_x + 1):
                weights = shape(-1.0 + 2.0 * i / num_x, -1.0 + 2.0 * j / num_y)
                point = tuple(
                    sum(
                        weight * corners[tag][axis]
                        for tag, weight in zip(range(1, 10), weights, strict=True)
                    )
                    for axis in range(3)
                )
                coords = [point[0], point[2]] if self.builder.ndm == 2 else list(point)
                self.builder.add_node(start_node + j * (num_x + 1) + i, coords, None)

        for j in range(num_y):
            for i in range(num_x):
                first = start_node + j * (num_x + 1) + i
                node_tags = (first, first + 1, first + num_x + 2, first + num_x + 1)
                element, _ = _element(
                    element_type,
                    start_ele + j * num_x + i,
                    [str(tag) for tag in node_tags] + element_args,
                    self.builder,
                )
                if element is not None:
                    self.builder.add_element(start_ele + j * num_x + i, element, node_tags)
        return ""

    def _cmd_block2d(self, words: list[_Word], source: Path) -> str:
        """Lower-case spelling of ``block2D`` used by some scripts."""
        return self._cmd_block2D(words, source)

    def _cmd_equalDOF(self, words: list[_Word], source: Path) -> str:
        values = [self._word(word) for word in words]
        if len(values) < 3:
            return ""
        self.builder.equal_dofs.append(
            EqualDOFConstraint(
                retained_node=int(values[0]),
                constrained_node=int(values[1]),
                dofs=tuple(int(value) for value in values[2:]),
            )
        )
        return ""

    def _cmd_rigidLink(self, words: list[_Word], source: Path) -> str:
        values = [self._word(word) for word in words]
        if len(values) < 3:
            return ""
        self.builder.rigid_links.append(
            RigidLink(
                kind="beam" if values[0].lower() == "beam" else "bar",
                retained_node=int(values[1]),
                constrained_node=int(values[2]),
            )
        )
        return ""

    def _cmd_rigidDiaphragm(self, words: list[_Word], source: Path) -> str:
        values = [self._word(word) for word in words]
        if len(values) < 3:
            return ""
        perp = int(values[0])
        self.builder.diaphragms.append(
            RigidDiaphragm(
                id=max((item.id for item in self.builder.diaphragms), default=0) + 1,
                perp_dirn=cast(Literal[1, 2, 3], perp if perp in (1, 2, 3) else 3),
                retained_node=int(values[1]),
                constrained_nodes=tuple(int(value) for value in values[2:]),
            )
        )
        return ""

    def _cmd_timeSeries(self, words: list[_Word], source: Path) -> str:
        values = [self._word(word) for word in words]
        if len(values) < 2:
            return ""
        kind, tag = values[0].lower(), int(values[1])
        series = _time_series(kind, tag, values[2:], source)
        if series is not None:
            self.builder.time_series[tag] = series
        return ""

    def _cmd_pattern(self, words: list[_Word], source: Path) -> str:
        values = [self._word(word) for word in words]
        if len(values) < 3 or values[0].lower() != "plain":
            self.builder.ignore(f"pattern {values[0] if values else ''}")
            self.builder.note(
                "Only Plain load patterns are imported; other pattern types were skipped.",
                key="pattern",
            )
            return ""
        tag = int(values[1])
        series = self._series_for(values[2], self.builder)
        pattern = PlainLoadPattern(id=tag, name=f"Pattern {tag}", time_series_id=series)
        self.builder.patterns[tag] = pattern
        self.builder.current_pattern = tag
        body = self._raw(words[-1]) if len(words) > 3 else ""
        try:
            self.eval_script(body, source)
        finally:
            self.builder.current_pattern = None
        return ""

    def _series_for(self, value: str, builder: _Builder) -> int:
        try:
            tag = int(value)
        except ValueError:
            tag = max(builder.time_series, default=0) + 1
            kind = value.lower()
            series = _time_series(kind, tag, [], self.path)
            if series is not None:
                builder.time_series[tag] = series
            else:
                builder.time_series[tag] = LinearTimeSeries(id=tag)
            return tag
        if tag not in builder.time_series:
            builder.time_series[tag] = LinearTimeSeries(id=tag)
        return tag

    def _cmd_load(self, words: list[_Word], source: Path) -> str:
        values = [self._word(word) for word in words]
        if len(values) < 2:
            return ""
        try:
            node = int(values[0])
            if node <= 0:
                self.builder.drop("load on a non-positive node tag")
                return ""
            forces = [float(value) for value in values[1 : 1 + self.builder.ndf]]
            self.builder.add_nodal_load(forces, node)
        except (ValueError, ValidationError):
            self.builder.drop("nodal load with a non-numeric value")
        return ""

    def _cmd_eleLoad(self, words: list[_Word], source: Path) -> str:
        values = [self._word(word) for word in words]
        if not values:
            return ""
        elements: list[int] = []
        kind = ""
        args: list[str] = []
        index = 0
        while index < len(values):
            value = values[index]
            if value in {"-ele", "-eles", "-range"}:
                index += 1
                while index < len(values) and not values[index].startswith("-"):
                    if value == "-range":
                        parts = values[index].split("-")
                        if len(parts) == 2:
                            elements.extend(range(int(parts[0]), int(parts[1]) + 1))
                    else:
                        elements.append(int(values[index]))
                    index += 1
            elif value == "-type":
                index += 1
                kind = values[index] if index < len(values) else ""
                index += 1
                count = 0
                if kind == "-beamUniform":
                    count = 2 if self.builder.ndm == 2 else 3
                elif kind == "-beamPoint":
                    count = 3 if self.builder.ndm == 2 else 4
                args = values[index : index + count]
                index += count
            else:
                index += 1
        if not elements or not kind:
            self.builder.drop("eleLoad without elements or type")
            return ""
        if kind == "-beamUniform":
            load = _uniform_load(args, self.builder)
            if load is not None:
                pattern = self.builder.ensure_pattern()
                for element in elements:
                    pattern.element_loads.append(load.model_copy(update={"element_id": element}))
        elif kind == "-beamPoint":
            point = _point_load(args, self.builder)
            if point is not None:
                pattern = self.builder.ensure_pattern()
                for element in elements:
                    pattern.point_loads.append(point.model_copy(update={"element_id": element}))
        else:
            self.builder.drop(f"eleLoad type {kind}")
        return ""


class _ReturnError(Exception):
    def __init__(self, value: str) -> None:
        super().__init__(value)
        self.value = value


# ─────────────────────────── command mapping ───────────────────────────


def _uniaxial(kind: str, tag: int, values: list[float], builder: _Builder) -> Any | None:
    name = kind.lower()
    try:
        if name == "elastic":
            return ElasticUniaxial(
                id=tag,
                E=values[0],
                eta=values[1] if len(values) > 1 else 0.0,
                Eneg=values[2] if len(values) > 2 else None,
            )
        if name == "steel01":
            return Steel01(
                id=tag,
                Fy=values[0],
                E0=values[1],
                b=values[2],
                a1=values[3] if len(values) > 3 else None,
                a2=values[4] if len(values) > 4 else None,
                a3=values[5] if len(values) > 5 else None,
                a4=values[6] if len(values) > 6 else None,
            )
        if name == "steel02":
            if len(values) > 6:
                builder.note(
                    "Steel02 isotropic-hardening parameters (a1..a4) are not preserved.",
                    key="steel02",
                )
            return Steel02(
                id=tag,
                Fy=values[0],
                E0=values[1],
                b=values[2],
                R0=values[3] if len(values) > 3 else 18.0,
                cR1=values[4] if len(values) > 4 else 0.925,
                cR2=values[5] if len(values) > 5 else 0.15,
            )
        if name == "concrete01":
            return Concrete01(
                id=tag, fpc=values[0], epsc0=values[1], fpcu=values[2], epsU=values[3]
            )
        if name == "concrete02":
            return Concrete02.model_validate(
                {
                    "id": tag,
                    "fpc": values[0],
                    "epsc0": values[1],
                    "fpcu": values[2],
                    "epsU": values[3],
                    "lambda": values[4],
                    "ft": values[5],
                    "Ets": values[6],
                }
            )
        if name == "concrete04":
            return Concrete04(
                id=tag,
                fpc=values[0],
                epsc0=values[1],
                epscu=values[2],
                Ec=values[3],
                fct=values[4] if len(values) > 4 else None,
                et=values[5] if len(values) > 5 else None,
                beta=values[6] if len(values) > 6 else None,
            )
        if name == "hardening":
            return Hardening(
                id=tag,
                E=values[0],
                sigmaY=values[1],
                H_iso=values[2],
                H_kin=values[3],
                eta=values[4] if len(values) > 4 else 0.0,
            )
        if name == "elasticpp":
            return ElasticPP(
                id=tag,
                E=values[0],
                epsy_pos=values[1],
                epsy_neg=values[2] if len(values) > 2 else None,
                eps0=values[3] if len(values) > 3 else 0.0,
            )
        if name == "hysteretic":
            return HystereticMaterial(
                id=tag,
                s1p=values[0],
                e1p=values[1],
                s2p=values[2],
                e2p=values[3],
                s3p=values[4],
                e3p=values[5],
                s1n=values[6],
                e1n=values[7],
                s2n=values[8],
                e2n=values[9],
                s3n=values[10],
                e3n=values[11],
                px=values[12] if len(values) > 12 else 1.0,
                py=values[13] if len(values) > 13 else 1.0,
                d1=values[14] if len(values) > 14 else 0.0,
                d2=values[15] if len(values) > 15 else 0.0,
                beta=values[16] if len(values) > 16 else 0.0,
            )
    except (IndexError, ValidationError, ValueError) as exc:
        builder.drop(f"material {kind} ({exc})")
        return None
    builder.drop(f"material {kind}")
    return None


def _nd_material(kind: str, tag: int, values: list[float], builder: _Builder) -> Any | None:
    if kind.lower() == "elasticisotropic":
        try:
            return ElasticIsotropic(
                id=tag,
                E=values[0],
                nu=values[1],
                rho=values[2] if len(values) > 2 else 0.0,
            )
        except (IndexError, ValidationError, ValueError) as exc:
            builder.drop(f"nDMaterial {kind} ({exc})")
            return None
    builder.drop(f"nDMaterial {kind}")
    return None


def _section(kind: str, tag: int, values: list[float], builder: _Builder) -> Any | None:
    try:
        if kind == "elastic":
            return ElasticSection(
                id=tag,
                E=values[0],
                A=values[1],
                Iz=values[2],
                Iy=values[3] if len(values) > 3 else None,
                G=values[4] if len(values) > 4 else None,
                J=values[5] if len(values) > 5 else None,
            )
        if kind == "elasticmembraneplatesection":
            return ElasticMembranePlateSection(
                id=tag,
                E=values[0],
                nu=values[1],
                h=values[2],
                rho=values[3] if len(values) > 3 else 0.0,
            )
    except (IndexError, ValidationError, ValueError) as exc:
        builder.drop(f"section {kind} ({exc})")
        return None
    builder.drop(f"section {kind}")
    return None


def _geom_transf(builder: _Builder, tag: int) -> _GeomTransf:
    return cast(_GeomTransf, builder.geom_transfs.get(tag, "Linear"))


def _element(
    kind: str, tag: int, values: list[str], builder: _Builder
) -> tuple[Any | None, tuple[int, ...]]:
    name = kind.lower()
    try:
        if name in {"truss", "corottruss"}:
            nodes = (int(values[0]), int(values[1]))
            area, material = float(values[2]), int(values[3])
            truss_cls: Any = TrussElement if name == "truss" else CorotTrussElement
            return (
                truss_cls(id=tag, nodes=nodes, area=area, material_id=material),
                nodes,
            )
        if name == "elasticbeamcolumn":
            nodes = (int(values[0]), int(values[1]))
            numbers = [float(value) for value in values[2:]]
            section_id = _elastic_section(numbers, builder)
            if section_id is None:
                return None, nodes
            trans = int(numbers[3] if builder.ndm == 2 else numbers[6])
            return (
                ElasticBeamColumn(
                    id=tag,
                    nodes=nodes,
                    section_id=section_id,
                    geom_transf=_geom_transf(builder, trans),
                ),
                nodes,
            )
        if name in {"forcebeamcolumn", "nonlinearbeamcolumn", "dispbeamcolumn"}:
            nodes = (int(values[0]), int(values[1]))
            points = int(values[2])
            section_id = int(values[3])
            trans = int(values[4])
            frame_cls: Any = DispBeamColumn if name == "dispbeamcolumn" else ForceBeamColumn
            return (
                frame_cls(
                    id=tag,
                    nodes=nodes,
                    section_id=section_id,
                    integration_points=max(2, min(points, 10)),
                    geom_transf=_geom_transf(builder, trans),
                ),
                nodes,
            )
        if name == "zerolength":
            nodes = (int(values[0]), int(values[1]))
            materials: list[int] = []
            dofs: list[int] = []
            index = 2
            while index < len(values):
                option = values[index]
                index += 1
                if option == "-mat":
                    while index < len(values) and not values[index].startswith("-"):
                        materials.append(int(values[index]))
                        index += 1
                elif option == "-dir":
                    while index < len(values) and not values[index].startswith("-"):
                        dofs.append(int(values[index]))
                        index += 1
                else:
                    while index < len(values) and not values[index].startswith("-"):
                        index += 1
            return (
                ZeroLengthElement(
                    id=tag, nodes=nodes, material_ids=tuple(materials), dofs=tuple(dofs)
                ),
                nodes,
            )
        if name == "zerolengthsection":
            nodes = (int(values[0]), int(values[1]))
            return (
                ZeroLengthSectionElement(id=tag, nodes=nodes, section_id=int(values[2])),
                nodes,
            )
        if name == "quad":
            quad_nodes = (int(values[0]), int(values[1]), int(values[2]), int(values[3]))
            thickness = float(values[4])
            behaviour = values[5] if len(values) > 5 else "PlaneStress"
            return (
                QuadElement(
                    id=tag,
                    nodes=quad_nodes,
                    thickness=thickness,
                    material_id=int(values[6]),
                    behaviour="PlaneStrain2D"
                    if behaviour.lower().startswith("planestrain")
                    else "PlaneStress2D",
                    pressure=float(values[7]) if len(values) > 7 else 0.0,
                    rho=float(values[8]) if len(values) > 8 else 0.0,
                    b1=float(values[9]) if len(values) > 9 else 0.0,
                    b2=float(values[10]) if len(values) > 10 else 0.0,
                ),
                quad_nodes,
            )
        if name in {"shellmitc4", "shellmitc4element", "shell"}:
            shell_nodes = (int(values[0]), int(values[1]), int(values[2]), int(values[3]))
            return (
                ShellMITC4Element(
                    id=tag,
                    nodes=shell_nodes,
                    section_id=int(values[4]),
                ),
                shell_nodes,
            )
        if name == "beamwithhinges":
            nodes = (int(values[0]), int(values[1]))
            section_i, lp_i = int(values[2]), float(values[3])
            section_j, lp_j = int(values[4]), float(values[5])
            e, area, iz = float(values[6]), float(values[7]), float(values[8])
            trans = int(values[12] if builder.ndm == 3 else values[9])
            return (
                BeamWithHingesElement(
                    id=tag,
                    nodes=nodes,
                    section_i_id=section_i,
                    section_j_id=section_j,
                    lp_i=lp_i,
                    lp_j=lp_j,
                    E=e,
                    A=area,
                    Iz=iz,
                    Iy=float(values[9]) if builder.ndm == 3 else None,
                    G=float(values[10]) if builder.ndm == 3 else None,
                    J=float(values[11]) if builder.ndm == 3 else None,
                    geom_transf=_geom_transf(builder, trans),
                ),
                nodes,
            )
    except (IndexError, ValidationError, ValueError) as exc:
        builder.drop(f"element {kind} ({exc})")
        return None, ()
    builder.drop(f"element {kind}")
    return None, ()


def _elastic_section(values: list[float], builder: _Builder) -> int | None:
    """A section for a raw ``elasticBeamColumn`` signature (2D or 3D)."""
    if builder.ndm == 2:
        if len(values) < 4:
            builder.drop("2D elasticBeamColumn without A, E, Iz and a transform")
            return None
        area, e, iz = values[0], values[1], values[2]
        return builder.elastic_section(e, area, iz, None, None, None)
    if len(values) < 7:
        builder.drop("3D elasticBeamColumn without A, E, G, J, Iy, Iz and a transform")
        return None
    area, e, g, j, iy, iz = values[:6]
    return builder.elastic_section(e, area, iz, iy, g, j)


def _uniform_load(values: list[str], builder: _Builder) -> UniformElementLoad | None:
    try:
        numbers = [float(value) for value in values]
    except ValueError:
        builder.drop("beamUniform with a non-numeric value")
        return None
    if builder.ndm == 2:
        if len(numbers) >= 3:
            builder.note(
                "2D beamUniform loads keep wy and wx; wz is out of plane and was dropped.",
                key="wz",
            )
        return UniformElementLoad(
            element_id=1,
            wy=numbers[0] if len(numbers) > 0 else 0.0,
            wx=numbers[2] if len(numbers) > 2 else (numbers[1] if len(numbers) > 1 else 0.0),
        )
    return UniformElementLoad(
        element_id=1,
        wy=numbers[0] if len(numbers) > 0 else 0.0,
        wz=numbers[1] if len(numbers) > 1 else 0.0,
        wx=numbers[2] if len(numbers) > 2 else 0.0,
    )


def _point_load(values: list[str], builder: _Builder) -> PointElementLoad | None:
    try:
        numbers = [float(value) for value in values]
    except ValueError:
        builder.drop("beamPoint with a non-numeric value")
        return None
    if builder.ndm == 2:
        return PointElementLoad(
            element_id=1,
            py=numbers[0] if len(numbers) > 0 else 0.0,
            x=numbers[1] if len(numbers) > 1 else 0.5,
            px=numbers[2] if len(numbers) > 2 else 0.0,
        )
    return PointElementLoad(
        element_id=1,
        py=numbers[0] if len(numbers) > 0 else 0.0,
        pz=numbers[1] if len(numbers) > 1 else 0.0,
        x=numbers[2] if len(numbers) > 2 else 0.5,
        px=numbers[3] if len(numbers) > 3 else 0.0,
    )


def _time_series(kind: str, tag: int, values: list[str], source: Path) -> Any | None:
    if kind == "path":
        try:
            return _path_series(tag, values, source)
        except (IndexError, ValidationError, ValueError):
            return None
    try:
        numbers = [float(value) for value in values]
        if kind == "linear":
            return LinearTimeSeries(id=tag, factor=numbers[0] if numbers else 1.0)
        if kind == "constant":
            return ConstantTimeSeries(id=tag, factor=numbers[0] if numbers else 1.0)
        if kind == "trig":
            return TrigTimeSeries(
                id=tag,
                t_start=numbers[0],
                t_end=numbers[1],
                period=numbers[2],
                factor=numbers[3] if len(numbers) > 3 else 1.0,
            )
    except (IndexError, ValidationError, ValueError):
        return None
    return None


def _path_series(tag: int, values: list[str], source: Path) -> PathTimeSeries | None:
    options = {values[index]: values[index + 1] for index in range(0, len(values) - 1, 2)}
    file_name = options.get("-filePath")
    if file_name is None:
        return None
    path = Path(file_name)
    if not path.is_absolute():
        path = source.parent / path
    data: list[float] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if not parts:
                continue
            try:
                data.append(float(parts[-1]))
            except ValueError:
                continue
    factor = float(options.get("-factor", "1.0"))
    dt = float(options["-dt"]) if "-dt" in options else None
    if dt is not None:
        return PathTimeSeries(id=tag, factor=factor, dt=dt, values=data)
    return PathTimeSeries(id=tag, factor=factor, values=data)


def import_tcl(path: str | Path, *, units: UnitSystem = UnitSystem.SI_M_N) -> TclImport:
    """Read ``path`` and translate its model into a :class:`Project`."""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise TclImportError(f"Cannot read {source.name}: {exc}") from exc
    interpreter = _Interpreter(source, units)
    try:
        interpreter.eval_script(text)
        if not interpreter.builder.nodes:
            interpreter.builder.restore_last()
        project = interpreter.builder.project()
    except TclImportError:
        raise
    except (ValidationError, ValueError) as exc:
        raise TclImportError(f"{source.name} does not make a valid project: {exc}") from exc
    builder = interpreter.builder
    notes = list(builder.notes)
    if builder.ignored:
        names = ", ".join(f"{name} ({count})" for name, count in builder.ignored.most_common(12))
        notes.append(f"Commands not imported: {names}.")
    if builder.dropped:
        names = ", ".join(f"{name} ({count})" for name, count in builder.dropped.most_common(12))
        notes.append(f"Items left out: {names}.")
    return TclImport(
        project=project,
        path=source,
        notes=notes,
        ignored=builder.ignored,
        dropped=builder.dropped,
    )
