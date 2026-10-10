"""Result tables: the numbers a result view shows, with units, and their CSV export.

Every table the Results panel displays is built here from a result object,
so the display and the export share one source. A cell holds the float the
analysis produced, never a rounded copy: views round for display only, and
:func:`write_csv` writes each number in its shortest round-trip form
(``repr``), so reading the file back gives the result values exactly.

Column headers carry their unit in brackets, taken from the project's *display*
unit system (translations in length units, rotations in rad, forces and moments),
and every value is converted to that system: switching the display units moves
the numbers and the headers together. No Qt here.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from opensees_studio.core import (
    BeamWithHingesElement,
    DispBeamColumn,
    ElasticBeamColumn,
    ForceBeamColumn,
    Project,
)
from opensees_studio.core.units import UnitConverter, UnitLabels, UnitSystem
from opensees_studio.services.results import (
    ModalResults,
    PushoverResults,
    ResponseSpectrumResults,
    StaticResults,
    TransientResults,
)

Cell = int | float | str

FRAME_TYPES = (ElasticBeamColumn, ForceBeamColumn, DispBeamColumn, BeamWithHingesElement)
"""Elements whose recorded forces are OpenSees ``localForce`` (N, V, M per end)."""

_LOCAL_2D = ("N", "V", "M")
_LOCAL_3D = ("N", "Vy", "Vz", "T", "My", "Mz")

HISTORY_KINDS = ("disp", "vel", "accel")
"""Transient node histories: displacement, velocity, acceleration."""


@dataclass
class ResultTable:
    """A titled table: ``columns`` name the quantity and its unit, ``rows`` hold raw values."""

    title: str
    columns: list[str]
    rows: list[list[Cell]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    """Warnings shown above the table (not exported)."""


@dataclass(frozen=True)
class Layout:
    """What a table builder needs to know about the model: DOF layout and units.

    ``units`` is the model's own system; ``display_units`` (``None`` = the same)
    is the system the numbers are *shown* in. Every table builder converts
    through :attr:`converter` so a display change moves values and headers
    together — the two can never disagree.
    """

    ndm: int = 3
    ndf: int = 6
    units: UnitSystem = UnitSystem.SI_M_N
    display_units: UnitSystem | None = None

    @classmethod
    def of(cls, project: Project | None, ndf: int | None = None) -> Layout:
        """The project's layout; without a project, guess from the recorded DOF count."""
        if project is not None:
            return cls(
                project.ndm,
                project.ndf,
                project.meta.units,
                project.meta.display_units,
            )
        if ndf is None or ndf == 6:
            return cls()
        return cls(ndm=2, ndf=ndf)

    @property
    def converter(self) -> UnitConverter:
        return UnitConverter(self.units, self.display_units)

    @property
    def labels(self) -> UnitLabels:
        return self.converter.labels

    def is_rotation(self, dof: int) -> bool:
        """``dof`` is 1-based; DOFs above ``ndm`` are rotations (ndf 3 in 2D, 6 in 3D)."""
        return self.ndf > self.ndm and dof > self.ndm

    def _rotation_axis(self, dof: int) -> int:
        return 3 if self.ndm == 2 else dof - 3

    def dof_factor(self, dof: int, kind: str = "disp") -> float:
        """Factor for a nodal DOF column: rotations are unit-free, translations are lengths.

        ``kind`` names the quantity (``disp``/``vel``/``accel``) and only drives
        the label; every one of them is a length per some power of time, and only
        the length unit differs between systems.
        """
        if self.is_rotation(dof):
            return 1.0
        return self.converter.factor("length")

    def force_dof_factor(self, dof: int) -> float:
        """Factor for a nodal force column: rotations carry moments, translations forces."""
        if self.is_rotation(dof):
            return self.converter.factor("moment")
        return self.converter.factor("force")

    def disp_column(self, dof: int, kind: str = "disp") -> str:
        """``U1 [m]``, ``R3 [rad]``; velocity ``V1 [m/s]``, ``VR3 [rad/s]``; acceleration
        ``A1 [m/s^2]``, ``AR3 [rad/s^2]``."""
        per_time = {"disp": "", "vel": "/s", "accel": "/s^2"}[kind]
        if self.is_rotation(dof):
            prefix = {"disp": "R", "vel": "VR", "accel": "AR"}[kind]
            return f"{prefix}{self._rotation_axis(dof)} [{self.labels.rotation}{per_time}]"
        prefix = {"disp": "U", "vel": "V", "accel": "A"}[kind]
        return f"{prefix}{dof} [{self.labels.length}{per_time}]"

    def force_column(self, dof: int) -> str:
        """``F1 [N]``, ``M3 [N·m]``."""
        if self.is_rotation(dof):
            return f"M{self._rotation_axis(dof)} [{self.labels.moment}]"
        return f"F{dof} [{self.labels.force}]"


# ─────────────────────────── builders ───────────────────────────
def _node_table(
    title: str,
    values: dict[int, np.ndarray],
    layout: Layout,
    column: str,
) -> ResultTable:
    """One row per node from the last row of each node's history."""
    nodes = sorted(values)
    ndf = int(values[nodes[0]].shape[-1]) if nodes else layout.ndf
    is_force = column == "force"
    name = layout.force_column if is_force else layout.disp_column
    factor = layout.force_dof_factor if is_force else layout.dof_factor
    factors = [factor(d) for d in range(1, ndf + 1)]
    table = ResultTable(title, ["Node"] + [name(d) for d in range(1, ndf + 1)])
    for nid in nodes:
        last = np.atleast_2d(values[nid])[-1]
        table.rows.append([nid, *(float(v) * f for v, f in zip(last, factors, strict=True))])
    return table


def _component_names(element: object, n: int, layout: Layout) -> list[tuple[str, str, float]]:
    """``(component, unit, factor)`` per recorded force component of one element.

    Frame elements record ``localForce``: N, V, M per end in 2D, N, Vy, Vz,
    T, My, Mz in 3D. Other elements record their nodal forces, ``ndf`` values
    per node, named by DOF. ``factor`` takes the recorded value to display units.
    """
    labels = layout.labels
    if isinstance(element, FRAME_TYPES) and n in (6, 12):
        names = _LOCAL_2D if n == 6 else _LOCAL_3D
        out = []
        for end in ("i", "j"):
            for name in names:
                is_moment = name in ("M", "T", "My", "Mz")
                unit = labels.moment if is_moment else labels.force
                factor = layout.converter.factor("moment" if is_moment else "force")
                out.append((f"{name} {end}", unit, factor))
        return out
    per_node = layout.ndf if layout.ndf and n % layout.ndf == 0 else n
    out = []
    for k in range(n):
        node, dof = divmod(k, per_node)
        unit = labels.moment if layout.is_rotation(dof + 1) else labels.force
        out.append(
            (f"node {node + 1} DOF {dof + 1}", unit, layout.force_dof_factor(dof + 1)),
        )
    return out


def element_force_table(
    title: str,
    forces: dict[int, np.ndarray],
    project: Project | None,
    layout: Layout,
) -> ResultTable:
    """Final-step element forces, one row per component, the unit in its own column."""
    by_id = {el.id: el for el in project.elements} if project is not None else {}
    table = ResultTable(title, ["Element", "Type", "Component", "Unit", "Value"])
    for eid in sorted(forces):
        last = np.atleast_2d(forces[eid])[-1]
        element = by_id.get(eid)
        kind = type(element).__name__ if element is not None else ""
        for (component, unit, factor), value in zip(
            _component_names(element, len(last), layout), last, strict=True
        ):
            table.rows.append([eid, kind, component, unit, float(value) * factor])
    return table


def static_tables(r: StaticResults, project: Project | None = None) -> list[ResultTable]:
    ndf = next(iter(r.node_disp.values())).shape[-1] if r.node_disp else None
    layout = Layout.of(project, ndf)
    return [
        _node_table("Final-step displacements", r.node_disp, layout, "disp"),
        _node_table("Final-step reactions", r.node_reaction, layout, "force"),
        element_force_table("Final-step element forces", r.element_forces, project, layout),
    ]


def pushover_tables(r: PushoverResults, project: Project | None = None) -> list[ResultTable]:
    ndf = next(iter(r.node_disp.values())).shape[-1] if r.node_disp else None
    layout = Layout.of(project, ndf)
    curve = ResultTable(
        f"Pushover curve (node {r.control_node})",
        [
            "Step",
            f"Control {layout.disp_column(r.control_dof)}",
            f"Base shear [{layout.labels.force}]",
        ],
    )
    disp_factor = layout.dof_factor(r.control_dof)
    shear_factor = layout.converter.factor("force")
    for step, (disp, shear) in enumerate(zip(r.control_disp, r.base_shear, strict=True)):
        curve.rows.append([step, float(disp) * disp_factor, float(shear) * shear_factor])
    return [
        curve,
        _node_table("Final-step displacements", r.node_disp, layout, "disp"),
        element_force_table("Final-step element forces", r.element_forces, project, layout),
    ]


def modal_tables(r: ModalResults) -> list[ResultTable]:
    table = ResultTable(
        "Modal results",
        ["Mode", "Eigenvalue [rad²/s²]", "ω [rad/s]", "f [Hz]", "T [s]"],
    )
    for i, lam in enumerate(r.eigenvalues):
        table.rows.append(
            [
                i + 1,
                float(lam),
                float(r.angular_frequencies[i]),
                float(r.frequencies[i]),
                float(r.periods[i]),
            ]
        )
    return [table]


def response_spectrum_tables(
    r: ResponseSpectrumResults, project: Project | None = None
) -> list[ResultTable]:
    converter = Layout.of(project).converter
    length = converter.labels.length
    combined = ResultTable(
        f"{r.combination} combined peak displacements",
        ["Node", f"U1 [{length}]", f"U2 [{length}]", f"U3 [{length}]"],
        notes=list(r.warnings),
    )
    for nid in sorted(r.combined_disp):
        combined.rows.append(
            [nid, *(float(v) * converter.length for v in r.combined_disp[nid][:3])],
        )
    modes = ResultTable(
        "Modal contributions",
        ["Mode", "T [s]", "f [Hz]", "Γ [-]", "Mass ratio [-]", f"Sa(T) [{length}/s²]"],
        notes=list(r.warnings),
    )
    for m in r.modes:
        modes.rows.append(
            [
                m.mode_number,
                float(m.period),
                float(m.frequency),
                float(m.participation_factor),
                float(m.mass_ratio),
                float(m.sa_at_period) * converter.length,
            ]
        )
    return [combined, modes]


def node_history_table(
    r: TransientResults, node_id: int, kind: str = "disp", project: Project | None = None
) -> ResultTable:
    """Time history of one node: time, then every DOF of ``kind`` (disp, vel or accel)."""
    history = {
        "disp": r.node_disp_history,
        "vel": r.node_vel_history,
        "accel": r.node_accel_history,
    }[kind](node_id)
    layout = Layout.of(project, history.shape[-1])
    name = {"disp": "displacement", "vel": "velocity", "accel": "acceleration"}[kind]
    table = ResultTable(
        f"Node {node_id} {name} history",
        ["Time [s]"] + [layout.disp_column(d, kind) for d in range(1, history.shape[-1] + 1)],
    )
    factors = [layout.dof_factor(d, kind) for d in range(1, history.shape[-1] + 1)]
    for t, row in zip(r.time(), history, strict=True):
        table.rows.append(
            [float(t), *(float(v) * f for v, f in zip(row, factors, strict=True))],
        )
    return table


# ─────────────────────────── display and export ───────────────────────────
def display_text(value: Cell, digits: int) -> str:
    """A cell rounded to ``digits`` significant digits for display; text and ids as is."""
    if isinstance(value, float):
        return f"{value:.{digits}g}"
    return str(value)


def full_text(value: Cell) -> str:
    """A cell as exported: the shortest text that reads back to the same double."""
    if isinstance(value, float):
        return repr(value)
    return str(value)


def write_csv(table: ResultTable, path: Path | str) -> Path:
    """Write ``table`` with its header row (units in brackets) at full precision."""
    target = Path(path)
    with target.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(table.columns)
        for row in table.rows:
            writer.writerow([full_text(v) for v in row])
    return target
