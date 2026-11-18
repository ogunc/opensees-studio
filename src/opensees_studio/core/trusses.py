"""Parametric plane trusses: chords, web pattern, supports.

A truss here is the classic simply supported plane truss: a bottom chord on
``n_panels`` equal panels, a top chord that is either parallel to it or pitched
to a ridge at mid-span, and a web of one of four patterns:

* **Pratt** — verticals, and diagonals running down towards mid-span (in
  tension under gravity);
* **Howe** — verticals, and diagonals running up towards mid-span (in
  compression under gravity);
* **Warren** — no verticals: diagonals zig-zag between the bottom panel points
  and top nodes at the middle of each panel;
* **Warren with verticals** — the zig-zag between panel points, plus verticals.

The left end is pinned and the right end on a roller. Members are two-node
``truss`` elements (axial only), chords and web with their own area. A pitched
truss may end at zero depth (a triangular truss): members that would then have
no length or repeat a chord are left out.

Every node of a truss carries only translational stiffness, so the rotational
DOF of a frame model (``ndf`` 3 or 6) are restrained at every truss node, and in
3D the out-of-plane translation too when asked (a truss analysed on its own).

Pure: no Qt, no OpenSeesPy. Like :mod:`core.frames`, a spec is checked once,
and the wizard, the geometry and the tests all read it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Literal

from opensees_studio.core.frames import PLANE_AXES
from opensees_studio.core.geometry.elements import TrussElement
from opensees_studio.core.geometry.node import Node, Restraint6

#: (ndm, ndf) pairs a plane truss can be built in.
TRUSS_NDF: frozenset[tuple[int, int]] = frozenset({(2, 2), (2, 3), (3, 3), (3, 6)})

#: Out-of-plane translation index per plane (canonical 6-DOF storage).
_OUT_OF_PLANE_TRANSLATION = {"XY": 2, "XZ": 1, "YZ": 0}

Plane = Literal["XZ", "YZ"]
"""Planes a truss can stand in (Z up); a 2D project lives in XZ (core.plane)."""


class TrussType(enum.Enum):
    PRATT = "pratt"
    HOWE = "howe"
    WARREN = "warren"
    WARREN_VERTICALS = "warren_verticals"


#: (label, type) in the order the wizard offers them.
TRUSS_TYPE_LABELS: list[tuple[str, TrussType]] = [
    ("Pratt", TrussType.PRATT),
    ("Howe", TrussType.HOWE),
    ("Warren", TrussType.WARREN),
    ("Warren with verticals", TrussType.WARREN_VERTICALS),
]


class TrussError(ValueError):
    """The specification cannot describe a truss."""


@dataclass(frozen=True)
class TrussSpec:
    """Everything the wizard asks for. Dimensions are in project units.

    ``depth`` is the depth at mid-span; ``end_depth`` the depth at the supports
    (equal to ``depth`` for parallel chords, smaller for a pitched top chord,
    0 for a triangular truss).
    """

    span: float
    depth: float
    n_panels: int
    material_id: int
    chord_area: float
    web_area: float
    truss_type: TrussType = TrussType.PRATT
    end_depth: float | None = None  # None: parallel chords
    plane: Plane = "XZ"
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
    restrain_out_of_plane: bool = True
    unit_weight: float = 0.0  # weight per volume of every bar (self weight)

    def __post_init__(self) -> None:
        if self.span <= 0.0:
            raise TrussError("The span must be positive.")
        if self.depth <= 0.0:
            raise TrussError("The depth must be positive.")
        if self.n_panels < 2:
            raise TrussError("A truss needs at least two panels.")
        if self.end_depth is not None and not 0.0 <= self.end_depth <= self.depth:
            raise TrussError("The depth at the supports must be between 0 and the mid-span depth.")
        if self.chord_area <= 0.0 or self.web_area <= 0.0:
            raise TrussError("Both member areas must be positive.")
        if self.unit_weight < 0.0:
            raise TrussError("The unit weight cannot be negative.")
        if self.material_id < 1:
            raise TrussError("The members need a material.")
        if self.plane not in ("XZ", "YZ"):  # an elevation: Z is up
            raise TrussError(f"Unknown plane {self.plane!r}.")
        if self.is_pitched:
            warren = self.truss_type is TrussType.WARREN
            if warren and self.n_panels % 2 == 0:
                raise TrussError(
                    "A pitched Warren truss needs an odd number of panels, so a top node "
                    "sits at the ridge."
                )
            if not warren and self.n_panels % 2 == 1:
                raise TrussError(
                    "A pitched truss needs an even number of panels, so a panel point "
                    "sits at the ridge."
                )

    # ── derived geometry ────────────────────────────────────────────
    @property
    def is_pitched(self) -> bool:
        return self.end_depth is not None and self.end_depth < self.depth

    @property
    def panel(self) -> float:
        return self.span / self.n_panels

    def top_height(self, x: float) -> float:
        """Height of the top chord ``x`` along the span."""
        if not self.is_pitched:
            return self.depth
        assert self.end_depth is not None
        run = min(x, self.span - x) / (self.span / 2.0)
        return self.end_depth + (self.depth - self.end_depth) * max(0.0, min(1.0, run))

    # ── restraints ──────────────────────────────────────────────────
    def restraint(
        self, support: Literal["pin", "roller", "free"], *, ndm: int, ndf: int
    ) -> Restraint6:
        """The 6-DOF restraint vector of a truss node."""
        if (ndm, ndf) not in TRUSS_NDF:
            raise TrussError(f"Unsupported (ndm, ndf): ({ndm}, {ndf}).")
        span_axis, height_axis, _ = PLANE_AXES[self.plane] if ndm == 3 else PLANE_AXES["XZ"]
        flags = [False] * 6
        if support == "pin":
            flags[span_axis] = flags[height_axis] = True
        elif support == "roller":
            flags[height_axis] = True
        if ndm == 3 and (self.restrain_out_of_plane or support != "free"):
            flags[_OUT_OF_PLANE_TRANSLATION[self.plane]] = True
        if ndf == 3 and ndm == 2:
            flags[4] = True  # Ry: a truss node has no rotational stiffness
        if ndf == 6:
            flags[3] = flags[4] = flags[5] = True
        return (flags[0], flags[1], flags[2], flags[3], flags[4], flags[5])


@dataclass(frozen=True)
class Truss:
    """The built truss: models ready to be inserted, and what they are."""

    nodes: list[Node]
    elements: list[TrussElement]
    spec: TrussSpec
    chord_element_ids: list[int]
    web_element_ids: list[int]

    def summary(self) -> str:
        label = dict((t, name) for name, t in TRUSS_TYPE_LABELS)[self.spec.truss_type]
        chords = "pitched" if self.spec.is_pitched else "parallel chords"
        return (
            f"{label} truss in {self.spec.plane}: span {self.spec.span:g}, depth "
            f"{self.spec.depth:g} ({chords}), {self.spec.n_panels} panels - "
            f"{len(self.nodes)} nodes, {len(self.chord_element_ids)} chord and "
            f"{len(self.web_element_ids)} web members."
        )


def build_truss(
    spec: TrussSpec,
    *,
    ndm: int,
    ndf: int,
    first_node_id: int,
    first_element_id: int,
) -> Truss:
    """Build the nodes and truss elements of ``spec``, ids counted up from the given ones.

    Raises:
        TrussError: if ``(ndm, ndf)`` cannot carry a plane truss, or a 2D model
            is asked for a plane other than XZ.
    """
    if (ndm, ndf) not in TRUSS_NDF:
        raise TrussError(f"Unsupported (ndm, ndf): ({ndm}, {ndf}).")
    if ndm == 2 and spec.plane != "XZ":
        raise TrussError("A 2D project builds its trusses in the XZ plane.")

    span_axis, height_axis, _ = PLANE_AXES[spec.plane]

    def point(x: float, height: float) -> tuple[float, float, float]:
        coords = list(spec.origin)
        coords[span_axis] += x
        coords[height_axis] += height
        return (coords[0], coords[1], coords[2])

    nodes: list[Node] = []
    next_node = first_node_id

    def add_node(x: float, height: float, support: Literal["pin", "roller", "free"]) -> int:
        nonlocal next_node
        node = Node(
            id=next_node,
            coords=point(x, height),
            restraint=spec.restraint(support, ndm=ndm, ndf=ndf),
        )
        nodes.append(node)
        next_node += 1
        return node.id

    n = spec.n_panels
    bottom = [
        add_node(i * spec.panel, 0.0, "pin" if i == 0 else "roller" if i == n else "free")
        for i in range(n + 1)
    ]

    warren = spec.truss_type is TrussType.WARREN
    if warren:
        top = [
            add_node((i + 0.5) * spec.panel, spec.top_height((i + 0.5) * spec.panel), "free")
            for i in range(n)
        ]
    else:
        top = []
        for i in range(n + 1):
            x = i * spec.panel
            height = spec.top_height(x)
            # A triangular truss closes on its supports: the top chord starts there.
            top.append(bottom[i] if height <= 1e-12 else add_node(x, height, "free"))

    chords: list[tuple[int, int]] = [(bottom[i], bottom[i + 1]) for i in range(n)]
    chords += [(top[i], top[i + 1]) for i in range(len(top) - 1)]
    web: list[tuple[int, int]] = []
    half = n / 2.0
    if warren:
        for i in range(n):
            web += [(bottom[i], top[i]), (top[i], bottom[i + 1])]
    else:
        web += [(bottom[i], top[i]) for i in range(n + 1)]  # verticals (ends included)
        for i in range(n):
            left_half = i + 0.5 < half
            if spec.truss_type is TrussType.PRATT:
                web.append((top[i], bottom[i + 1]) if left_half else (bottom[i], top[i + 1]))
            elif spec.truss_type is TrussType.HOWE:
                web.append((bottom[i], top[i + 1]) if left_half else (top[i], bottom[i + 1]))
            else:  # Warren with verticals: alternate, symmetric about mid-span
                rising = (i % 2 == 0) if left_half else ((n - 1 - i) % 2 == 1)
                web.append((bottom[i], top[i + 1]) if rising else (top[i], bottom[i + 1]))

    elements: list[TrussElement] = []
    chord_ids: list[int] = []
    web_ids: list[int] = []
    seen: set[frozenset[int]] = set()
    next_element = first_element_id
    for members, area, ids in ((chords, spec.chord_area, chord_ids), (web, spec.web_area, web_ids)):
        for i, j in members:
            key = frozenset((i, j))
            if i == j or key in seen:
                continue  # no length (a closed end), or the same bar as a chord
            seen.add(key)
            elements.append(
                TrussElement(
                    id=next_element,
                    nodes=(i, j),
                    area=area,
                    material_id=spec.material_id,
                    unit_weight=spec.unit_weight,
                )
            )
            ids.append(next_element)
            next_element += 1

    return Truss(
        nodes=nodes,
        elements=elements,
        spec=spec,
        chord_element_ids=chord_ids,
        web_element_ids=web_ids,
    )
