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
from opensees_studio.core.mass_source import effective_nodal_masses
from opensees_studio.core.plane import dof_indices
from opensees_studio.core.section_cuts import cut_geometry
from opensees_studio.core.storey_results import (
    BASE_NAME,
    base_shear_from_reactions,
    combine_storey_response,
    storey_profile,
)
from opensees_studio.core.storeys import (
    StoreyLevel,
    base_elevation,
    lateral_axes,
    storey_levels,
)
from opensees_studio.core.units import UnitConverter, UnitLabels, UnitSystem
from opensees_studio.services.results import (
    CombinationResults,
    InfluenceLineResults,
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
        # The global axis: a 2D frame's rotation is about Y (core.plane).
        return dof_indices(self.ndm, self.ndf)[dof - 1] - 2

    def _translation_axis(self, dof: int) -> int:
        # The global axis: a 2D model's second DOF is Z (core.plane).
        return dof_indices(self.ndm, self.ndf)[dof - 1] + 1

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
        return f"{prefix}{self._translation_axis(dof)} [{self.labels.length}{per_time}]"

    def force_column(self, dof: int) -> str:
        """``F1 [N]``, ``M3 [N·m]``."""
        if self.is_rotation(dof):
            return f"M{self._rotation_axis(dof)} [{self.labels.moment}]"
        return f"F{self._translation_axis(dof)} [{self.labels.force}]"


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


def _bounded_node_table(
    title: str,
    upper: dict[int, np.ndarray],
    lower: dict[int, np.ndarray],
    layout: Layout,
    column: str,
) -> ResultTable:
    """Two rows per node, ``Max`` then ``Min``."""
    nodes = sorted(set(upper) & set(lower))
    ndf = int(np.atleast_2d(upper[nodes[0]]).shape[-1]) if nodes else layout.ndf
    is_force = column == "force"
    name = layout.force_column if is_force else layout.disp_column
    factor = layout.force_dof_factor if is_force else layout.dof_factor
    factors = np.array([factor(d) for d in range(1, ndf + 1)])
    table = ResultTable(title, ["Node", "Bound"] + [name(d) for d in range(1, ndf + 1)])
    for nid in nodes:
        a, b = np.atleast_2d(upper[nid])[-1], np.atleast_2d(lower[nid])[-1]
        for bound, values in (("Max", np.maximum(a, b)), ("Min", np.minimum(a, b))):
            table.rows.append([nid, bound, *(float(v) for v in values * factors)])
    return table


def _bounded_element_force_table(
    title: str,
    upper: dict[int, np.ndarray],
    lower: dict[int, np.ndarray],
    project: Project | None,
    layout: Layout,
) -> ResultTable:
    """One row per component with its ``localForce`` maximum and minimum."""
    by_id = {el.id: el for el in project.elements} if project is not None else {}
    table = ResultTable(title, ["Element", "Type", "Component", "Unit", "Max", "Min"])
    for eid in sorted(set(upper) & set(lower)):
        a, b = np.atleast_2d(upper[eid])[-1], np.atleast_2d(lower[eid])[-1]
        element = by_id.get(eid)
        kind = type(element).__name__ if element is not None else ""
        for (component, unit, factor), hi, lo in zip(
            _component_names(element, len(a), layout),
            np.maximum(a, b),
            np.minimum(a, b),
            strict=True,
        ):
            table.rows.append([eid, kind, component, unit, float(hi) * factor, float(lo) * factor])
    return table


def combination_tables(
    r: CombinationResults, project: Project | None = None
) -> list[tuple[str, ResultTable]]:
    """``(tab name, table)`` for each quantity the combination has.

    A single-valued combination reads like a static case. Otherwise every value
    has a maximum and a minimum; element forces are given per ``localForce``
    component, the same convention as a static case's table (the force diagram
    is what shows the envelope as internal forces).
    """
    ndf = next(iter(r.max.node_disp.values())).shape[-1] if r.max.node_disp else None
    layout = Layout.of(project, ndf)
    notes = list(r.warnings)
    tabs: list[tuple[str, ResultTable]] = []
    quantities = (
        ("node_disp", "Displacements", "displacements", "disp"),
        ("node_reaction", "Reactions", "reactions", "force"),
        ("element_forces", "Element forces", "element forces", ""),
    )
    for name, tab, what, column in quantities:
        if name in r.missing_fields:
            continue
        upper, lower = getattr(r.max, name), getattr(r.min, name)
        title = f"Combination '{r.combination_name}' {what}"
        if name == "element_forces":
            table = (
                element_force_table(title, upper, project, layout)
                if r.single_valued
                else _bounded_element_force_table(title, upper, lower, project, layout)
            )
        elif r.single_valued:
            table = _node_table(title, upper, layout, column)
        else:
            table = _bounded_node_table(title, upper, lower, layout, column)
        table.notes = list(notes)
        tabs.append((tab, table))
    return tabs


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
    tables = [combined]
    ndf = next(iter(r.node_reaction.values())).shape[-1] if r.node_reaction else None
    layout = Layout.of(project, ndf)
    if r.node_reaction:
        tables.append(
            _node_table(
                f"{r.combination} combined peak reactions (magnitudes)",
                r.node_reaction,
                layout,
                "force",
            )
        )
    if r.element_forces:
        tables.append(
            element_force_table(
                f"{r.combination} combined peak element forces (magnitudes)",
                r.element_forces,
                project,
                layout,
            )
        )
    tables.append(modes)
    return tables


# ─────────────────────────── storeys ───────────────────────────
def _storey_columns(layout: Layout, *, leading: list[str]) -> list[str]:
    labels = layout.labels
    axes = ("X",) if layout.ndm == 2 else ("X", "Y")
    return [
        *leading,
        "Storey",
        f"Elevation [{labels.length}]",
        f"Height [{labels.length}]",
        *(f"U{a} [{labels.length}]" for a in axes),
        *(f"Drift {a} [-]" for a in axes),
        *(f"Shear {a} [{labels.force}]" for a in axes),
    ]


def _storey_rows(
    profile_disp: np.ndarray,
    profile_drift: np.ndarray,
    shears: list[np.ndarray | None],
    base_disp: np.ndarray,
    base_shear: np.ndarray | None,
    levels: tuple[StoreyLevel, ...],
    base_z: float,
    layout: Layout,
    leading: list[Cell],
) -> list[list[Cell]]:
    """Top storey first, the base last, as ETABS lists them."""
    length = layout.converter.factor("length")
    force = layout.converter.factor("force")
    n = profile_disp.shape[1] if profile_disp.ndim == 2 else len(base_disp)
    blank: list[Cell] = [""] * n
    rows: list[list[Cell]] = []
    for k in reversed(range(len(levels))):
        level = levels[k]
        shear = shears[k]
        rows.append(
            [
                *leading,
                level.storey.name,
                level.storey.elevation * length,
                level.height * length,
                *(float(v) * length for v in profile_disp[k]),
                *(float(v) for v in profile_drift[k]),
                *(blank if shear is None else [float(v) * force for v in shear[:n]]),
            ]
        )
    rows.append(
        [
            *leading,
            BASE_NAME,
            base_z * length,
            "",
            *(float(v) * length for v in base_disp),
            *blank,
            *(blank if base_shear is None else [float(v) * force for v in base_shear[:n]]),
        ]
    )
    return rows


def storey_table(results: object, project: Project | None) -> ResultTable | None:
    """Storey displacement, drift ratio and shear; ``None`` without storeys above the base.

    Static: the last step, storey shears from the members cut above the level
    below, base shear from the reactions. Pushover: the last step, no shears.
    Modal: one block per mode (the mode shape, no shears). Response spectrum:
    peaks combined per quantity by the case's rule.
    """
    if project is None or not project.storeys:
        return None
    levels = tuple(storey_levels(project))
    if not levels:
        return None
    layout = Layout.of(project)
    base_z = base_elevation(project)
    lateral = len(lateral_axes(project.ndm))

    def last(values: dict[int, np.ndarray]) -> dict[int, np.ndarray]:
        return {nid: np.atleast_2d(v)[-1] for nid, v in values.items()}

    if isinstance(results, StaticResults):
        table = ResultTable("Storey response (final step)", _storey_columns(layout, leading=[]))
        profile = storey_profile(project, last(results.node_disp))
        shears = [
            np.atleast_2d(results.storey_shear[lv.storey.id])[-1]
            if lv.storey.id in results.storey_shear
            else None
            for lv in levels
        ]
        if any(v is None for v in shears):
            table.notes.append(
                "Storey shears need a re-run: the storeys changed after the analysis."
            )
        base = base_shear_from_reactions(project, last(results.node_reaction))
        table.rows = _storey_rows(
            profile.disp, profile.drift, shears, profile.base, base, levels, base_z, layout, []
        )
        return table
    if isinstance(results, PushoverResults):
        table = ResultTable("Storey response (final step)", _storey_columns(layout, leading=[]))
        profile = storey_profile(project, last(results.node_disp))
        table.rows = _storey_rows(
            profile.disp,
            profile.drift,
            [None] * len(levels),
            profile.base,
            None,
            levels,
            base_z,
            layout,
            [],
        )
        return table
    if isinstance(results, ModalResults):
        table = ResultTable(
            "Storey mode shapes", _storey_columns(layout, leading=["Mode", "T [s]"])
        )
        table.notes.append("Mode shapes as OpenSees normalises them; shears need a spectrum.")
        for mode in sorted(results.mode_shapes):
            profile = storey_profile(project, results.mode_shapes[mode])
            table.rows += _storey_rows(
                profile.disp,
                profile.drift,
                [None] * len(levels),
                profile.base,
                None,
                levels,
                base_z,
                layout,
                [mode, float(results.periods[mode - 1])],
            )
        return table
    if isinstance(results, ResponseSpectrumResults):
        modes = [m for m in results.modes if m.modal_peak_disp]
        combined = combine_storey_response(
            project,
            [m.modal_peak_disp for m in modes],
            [m.angular_frequency for m in modes],
            effective_nodal_masses(project),
            method=results.combination,
            damping=results.damping_ratio,
        )
        table = ResultTable(
            f"Storey response ({results.combination} peaks)",
            _storey_columns(layout, leading=[]),
            notes=list(results.warnings),
        )
        base_disp = np.zeros(lateral)
        table.rows = _storey_rows(
            combined.disp,
            combined.drift,
            list(combined.shear),
            base_disp,
            combined.base_shear,
            levels,
            base_z,
            layout,
            [],
        )
        return table
    return None


def influence_stops_table(results: InfluenceLineResults) -> ResultTable:
    """Where the moving load stood at each stop of an influence-line run."""
    table = ResultTable(
        "Stops of the moving load", ["Stop", "Distance along the path", "Member", "x / L"]
    )
    table.rows = [
        [k + 1, float(d), int(e), float(f)]
        for k, (d, e, f) in enumerate(
            zip(results.distances, results.element_ids, results.fractions, strict=True)
        )
    ]
    return table


def section_cut_table(results: object, project: Project | None) -> ResultTable | None:
    """Final-step resultant of every section cut (static cases); ``None`` without cuts."""
    if project is None or not project.section_cuts or not isinstance(results, StaticResults):
        return None
    layout = Layout.of(project)
    slots = dof_indices(project.ndm, project.ndf)
    table = ResultTable(
        "Section cut forces (final step)",
        ["Cut", "Group", "Centre", *(layout.force_column(k + 1) for k in range(len(slots)))],
    )
    groups = {g.id: g.name for g in project.groups}
    length = layout.converter.factor("length")
    for cut in project.section_cuts:
        values = results.section_cut_forces.get(cut.id)
        if values is None:
            table.notes.append(
                f"Cut {cut.name or cut.id} needs a re-run: it is newer than the analysis."
            )
            continue
        last = np.atleast_2d(values)[-1]
        centre = cut_geometry(project, cut).centre
        table.rows.append(
            [
                cut.name or str(cut.id),
                groups.get(cut.group_id, str(cut.group_id)),
                "(" + ", ".join(f"{c * length:g}" for c in centre) + ")",
                *(
                    float(last[slot]) * layout.force_dof_factor(k + 1)
                    for k, slot in enumerate(slots)
                ),
            ]
        )
    return table


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
