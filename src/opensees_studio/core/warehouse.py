"""Parametric steel warehouse: portal frames, purlins, girts, bracing, loads.

A "bodega" (nave industrial) here is a row of identical portal frames along
global Y, each in an X-Z plane: columns on a grid of nave spans carrying a roof
that is flat, single-pitched or double-pitched (the roof line and the column
heights are :class:`opensees_studio.core.frames.PortalFrameSpec`'s, so the 2D
wizard and this one cannot disagree). Between the frames run the secondary
members:

* **Purlins** on the roof, on lines equally spaced between the eaves, the ridge
  and the interior column lines, never further apart than the spacing asked
  for. The eave and ridge purlins double as the eave strut and the ridge tie.
* **Girts** on the two side walls (the walls along Y), the same way.
* **X bracing** of the roof and of the side walls in the braced bays (by
  default the first and the last).

Three rules that are easy to get wrong, and that the tests pin:

* **Secondary members are pinned.** Purlins, girts and braces release both
  bending moments at both ends (and a purlin or girt its torsion at one end),
  so they carry their own load to the frames and never add bending or
  torsional restraint to them.
* **A purlin does not brace the rafter unless it has a stabilising angle.** A
  purlin sits on the top flange; without a fly brace (the angle from the purlin
  down to the bottom flange) it does not hold the compression flange against
  lateral-torsional buckling. So :func:`member_design_overrides` gives every
  rafter element the unbraced length between *fly-braced* purlins, and the whole
  eave-to-ridge length when there are none; the girts and the side columns
  follow the same rule. Without the overrides ``core.design.members`` would take
  every purlin as a bracing point.
* **Loads act on the purlins**, as on the real roof: a load per area becomes a
  uniform load per length on each purlin element (its tributary width times the
  pressure), in the element's local axes — a purlin's web stands normal to the
  roof, so gravity has a component along both of them.

The module is pure (no Qt, no OpenSees): :func:`build_warehouse` returns the
geometry, :func:`plan_warehouse` everything a project needs to become that
warehouse (sections, load cases, loads, combinations, groups, grid, design
overrides) without touching the project, and :meth:`WarehousePlan.apply` writes
it for a script. The desktop inserts the same plan through undoable commands.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from opensees_studio.core.frames import (
    GRID_TOLERANCE,
    PortalFrameError,
    PortalFrameSpec,
    RoofType,
    SupportCondition,
)
from opensees_studio.core.geometry.elements import ElasticBeamColumn
from opensees_studio.core.geometry.frame_options import EndRelease, FrameReleases
from opensees_studio.core.geometry.grid import (
    CoordinateGridSystem,
    CoordinateSystem,
    GridSystem,
    make_grid_lines,
)
from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.geometry.node import Node, Restraint6
from opensees_studio.core.units import UnitSystem, force_scale, length_scale

if TYPE_CHECKING:
    from opensees_studio.core.project import Project

#: The model a warehouse is built in: a 3D frame model.
WAREHOUSE_NDF: tuple[int, int] = (3, 6)

#: Member groups, in the order they are created and listed, with their names.
GROUPS: dict[str, str] = {
    "columns": "Columns",
    "rafters": "Rafters",
    "purlins": "Purlins",
    "girts": "Girts",
    "roof_bracing": "Roof bracing",
    "wall_bracing": "Wall bracing",
}

#: Display colour of each group (#rrggbb).
GROUP_COLOURS: dict[str, str] = {
    "columns": "#4363d8",
    "rafters": "#e6194b",
    "purlins": "#3cb44b",
    "girts": "#469990",
    "roof_bracing": "#f58231",
    "wall_bracing": "#911eb4",
}

#: The section each kind of member takes: section key -> the groups it serves.
SECTION_KEYS: dict[str, str] = {
    "column": "Columns",
    "rafter": "Rafters",
    "purlin": "Purlins",
    "girt": "Girts",
    "brace": "Bracing",
}

#: AISC shape created for a section key when the caller chooses none.
DEFAULT_AISC_SHAPES: dict[str, str] = {
    "column": "W14X48",
    "rafter": "W16X40",
    "brace": "L3X3X1_4",
}

#: Default purlin and girt: a lipped channel 150 x 50 x 15 x 2.38 mm (a 2" x 6"
#: "perlín" of 3/32"), a size every local supplier lists. Dimensions in mm.
DEFAULT_PURLIN_MM: dict[str, float] = {"d": 150.0, "bf": 50.0, "lip": 15.0, "t": 2.38, "r": 2.38}

_PINNED = EndRelease(released=("M2", "M3"))
_PINNED_FREE_TORSION = EndRelease(released=("T", "M2", "M3"))
#: A brace: no moments at either end, torsion kept so it cannot spin.
BRACE_RELEASES = FrameReleases(i=_PINNED, j=_PINNED)
#: A purlin or girt: simply supported, torsion held at one end only.
SECONDARY_RELEASES = FrameReleases(i=_PINNED, j=_PINNED_FREE_TORSION)


class WarehouseError(ValueError):
    """The numbers do not describe a warehouse."""


@dataclass(frozen=True)
class WarehouseSpec:
    """A warehouse in project units: frames in X-Z planes, repeated along Y."""

    span: float
    """Width of one nave: the distance between column lines across the building."""
    eave_height: float
    frame_spacing: float
    """Distance between consecutive portal frames (the bay length along Y)."""
    n_frames: int = 5
    n_naves: int = 1
    roof: RoofType = RoofType.GABLE
    slope: float = 0.10
    support: SupportCondition = SupportCondition.PINNED
    purlin_spacing: float = 1.5
    """Largest distance between purlin lines, along the roof surface."""
    girt_spacing: float = 0.0
    """Largest distance between girt lines on the side walls; 0 = no girts."""
    rafter_fly_brace_every: int = 0
    """Every n-th purlin has a stabilising angle to the rafter's bottom flange; 0 = none."""
    column_fly_brace_every: int = 0
    """Every n-th girt has a stabilising angle to the column's inner flange; 0 = none."""
    roof_bracing: bool = True
    wall_bracing: bool = True
    braced_bays: tuple[int, ...] | None = None
    """Bays (0-based, between frame ``b`` and ``b + 1``) with X bracing; None = first and last."""
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def __post_init__(self) -> None:
        if self.span <= 0.0:
            raise WarehouseError("The nave span must be positive.")
        if self.eave_height <= 0.0:
            raise WarehouseError("The eave height must be positive.")
        if self.frame_spacing <= 0.0:
            raise WarehouseError("The distance between frames must be positive.")
        if self.n_frames < 2:
            raise WarehouseError("A warehouse needs at least two frames.")
        if self.n_naves < 1:
            raise WarehouseError("A warehouse needs at least one nave.")
        if not 0.0 <= self.slope < 1.0:
            raise WarehouseError("The roof slope must be between 0 and 100 %.")
        if self.purlin_spacing <= 0.0:
            raise WarehouseError("The purlin spacing must be positive.")
        if self.girt_spacing < 0.0:
            raise WarehouseError("The girt spacing cannot be negative.")
        if self.rafter_fly_brace_every < 0 or self.column_fly_brace_every < 0:
            raise WarehouseError("A stabilising angle interval cannot be negative.")
        if len(self.origin) != 3:
            raise WarehouseError("The origin needs three coordinates.")
        for bay in self.braced_bays or ():
            if not 0 <= bay < self.n_frames - 1:
                raise WarehouseError(
                    f"Braced bay {bay + 1} does not exist: there are {self.n_frames - 1} bay(s)."
                )

    # ── derived ─────────────────────────────────────────────────────
    @property
    def width(self) -> float:
        """Total width across the naves."""
        return self.span * self.n_naves

    @property
    def length(self) -> float:
        """Total length along the frames."""
        return self.frame_spacing * (self.n_frames - 1)

    @property
    def n_bays(self) -> int:
        return self.n_frames - 1

    @property
    def profile(self) -> PortalFrameSpec:
        """The roof line and column heights, shared with the 2D portal frame."""
        try:
            return PortalFrameSpec(
                bay_width=self.span,
                eave_height=self.eave_height,
                column_section_id=1,
                rafter_section_id=1,
                roof=self.roof,
                slope=self.slope,
                n_bays=self.n_naves,
                support=self.support,
                restrain_out_of_plane=False,
            )
        except PortalFrameError as exc:  # pragma: no cover - same checks as above
            raise WarehouseError(str(exc)) from exc

    @property
    def ridge_height(self) -> float:
        return self.profile.ridge_height

    def bracing_bays(self) -> tuple[int, ...]:
        """The braced bays, sorted; the first and the last when none were chosen."""
        if self.braced_bays is None:
            return tuple(sorted({0, self.n_bays - 1}))
        return tuple(sorted(set(self.braced_bays)))

    def column_lines(self) -> list[float]:
        """X of every column line, from the left eave."""
        return [i * self.span for i in range(self.n_naves + 1)]

    def roof_breaks(self) -> list[float]:
        """X where the rafter is held or changes direction: column lines and the ridge."""
        xs = self.column_lines()
        if self.roof is RoofType.GABLE:
            xs.append(self.width / 2.0)
        return _distinct(xs)

    def girt_heights(self) -> list[float]:
        """Elevation of each girt line above the base (none at the base or the eave)."""
        if self.girt_spacing <= 0.0:
            return []
        n = max(1, math.ceil(self.eave_height / self.girt_spacing - 1e-9))
        return [k * self.eave_height / n for k in range(1, n)]


def _distinct(values: Iterable[float]) -> list[float]:
    out: list[float] = []
    for value in sorted(values):
        if not out or abs(value - out[-1]) > GRID_TOLERANCE:
            out.append(value)
    return out


def _fly_braced(count: int, every: int) -> list[bool]:
    """Which of ``count + 1`` points along a segment are bracing points.

    The two ends always are (a column, the ridge, the base); an interior point
    ``k`` only when it carries a stabilising angle, every ``every``-th one.
    """
    return [k in (0, count) or (every > 0 and k % every == 0) for k in range(count + 1)]


def _unbraced_lengths(stations: list[float], braced: list[bool]) -> list[float]:
    """Per interval between consecutive ``stations``: the bracing-point distance around it."""
    out: list[float] = []
    for k in range(len(stations) - 1):
        start = max(i for i in range(k + 1) if braced[i])
        end = min(i for i in range(k + 1, len(stations)) if braced[i])
        out.append(stations[end] - stations[start])
    return out


@dataclass(frozen=True)
class RoofStation:
    """One purlin line: where it is on the roof and what it carries."""

    x: float
    z: float
    tributary_slope: float
    """Roof surface width the purlin carries (half way to each neighbour)."""
    tributary_plan: float
    """The same width in plan, for loads given on the horizontal projection."""
    angle: float
    """``local_axis_angle`` that stands the purlin's web normal to the roof, degrees."""
    fly_braced: bool
    """A bracing point of the rafter: a segment end, or a purlin with a stabilising angle."""


@dataclass
class Warehouse:
    """The built warehouse: models ready to insert, and what each element is."""

    spec: WarehouseSpec
    nodes: list[Node]
    elements: list[ElasticBeamColumn]
    members: dict[str, list[int]]
    """Group key (see :data:`GROUPS`) -> element ids."""
    stations: list[RoofStation]
    purlin_station: dict[int, int] = field(default_factory=dict)
    """Purlin element id -> index of its roof station."""
    rafter_elements: list[list[int]] = field(default_factory=list)
    """Per frame: the rafter element ids from the left eave, one per station interval."""
    unbraced: dict[int, float] = field(default_factory=dict)
    """Rafter and side-column element id -> unbraced length of its compression flange."""
    base_node_ids: list[int] = field(default_factory=list)

    def summary(self) -> str:
        """One line for the log: what was created."""
        spec = self.spec
        roof = {RoofType.MONO_PITCH: "1 slope", RoofType.GABLE: "2 slopes"}[spec.roof]
        return (
            f"Warehouse {spec.width:g} x {spec.length:g}: {spec.n_frames} frames at "
            f"{spec.frame_spacing:g}, {spec.n_naves} nave(s) of {spec.span:g}, eave "
            f"{spec.eave_height:g}, ridge {spec.ridge_height:g} ({roof}, "
            f"{spec.slope * 100:g} %) - {len(self.members['columns'])} column, "
            f"{len(self.members['rafters'])} rafter, {len(self.members['purlins'])} purlin, "
            f"{len(self.members['girts'])} girt and "
            f"{len(self.members['roof_bracing']) + len(self.members['wall_bracing'])} bracing "
            f"elements, {len(self.nodes)} nodes."
        )


def roof_stations(spec: WarehouseSpec) -> list[RoofStation]:
    """The purlin lines of ``spec``, from the left eave to the right one.

    Each stretch of roof between two breaks (column lines, the ridge) is divided
    into equal parts no longer than the purlin spacing, measured on the slope.
    """
    profile = spec.profile
    breaks = spec.roof_breaks()
    xs: list[float] = [breaks[0]]
    braced: list[bool] = [True]
    for a, b in itertools.pairwise(breaks):
        length = math.hypot(b - a, profile.roof_height(b) - profile.roof_height(a))
        count = max(1, math.ceil(length / spec.purlin_spacing - 1e-9))
        flags = _fly_braced(count, spec.rafter_fly_brace_every)
        for k in range(1, count + 1):
            xs.append(b if k == count else a + k * (b - a) / count)
            braced.append(flags[k])
    zs = [profile.roof_height(x) for x in xs]

    stations: list[RoofStation] = []
    last = len(xs) - 1
    for k, (x, z) in enumerate(zip(xs, zs, strict=True)):
        slope_width = plan_width = 0.0
        normal = np.zeros(3)
        for other in (k - 1, k + 1):
            if not 0 <= other <= last:
                continue
            dx, dz = xs[other] - x, zs[other] - z
            run = math.hypot(dx, dz)
            slope_width += run / 2.0
            plan_width += abs(dx) / 2.0
            # Upward normal of this stretch of roof (the roof line lies in X-Z).
            normal += np.array([-dz, 0.0, dx]) / run * (1.0 if dx > 0.0 else -1.0)
        # A purlin runs along +Y, so its local z is Z turned about Y by the
        # element angle: (sin a, 0, cos a). At the ridge the two normals average
        # to the vertical and the web stands plumb.
        angle = math.degrees(math.atan2(normal[0], normal[2]))
        stations.append(
            RoofStation(
                x=x,
                z=z,
                tributary_slope=slope_width,
                tributary_plan=plan_width,
                angle=0.0 if abs(angle) < 1e-9 else angle,
                fly_braced=braced[k],
            )
        )
    return stations


def _base_restraint(support: SupportCondition) -> Restraint6:
    fixed = support is SupportCondition.FIXED
    return (True, True, True, fixed, fixed, fixed)


_FREE: Restraint6 = (False, False, False, False, False, False)


def build_warehouse(
    spec: WarehouseSpec,
    sections: Mapping[str, int],
    *,
    first_node_id: int,
    first_element_id: int,
) -> Warehouse:
    """Build the nodes and elements of ``spec``.

    ``sections`` maps every key of :data:`SECTION_KEYS` to a section id. Ids are
    allocated from ``first_node_id`` / ``first_element_id`` upwards.
    """
    missing = [key for key in SECTION_KEYS if int(sections.get(key, 0) or 0) < 1]
    if missing:
        raise WarehouseError("No section for: " + ", ".join(missing) + ".")
    ox, oy, oz = spec.origin
    stations = roof_stations(spec)
    column_xs = spec.column_lines()
    girt_zs = spec.girt_heights()
    side_lines = (0, len(column_xs) - 1)

    nodes: list[Node] = []
    elements: list[ElasticBeamColumn] = []
    members: dict[str, list[int]] = {key: [] for key in GROUPS}
    counters = {"node": first_node_id, "element": first_element_id}

    def add_node(x: float, y: float, z: float, restraint: Restraint6 = _FREE) -> int:
        node_id = counters["node"]
        counters["node"] += 1
        nodes.append(Node(id=node_id, coords=(ox + x, oy + y, oz + z), restraint=restraint))
        return node_id

    def add_element(
        group: str,
        i: int,
        j: int,
        section: str,
        *,
        releases: FrameReleases | None = None,
        angle: float = 0.0,
    ) -> int:
        element_id = counters["element"]
        counters["element"] += 1
        extra: dict[str, Any] = {}
        if releases is not None:
            extra["releases"] = releases
        if angle:
            extra["local_axis_angle"] = angle
        elements.append(
            ElasticBeamColumn(
                id=element_id, nodes=(i, j), section_id=int(sections[section]), **extra
            )
        )
        members[group].append(element_id)
        return element_id

    def station_at(x: float) -> int:
        return next(k for k, s in enumerate(stations) if abs(s.x - x) <= GRID_TOLERANCE)

    warehouse = Warehouse(
        spec=spec, nodes=nodes, elements=elements, members=members, stations=stations
    )

    roof_nodes: list[list[int]] = []  # [frame][station]
    wall_nodes: list[dict[int, list[int]]] = []  # [frame][side line] -> base, girts..., eave
    rafter_lengths = _unbraced_lengths(
        _cumulative([(s.x, s.z) for s in stations]), [s.fly_braced for s in stations]
    )
    column_stations = [0.0, *girt_zs, spec.eave_height]
    column_lengths = _unbraced_lengths(
        column_stations, _fly_braced(len(girt_zs) + 1, spec.column_fly_brace_every)
    )

    for frame in range(spec.n_frames):
        y = frame * spec.frame_spacing
        tops = [add_node(s.x, y, s.z) for s in stations]
        roof_nodes.append(tops)
        walls: dict[int, list[int]] = {}
        for line, x in enumerate(column_xs):
            base = add_node(x, y, 0.0, _base_restraint(spec.support))
            warehouse.base_node_ids.append(base)
            top = tops[station_at(x)]
            chain = [base]
            if line in side_lines:
                chain += [add_node(x, y, z) for z in girt_zs]
            chain.append(top)
            for k, (a, b) in enumerate(itertools.pairwise(chain)):
                element_id = add_element("columns", a, b, "column")
                if line in side_lines and girt_zs:
                    warehouse.unbraced[element_id] = column_lengths[k]
            if line in side_lines:
                walls[line] = chain
        wall_nodes.append(walls)
        rafters: list[int] = []
        for k, (a, b) in enumerate(itertools.pairwise(tops)):
            element_id = add_element("rafters", a, b, "rafter")
            warehouse.unbraced[element_id] = rafter_lengths[k]
            rafters.append(element_id)
        warehouse.rafter_elements.append(rafters)

    for bay in range(spec.n_bays):
        near, far = roof_nodes[bay], roof_nodes[bay + 1]
        for k, station in enumerate(stations):
            element_id = add_element(
                "purlins", near[k], far[k], "purlin",
                releases=SECONDARY_RELEASES, angle=station.angle,
            )  # fmt: skip
            warehouse.purlin_station[element_id] = k
        for side, line in enumerate(side_lines):
            # A girt's web lies flat, to span the wall against the wind.
            angle = 90.0 if side == 0 else -90.0
            for level in range(1, len(girt_zs) + 1):
                add_element(
                    "girts",
                    wall_nodes[bay][line][level],
                    wall_nodes[bay + 1][line][level],
                    "girt",
                    releases=SECONDARY_RELEASES,
                    angle=angle,
                )

    for bay in spec.bracing_bays():
        if spec.roof_bracing:
            for a, b in _bracing_panels(spec, stations):
                near, far = roof_nodes[bay], roof_nodes[bay + 1]
                add_element("roof_bracing", near[a], far[b], "brace", releases=BRACE_RELEASES)
                add_element("roof_bracing", near[b], far[a], "brace", releases=BRACE_RELEASES)
        if spec.wall_bracing:
            for line in dict.fromkeys(side_lines):
                near_wall, far_wall = wall_nodes[bay][line], wall_nodes[bay + 1][line]
                add_element(
                    "wall_bracing", near_wall[0], far_wall[-1], "brace", releases=BRACE_RELEASES
                )
                add_element(
                    "wall_bracing", near_wall[-1], far_wall[0], "brace", releases=BRACE_RELEASES
                )
    return warehouse


def _cumulative(points: list[tuple[float, float]]) -> list[float]:
    """Distance of each point from the first along the polyline."""
    out = [0.0]
    for (x0, z0), (x1, z1) in itertools.pairwise(points):
        out.append(out[-1] + math.hypot(x1 - x0, z1 - z0))
    return out


def _bracing_panels(spec: WarehouseSpec, stations: list[RoofStation]) -> list[tuple[int, int]]:
    """Station index pairs ``(a, b)`` of each roof bracing panel.

    Each stretch of roof between two breaks is cut into panels about as long as
    the bay, on purlin lines, so the diagonals stay near 45 degrees.
    """
    breaks = spec.roof_breaks()
    index = {
        b: next(k for k, s in enumerate(stations) if abs(s.x - b) <= GRID_TOLERANCE) for b in breaks
    }
    along = _cumulative([(s.x, s.z) for s in stations])
    panels: list[tuple[int, int]] = []
    for a, b in itertools.pairwise(breaks):
        first, last = index[a], index[b]
        count = last - first
        wanted = max(1, min(count, round((along[last] - along[first]) / spec.frame_spacing)))
        cuts = sorted({first + round(j * count / wanted) for j in range(wanted + 1)})
        panels += list(itertools.pairwise(cuts))
    return panels


# ─────────────────────────── grid and groups ───────────────────────────
def warehouse_grid(spec: WarehouseSpec, *, name: str = "Warehouse") -> CoordinateGridSystem:
    """A grid on the column lines, the frames, and the base, eave and ridge levels."""
    xs = spec.roof_breaks()
    ys = [k * spec.frame_spacing for k in range(spec.n_frames)]
    zs = _distinct([0.0, spec.eave_height, spec.ridge_height, *spec.profile.column_heights()])
    return CoordinateGridSystem(
        name=name,
        coord=CoordinateSystem(origin=spec.origin),
        grid=GridSystem(
            x_grid_lines=make_grid_lines("X", xs),
            y_grid_lines=make_grid_lines("Y", ys),
            z_grid_lines=make_grid_lines("Z", zs),
        ),
    )


# ─────────────────────────────── loads ───────────────────────────────
def _gravity_components(nodes: Mapping[int, Node], element: ElasticBeamColumn) -> np.ndarray:
    """Local ``(x, y, z)`` components of a unit downward (-Z) load on ``element``."""
    axes = frame_local_axes(
        3,
        nodes[element.nodes[0]].coords,
        nodes[element.nodes[1]].coords,
        element.local_axis_angle,
    )
    assert axes is not None  # a warehouse has no zero-length member
    return np.array([-float(axis[2]) for axis in axes])


def roof_pressure_loads(warehouse: Warehouse, pressure: float, *, projected: bool) -> list[Any]:
    """A downward load per roof area as uniform loads on the purlins.

    ``projected`` reads ``pressure`` per area of horizontal projection (a live
    load); otherwise per area of roof surface (the weight of the cladding).
    """
    from opensees_studio.core.loads import UniformElementLoad

    if pressure == 0.0:
        return []
    nodes = {n.id: n for n in warehouse.nodes}
    purlins = {e.id: e for e in warehouse.elements if e.id in warehouse.purlin_station}
    loads: list[Any] = []
    for element_id, k in warehouse.purlin_station.items():
        station = warehouse.stations[k]
        width = station.tributary_plan if projected else station.tributary_slope
        _wx, wy, wz = _gravity_components(nodes, purlins[element_id]) * pressure * width
        loads.append(UniformElementLoad(element_id=element_id, wy=float(wy), wz=float(wz)))
    return loads


def midspan_point_loads(warehouse: Warehouse, force: float) -> tuple[list[Any], list[Any]]:
    """A downward force at mid-span of every nave of every frame.

    Returns ``(nodal loads, point element loads)``: the force goes on the node
    when a purlin line falls at mid-span (the ridge of a single-nave gable) and
    inside the rafter element otherwise.
    """
    from opensees_studio.core.loads import NodalLoad, PointElementLoad

    if force == 0.0:
        return [], []
    spec = warehouse.spec
    stations = warehouse.stations
    nodes = {n.id: n for n in warehouse.nodes}
    elements = {e.id: e for e in warehouse.elements}
    nodal: list[Any] = []
    inside: list[Any] = []
    for rafters in warehouse.rafter_elements:
        for nave in range(spec.n_naves):
            x = (nave + 0.5) * spec.span
            at = next((k for k, s in enumerate(stations) if abs(s.x - x) <= GRID_TOLERANCE), None)
            if at is not None:
                # Either element at the station shares the node: its end there.
                element = elements[rafters[min(at, len(rafters) - 1)]]
                node_id = element.nodes[0] if at < len(rafters) else element.nodes[1]
                nodal.append(NodalLoad(node_id=node_id, forces=(0.0, 0.0, -force, 0.0, 0.0, 0.0)))
                continue
            k = max(i for i, s in enumerate(stations) if s.x < x)
            element = elements[rafters[k]]
            px, py, pz = _gravity_components(nodes, element) * force
            inside.append(
                PointElementLoad(
                    element_id=element.id,
                    px=float(px),
                    py=float(py),
                    pz=float(pz),
                    x=(x - stations[k].x) / (stations[k + 1].x - stations[k].x),
                )
            )
    return nodal, inside


# ─────────────────────────── design lengths ───────────────────────────
def member_design_overrides(warehouse: Warehouse) -> list[Any]:
    """Unbraced lengths of the rafters and side columns for the steel check.

    Minor-axis buckling and lateral-torsional buckling take the distance
    between bracing points: a purlin (or a girt) counts only where it has a
    stabilising angle. Major-axis buckling stays as modelled.
    """
    from opensees_studio.core.design.settings import SteelMemberDesign

    return [
        SteelMemberDesign(element_id=element_id, length_minor=length, length_ltb=length)
        for element_id, length in sorted(warehouse.unbraced.items())
    ]


# ───────────────────────── code presets and defaults ─────────────────────────
@dataclass(frozen=True)
class CodePreset:
    """What a design code fixes for a warehouse's gravity loads and combinations."""

    key: str
    """Key of :data:`opensees_studio.core.code_combinations.CODES`."""
    roof_live_role: str
    """Load role of the roof live case: the code's combinations use this one."""
    roof_live_case: str
    roof_live_kpa: float
    """Default uniform roof live load, kN/m² of horizontal projection."""
    midspan_point_kn: float
    """Default concentrated roof live load at mid-span of each frame, kN."""
    design_method: str
    source: str
    """Where the two defaults come from, for the wizard's tool tip."""


_KGF = 9.80665e-3  # one kilogram-force in kN

#: The codes the wizard offers, in order. RNC-07 Art. 11 a (light roofs): main
#: members carry 10 kg/m² plus 200 kg at mid-span; NSCM is the seismic code of
#: Managua and keeps RNC-07's gravity loads. ASCE 7-16 Table 4.3-1: 20 psf.
CODE_PRESETS: dict[str, CodePreset] = {
    preset.key: preset
    for preset in (
        CodePreset(
            "rnc07", "L", "LIVE", 10 * _KGF, 200 * _KGF, "LRFD",
            "RNC-07 Art. 11 a: light roofs, 10 kg/m² plus 200 kg at mid-span of the main members.",
        ),
        CodePreset(
            "nscm", "Lr", "ROOF LIVE", 10 * _KGF, 200 * _KGF, "LRFD",
            "RNC-07 Art. 11 a: light roofs, 10 kg/m² plus 200 kg at mid-span of the main members.",
        ),
        CodePreset(
            "asce7_lrfd", "Lr", "ROOF LIVE", 0.9576, 0.0, "LRFD",
            "ASCE 7-16 Table 4.3-1: ordinary roofs, 20 psf (before any reduction).",
        ),
        CodePreset(
            "asce7_asd", "Lr", "ROOF LIVE", 0.9576, 0.0, "ASD",
            "ASCE 7-16 Table 4.3-1: ordinary roofs, 20 psf (before any reduction).",
        ),
    )
}  # fmt: skip

#: Default superimposed roof dead load (cladding and fixings), kN/m² of roof.
DEFAULT_ROOF_DEAD_KPA = 0.10


def pressure_from_kpa(value: float, units: UnitSystem) -> float:
    """``value`` kN/m² in the force / length² of ``units``."""
    return (
        value * 1e3 * force_scale(UnitSystem.SI_M_N, units)
        / length_scale(UnitSystem.SI_M_N, units) ** 2
    )  # fmt: skip


def force_from_kn(value: float, units: UnitSystem) -> float:
    """``value`` kN in the force of ``units``."""
    return value * 1e3 * force_scale(UnitSystem.SI_M_N, units)


def length_from_m(value: float, units: UnitSystem) -> float:
    """``value`` metres in the length of ``units``."""
    return value * length_scale(UnitSystem.SI_M_N, units)


@dataclass(frozen=True)
class WarehouseLoads:
    """The gravity loads of the roof, in project units, and what to derive from them."""

    code: str = "rnc07"
    roof_dead: float = 0.0
    """Superimposed dead load per area of roof surface (the self weight is separate)."""
    roof_live: float = 0.0
    """Live load per area of horizontal projection."""
    midspan_point: float = 0.0
    """Concentrated live load at mid-span of each nave of each frame."""
    combinations: bool = True
    design_lengths: bool = True

    def __post_init__(self) -> None:
        if self.code not in CODE_PRESETS:
            raise WarehouseError(f"Unknown design code {self.code!r}.")
        if min(self.roof_dead, self.roof_live, self.midspan_point) < 0.0:
            raise WarehouseError("Loads are entered as positive, downward values.")


def default_section(key: str, project: Project, section_id: int) -> Any:
    """The section a warehouse member takes when the user chooses none.

    Columns, rafters and braces come from the AISC library, purlins and girts
    are a lipped cold-formed channel; each is made of the project's default
    steel when it has it.
    """
    from opensees_studio.core.aisc import get_shape, shape_to_elastic_section
    from opensees_studio.core.cold_formed_sections import (
        cold_formed_section,
        default_cold_formed_material,
    )
    from opensees_studio.core.default_materials import find_default_material
    from opensees_studio.core.section_materials import linked
    from opensees_studio.core.sections.cold_formed import ColdFormedShape
    from opensees_studio.core.units import stress_scale

    units = project.meta.units
    e = 200e9 * stress_scale(UnitSystem.SI_M_N, units)
    g = e / 2.6
    if key in ("purlin", "girt"):
        mm = length_scale(UnitSystem.SI_MM_N, units)
        size = DEFAULT_PURLIN_MM
        shape = ColdFormedShape(
            profile="CS",
            d=size["d"] * mm,
            bf=size["bf"] * mm,
            lip=size["lip"] * mm,
            t=size["t"] * mm,
            r=size["r"] * mm,
        )
        return cold_formed_section(
            shape,
            section_id=section_id,
            ndm=project.ndm,
            name="C150X50X15X2.38",
            material=default_cold_formed_material(project),
            units=units,
            elastic_modulus=e,
            shear_modulus=g,
        )
    section = shape_to_elastic_section(
        get_shape(DEFAULT_AISC_SHAPES[key]),
        elastic_modulus=e,
        shear_modulus=g,
        section_id=section_id,
        units=units,
        ndm=project.ndm,
        with_shear_areas=True,
    )
    material = find_default_material(project)
    return linked(section, material, units) if material is not None else section


def default_section_name(key: str) -> str:
    """Name of the section :func:`default_section` creates for ``key``."""
    return "C150X50X15X2.38" if key in ("purlin", "girt") else DEFAULT_AISC_SHAPES[key]


# ─────────────────────────────── the plan ───────────────────────────────
@dataclass
class WarehousePlan:
    """Everything a project gains to become the warehouse; nothing is applied yet."""

    warehouse: Warehouse
    sections: list[Any] = field(default_factory=list)
    """New sections, created because a member kind had none chosen."""
    groups: list[Any] = field(default_factory=list)
    grid: CoordinateGridSystem | None = None
    time_series: list[Any] = field(default_factory=list)
    patterns: list[Any] = field(default_factory=list)
    cases: list[Any] = field(default_factory=list)
    pattern_loads: list[tuple[int, str, list[Any]]] = field(default_factory=list)
    """``(pattern id, PlainLoadPattern list name, loads)`` to append."""
    combinations: list[Any] = field(default_factory=list)
    design: Any = None
    """The project's design settings with the unbraced lengths, or None to leave them."""
    notes: list[str] = field(default_factory=list)

    def apply(self, project: Project) -> None:
        """Write the plan into ``project`` (headless: scripts and tests, no undo)."""
        project.sections.extend(self.sections)
        project.nodes.extend(self.warehouse.nodes)
        project.elements.extend(self.warehouse.elements)
        project.groups.extend(self.groups)
        if self.grid is not None:
            project.coord_systems.append(self.grid)
        project.time_series.extend(self.time_series)
        project.load_patterns.extend(self.patterns)
        project.analyses.extend(self.cases)
        patterns = {p.id: p for p in project.load_patterns}
        for pattern_id, list_name, loads in self.pattern_loads:
            getattr(patterns[pattern_id], list_name).extend(loads)
        project.combinations.extend(self.combinations)
        if self.design is not None:
            project.design = self.design


def envelope_name(group: str) -> str:
    """Name of the envelope over the combinations of ``group``."""
    return f"{group} envelope"


def plan_warehouse(
    project: Project,
    spec: WarehouseSpec,
    *,
    sections: Mapping[str, int | None] | None = None,
    loads: WarehouseLoads | None = None,
    with_grid: bool = True,
    group_names: Mapping[str, str] | None = None,
) -> WarehousePlan:
    """Plan the warehouse ``spec`` for ``project`` without changing the project.

    ``sections`` gives the section id of each member kind (:data:`SECTION_KEYS`);
    a missing or None entry gets :func:`default_section`. ``loads`` adds the roof
    loads to the dead case and to a roof live case (created when the project has
    none of that name), the combinations of its code, and the unbraced lengths
    of the steel check. ``group_names`` renames the groups (a translation).

    Raises:
        WarehouseError: when the project is not a 3D frame model, or the numbers
            do not describe a warehouse.
    """
    from opensees_studio.core.groups import Group

    if (project.ndm, project.ndf) != WAREHOUSE_NDF:
        raise WarehouseError(
            "A warehouse needs a 3D frame model (ndm = 3, ndf = 6); this project is "
            f"ndm = {project.ndm}, ndf = {project.ndf}."
        )
    # Ids come from a scratch copy that receives each piece as it is planned,
    # so two things planned together never get the same id.
    scratch = project.model_copy(deep=True)
    chosen = dict(sections or {})
    existing = {s.id for s in project.sections}
    section_ids: dict[str, int] = {}
    new_sections: list[Any] = []
    created: dict[str, int] = {}
    for key in SECTION_KEYS:
        section_id = chosen.get(key)
        if section_id is not None:
            if section_id not in existing:
                raise WarehouseError(f"Section {section_id} ({key}) is not in the project.")
            section_ids[key] = int(section_id)
            continue
        name = default_section_name(key)
        if name not in created:
            section = default_section(key, scratch, scratch.next_section_id())
            scratch.sections.append(section)
            new_sections.append(section)
            created[name] = section.id
        section_ids[key] = created[name]

    warehouse = build_warehouse(
        spec,
        section_ids,
        first_node_id=project.next_node_id(),
        first_element_id=project.next_element_id(),
    )
    plan = WarehousePlan(warehouse=warehouse, sections=new_sections)
    scratch.nodes.extend(warehouse.nodes)
    scratch.elements.extend(warehouse.elements)

    names = {**GROUPS, **(group_names or {})}
    taken = {g.name for g in project.groups}
    for key in GROUPS:
        ids = warehouse.members[key]
        if not ids:
            continue
        name, n = names[key], 2
        while name in taken:
            name, n = f"{names[key]} {n}", n + 1
        taken.add(name)
        group = Group(
            id=scratch.next_group_id(), name=name, element_ids=ids, colour=GROUP_COLOURS[key]
        )
        scratch.groups.append(group)
        plan.groups.append(group)
    if with_grid:
        grid_name, n = "Warehouse", 2
        while any(c.name == grid_name for c in project.coord_systems):
            grid_name, n = f"Warehouse {n}", n + 1
        plan.grid = warehouse_grid(spec, name=grid_name)

    if loads is not None:
        _plan_loads(plan, project, scratch, loads)
    return plan


def _static_cases_of(project: Project, pattern_id: int) -> list[int]:
    return [
        c.id
        for c in project.analyses
        if c.type == "Static" and pattern_id in getattr(c, "pattern_ids", ())
    ]


def _plan_loads(
    plan: WarehousePlan, project: Project, scratch: Project, loads: WarehouseLoads
) -> None:
    """The load cases, the roof loads, the combinations and the design lengths."""
    from opensees_studio.core.code_combinations import (
        CODES,
        envelope_groups,
        generate_for_code,
    )
    from opensees_studio.core.combinations import CombinationTerm, LoadCombination
    from opensees_studio.core.defaults import make_dead_load_case, make_load_cases
    from opensees_studio.core.design.settings import DesignSettings
    from opensees_studio.core.loads import PlainLoadPattern

    preset = CODE_PRESETS[loads.code]
    warehouse = plan.warehouse

    def add_case(series: Any, pattern: Any, case: Any) -> None:
        for target, planned, item in (
            (scratch.time_series, plan.time_series, series),
            (scratch.load_patterns, plan.patterns, pattern),
            (scratch.analyses, plan.cases, case),
        ):
            target.append(item)
            planned.append(item)

    dead = next(
        (p for p in project.load_patterns if isinstance(p, PlainLoadPattern) and p.self_weight),
        None,
    )
    if dead is None:
        add_case(*make_dead_load_case(scratch))
        dead = plan.patterns[-1]
    live = next(
        (
            p
            for p in project.load_patterns
            if isinstance(p, PlainLoadPattern)
            and p.name == preset.roof_live_case
            and _static_cases_of(project, p.id)
        ),
        None,
    )
    if live is None and (loads.roof_live or loads.midspan_point):
        series, patterns, cases = make_load_cases(scratch, [preset.roof_live_case])
        add_case(series[0], patterns[0], cases[0])
        live = patterns[0]

    dead_loads = roof_pressure_loads(warehouse, loads.roof_dead, projected=False)
    if dead_loads:
        plan.pattern_loads.append((dead.id, "element_loads", dead_loads))
    if live is not None:
        live_loads = roof_pressure_loads(warehouse, loads.roof_live, projected=True)
        nodal, inside = midspan_point_loads(warehouse, loads.midspan_point)
        for list_name, items in (
            ("element_loads", live_loads),
            ("nodal_loads", nodal),
            ("point_loads", inside),
        ):
            if items:
                plan.pattern_loads.append((live.id, list_name, items))

    if loads.combinations:
        roles: dict[str, list[int]] = {"D": _static_cases_of(scratch, dead.id)}
        if live is not None:
            roles[preset.roof_live_role] = _static_cases_of(scratch, live.id)
        case_names = {c.id: c.name or str(c.id) for c in scratch.analyses}
        generated = generate_for_code(loads.code, roles, case_names=case_names)
        used = {c.name for c in project.combinations}
        fresh = [g for g in generated if g.name not in used]
        if len(fresh) < len(generated):
            plan.notes.append(
                f"{len(generated) - len(fresh)} {CODES[loads.code].label} combination(s) "
                "already existed and were kept."
            )
        next_id = scratch.next_combination_id()
        ids_by_group: dict[str, list[int]] = {g: [] for g in envelope_groups(fresh)}
        for combo in fresh:
            combination = LoadCombination(
                id=next_id + len(plan.combinations), name=combo.name, terms=combo.terms
            )
            plan.combinations.append(combination)
            ids_by_group[combo.group].append(combination.id)
        for group, ids in ids_by_group.items():
            if len(ids) > 1 and envelope_name(group) not in used:
                plan.combinations.append(
                    LoadCombination(
                        id=next_id + len(plan.combinations),
                        name=envelope_name(group),
                        combination_type="Envelope",
                        terms=[CombinationTerm(source="combination", ref_id=i) for i in ids],
                    )
                )

    if loads.design_lengths:
        overrides = member_design_overrides(warehouse)
        if overrides:
            base = project.design
            if base is None:
                base = DesignSettings(method=preset.design_method)  # type: ignore[arg-type]
            plan.design = base.model_copy(update={"members": [*base.members, *overrides]})


__all__ = [
    "BRACE_RELEASES",
    "CODE_PRESETS",
    "DEFAULT_AISC_SHAPES",
    "DEFAULT_ROOF_DEAD_KPA",
    "GROUPS",
    "GROUP_COLOURS",
    "SECONDARY_RELEASES",
    "SECTION_KEYS",
    "WAREHOUSE_NDF",
    "CodePreset",
    "RoofStation",
    "Warehouse",
    "WarehouseError",
    "WarehouseLoads",
    "WarehousePlan",
    "WarehouseSpec",
    "build_warehouse",
    "default_section",
    "default_section_name",
    "envelope_name",
    "force_from_kn",
    "length_from_m",
    "member_design_overrides",
    "midspan_point_loads",
    "plan_warehouse",
    "pressure_from_kpa",
    "roof_pressure_loads",
    "roof_stations",
    "warehouse_grid",
]
