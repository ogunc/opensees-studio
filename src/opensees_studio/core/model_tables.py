"""Model tables: joints, elements and joint loads as rows of text, and back.

Edit → Interactive Table Editing shows the model as spreadsheets (SAP2000's
"interactive database editing"): every value is a cell, rows can be pasted from
Excel, added and deleted. This module turns the project into rows of strings
and the edited rows back into a *validated copy* of the project, so the view
only shows text and wraps the result in one undoable command.

Only the DOFs the model has are columns (:mod:`core.plane`): a 2D frame shows
X, Z and Ux, Uz, Ry. A cell that does not parse raises ``ValueError`` naming
its table, row and column.

No Qt, no OpenSees.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from opensees_studio.core.geometry import Element, Node
from opensees_studio.core.groups import prune_groups
from opensees_studio.core.loads import LoadPattern, NodalLoad, PlainLoadPattern
from opensees_studio.core.plane import AXIS_NAMES, coord_axes, dof_indices, dof_labels, force_labels
from opensees_studio.core.project import Project

Rows = list[list[str]]

_TRUE = {"1", "true", "yes", "y", "x", "fixed", "si", "sí"}
_FALSE = {"0", "false", "no", "n", "", "free"}


@dataclass(frozen=True)
class Table:
    """Column headers, which of them the user may edit, and the rows."""

    name: str
    columns: tuple[str, ...]
    editable: tuple[bool, ...]
    rows: Rows
    can_add_rows: bool = True


def _fmt(value: float) -> str:
    return repr(float(value)) if value != int(value) or abs(value) >= 1e16 else str(int(value))


def _cell(rows: Sequence[Sequence[str]], r: int, c: int) -> str:
    row = rows[r]
    return row[c].strip() if c < len(row) else ""


class _Reader:
    """Parses one table's cells, naming the place of a bad one."""

    def __init__(self, table: str, columns: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
        self.table, self.columns, self.rows = table, columns, rows

    def _where(self, r: int, c: int) -> str:
        return f"{self.table}, row {r + 1}, column {self.columns[c]}"

    def text(self, r: int, c: int) -> str:
        return _cell(self.rows, r, c)

    def number(self, r: int, c: int, default: float | None = None) -> float:
        text = self.text(r, c)
        if not text and default is not None:
            return default
        try:
            return float(text.replace(",", "."))
        except ValueError:
            raise ValueError(f"{self._where(r, c)}: {text!r} is not a number.") from None

    def whole(self, r: int, c: int) -> int:
        text = self.text(r, c)
        try:
            value = int(text)
        except ValueError:
            raise ValueError(f"{self._where(r, c)}: {text!r} is not a whole number.") from None
        if value <= 0:
            raise ValueError(f"{self._where(r, c)}: ids are positive, got {value}.")
        return value

    def flag(self, r: int, c: int) -> bool:
        text = self.text(r, c).casefold()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ValueError(f"{self._where(r, c)}: {text!r} is not 1/0 (fixed/free).")

    def ints(self, r: int, c: int) -> list[int]:
        text = self.text(r, c).replace(",", " ").replace(";", " ")
        try:
            return [int(t) for t in text.split()]
        except ValueError:
            raise ValueError(f"{self._where(r, c)}: {text!r} is not a list of ids.") from None


# ──────────────────────────── joints ────────────────────────────
def _joint_columns(project: Project) -> tuple[str, ...]:
    axes = tuple(AXIS_NAMES[i] for i in coord_axes(project.ndm))
    dofs = dof_labels(project.ndm, project.ndf)
    masses = tuple(f"M{label[1:]}" if label[0] == "U" else f"I{label[1:]}" for label in dofs)
    return ("ID", "Name", *axes, *dofs, *masses)


def joint_table(project: Project) -> Table:
    """One row per joint: id, name, coordinates, restraints (1/0) and masses."""
    axes, slots = coord_axes(project.ndm), dof_indices(project.ndm, project.ndf)
    rows = [
        [
            str(n.id),
            n.name,
            *(_fmt(n.coords[a]) for a in axes),
            *("1" if n.restraint[s] else "0" for s in slots),
            *(_fmt(n.mass[s]) for s in slots),
        ]
        for n in project.nodes
    ]
    columns = _joint_columns(project)
    return Table("Joints", columns, (True,) * len(columns), rows)


def joints_from_rows(project: Project, rows: Sequence[Sequence[str]]) -> list[Node]:
    """The joints the rows describe; a row with an empty ID gets the next free one."""
    columns = _joint_columns(project)
    read = _Reader("Joints", columns, rows)
    axes, slots = coord_axes(project.ndm), dof_indices(project.ndm, project.ndf)
    old = {n.id: n for n in project.nodes}
    typed = {read.whole(r, 0) for r in range(len(rows)) if read.text(r, 0)}
    next_id = max(typed | set(old), default=0) + 1
    nodes: list[Node] = []
    seen: set[int] = set()
    for r in range(len(rows)):
        if read.text(r, 0):
            node_id = read.whole(r, 0)
        else:
            node_id, next_id = next_id, next_id + 1
        if node_id in seen:
            raise ValueError(f"Joints, row {r + 1}: joint {node_id} appears twice.")
        seen.add(node_id)
        base = old.get(node_id)
        coords = list(base.coords) if base is not None else [0.0, 0.0, 0.0]
        restraint = list(base.restraint) if base is not None else [False] * 6
        mass = list(base.mass) if base is not None else [0.0] * 6
        c = 2
        for axis in axes:
            coords[axis] = read.number(r, c)
            c += 1
        for slot in slots:
            restraint[slot] = read.flag(r, c)
            c += 1
        for slot in slots:
            mass[slot] = read.number(r, c, default=0.0)
            if mass[slot] < 0:
                raise ValueError(
                    f"Joints, row {r + 1}, column {columns[c]}: a mass is not negative."
                )
            c += 1
        nodes.append(
            Node(
                id=node_id,
                name=read.text(r, 1),
                coords=(coords[0], coords[1], coords[2]),
                restraint=(
                    restraint[0],
                    restraint[1],
                    restraint[2],
                    restraint[3],
                    restraint[4],
                    restraint[5],
                ),
                mass=(mass[0], mass[1], mass[2], mass[3], mass[4], mass[5]),
                # Not a column: an edited joint keeps its support springs.
                spring=base.spring if base is not None else (0.0,) * 6,
            )
        )
    return nodes


# ──────────────────────────── elements ────────────────────────────
ELEMENT_COLUMNS = ("ID", "Type", "Name", "Joints", "Section", "Material")


def element_table(project: Project) -> Table:
    """One row per element: joints, section and material (blank when it has none)."""
    rows = []
    for e in project.elements:
        section = getattr(e, "section_id", None)
        material = getattr(e, "material_id", None)
        rows.append(
            [
                str(e.id),
                e.type,
                e.name,
                " ".join(str(n) for n in e.nodes),
                "" if section is None else str(section),
                "" if material is None else str(material),
            ]
        )
    # Elements are added with the draw tools and wizards; here they are edited or deleted.
    editable = (False, False, True, True, True, True)
    return Table("Elements", ELEMENT_COLUMNS, editable, rows, can_add_rows=False)


def elements_from_rows(project: Project, rows: Sequence[Sequence[str]]) -> list[Element]:
    """The elements the rows describe: each row edits the existing element with its ID."""
    read = _Reader("Elements", ELEMENT_COLUMNS, rows)
    old = {e.id: e for e in project.elements}
    out: list[Element] = []
    seen: set[int] = set()
    for r in range(len(rows)):
        element_id = read.whole(r, 0)
        element = old.get(element_id)
        if element is None:
            raise ValueError(f"Elements, row {r + 1}: there is no element {element_id}.")
        if element_id in seen:
            raise ValueError(f"Elements, row {r + 1}: element {element_id} appears twice.")
        seen.add(element_id)
        nodes = read.ints(r, 3)
        if len(nodes) != len(element.nodes):
            raise ValueError(
                f"Elements, row {r + 1}: a {element.type} has {len(element.nodes)} joints, "
                f"got {len(nodes)}."
            )
        update: dict[str, object] = {"name": read.text(r, 2), "nodes": tuple(nodes)}
        for c, field in ((4, "section_id"), (5, "material_id")):
            has = getattr(element, field, None) is not None
            if read.text(r, c):
                if not has:
                    raise ValueError(
                        f"Elements, row {r + 1}: a {element.type} has no "
                        f"{ELEMENT_COLUMNS[c].lower()}."
                    )
                update[field] = read.whole(r, c)
            elif has:
                raise ValueError(
                    f"Elements, row {r + 1}: a {element.type} needs a {ELEMENT_COLUMNS[c].lower()}."
                )
        data = element.model_dump()
        data.update(update)
        out.append(type(element).model_validate(data))
    return out


# ──────────────────────────── joint loads ────────────────────────────
def _load_columns(project: Project) -> tuple[str, ...]:
    return ("Pattern", "Joint", *force_labels(project.ndm, project.ndf))


def _pattern_label(pattern: PlainLoadPattern) -> str:
    return pattern.name or str(pattern.id)


def joint_load_table(project: Project) -> Table:
    """One row per joint load of every Plain pattern, named by the pattern's name."""
    slots = dof_indices(project.ndm, project.ndf)
    rows = [
        [_pattern_label(p), str(load.node_id), *(_fmt(load.forces[s]) for s in slots)]
        for p in project.load_patterns
        if isinstance(p, PlainLoadPattern)
        for load in p.nodal_loads
    ]
    columns = _load_columns(project)
    return Table("Joint Loads", columns, (True,) * len(columns), rows)


def patterns_from_load_rows(project: Project, rows: Sequence[Sequence[str]]) -> list[LoadPattern]:
    """The load patterns with their joint loads replaced by the rows (others untouched)."""
    columns = _load_columns(project)
    read = _Reader("Joint Loads", columns, rows)
    slots = dof_indices(project.ndm, project.ndf)
    plain = [p for p in project.load_patterns if isinstance(p, PlainLoadPattern)]
    by_label: dict[str, PlainLoadPattern] = {}
    for p in plain:
        by_label.setdefault(_pattern_label(p).casefold(), p)
        by_label.setdefault(str(p.id), p)
    loads: dict[int, list[NodalLoad]] = {p.id: [] for p in plain}
    for r in range(len(rows)):
        label = read.text(r, 0)
        pattern = by_label.get(label.casefold())
        if pattern is None:
            raise ValueError(f"Joint Loads, row {r + 1}: there is no Plain load pattern {label!r}.")
        forces = [0.0] * 6
        for k, slot in enumerate(slots):
            forces[slot] = read.number(r, 2 + k, default=0.0)
        loads[pattern.id].append(
            NodalLoad(
                node_id=read.whole(r, 1),
                forces=(forces[0], forces[1], forces[2], forces[3], forces[4], forces[5]),
            )
        )
    return [
        p.model_copy(update={"nodal_loads": loads[p.id]}) if isinstance(p, PlainLoadPattern) else p
        for p in project.load_patterns
    ]


# ──────────────────────────── all together ────────────────────────────
def model_tables(project: Project) -> list[Table]:
    """The tables Edit → Interactive Table Editing shows, in tab order."""
    return [joint_table(project), element_table(project), joint_load_table(project)]


def apply_tables(project: Project, rows: dict[str, Sequence[Sequence[str]]]) -> Project:
    """A validated copy of ``project`` with the edited tables (keyed by table name).

    Raises ``ValueError`` on a bad cell or on a reference the edit breaks (an
    element on a deleted joint, a load on a missing one).
    """
    copy = project.model_copy(deep=True)
    if "Joints" in rows:
        copy.nodes[:] = joints_from_rows(project, rows["Joints"])
    if "Elements" in rows:
        copy.elements[:] = elements_from_rows(project, rows["Elements"])
    if "Joint Loads" in rows:
        copy.load_patterns[:] = patterns_from_load_rows(project, rows["Joint Loads"])
    prune_groups(copy)  # a deleted row leaves the groups too
    copy.validate_references()
    return copy
