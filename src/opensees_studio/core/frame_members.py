"""Geometry of a frame member with end offsets and an insertion point, and its loads.

A member runs between two joints. Rigid end zones (``FrameEndOffsets``) and an
insertion point (``FrameInsertion``) move the ends of its *flexible* part away
from the joints; OpenSees models that with rigid joint offsets
(``geomTransf ... -jntOffset``). :func:`member_layout` computes those offsets,
and everything else that has to agree with them reads the same layout: the
runner, the diagrams (drawn along the flexible length, where the end forces
are reported) and the load split below.

Loads are given along the full joint-to-joint length, as in SAP2000.
:func:`split_member_loads` turns them into what OpenSees can take:

* the part on the flexible length, re-measured as fractions of that length;
* the part on a rigid end zone, which the rigid zone carries straight to its
  joint, as a joint force plus the moment of that force about the joint.

Pure NumPy, no OpenSees: the runner and the canvas both call it.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from opensees_studio.core.geometry.elements import BeamWithHingesElement, FrameMember
from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.sections import (
    AngleShape,
    CircularPatch,
    ElasticSection,
    FiberSection,
    PipeShape,
    RectangularPatch,
    RectShape,
    SectionAggregator,
    StraightLayer,
    TubeShape,
)

if TYPE_CHECKING:
    from opensees_studio.core.project import Project

#: Shortest flexible length a member may keep, as a fraction of its joint-to-joint length.
MIN_CLEAR_FRACTION = 1e-3

#: Cardinal point → (row along local 2, column along local 3), each -1, 0 or +1:
#: bottom/middle/top and left/center/right of the section's bounding box.
_CARDINAL_GRID: dict[int, tuple[int, int]] = {
    1: (-1, -1),
    2: (-1, 0),
    3: (-1, 1),
    4: (0, -1),
    5: (0, 0),
    6: (0, 1),
    7: (1, -1),
    8: (1, 0),
    9: (1, 1),
}


# ──────────────────────────── section extents ────────────────────────────
@dataclass(frozen=True)
class SectionExtents:
    """Bounding box of a cross section in its own (local 2 = y, local 3 = z) axes."""

    y_min: float
    y_max: float
    z_min: float
    z_max: float


def _symmetric(depth_y: float, width_z: float) -> SectionExtents:
    return SectionExtents(-depth_y / 2.0, depth_y / 2.0, -width_z / 2.0, width_z / 2.0)


def _elastic_extents(area: float, iz: float, iy: float | None) -> SectionExtents:
    """A rectangle with the same A, Iz (and Iy): ``Iz = b d^3 / 12`` puts the depth along y."""
    depth_y = math.sqrt(12.0 * iz / area)
    width_z = math.sqrt(12.0 * iy / area) if iy else area / depth_y
    return _symmetric(depth_y, width_z)


def section_extents(project: Project, section_id: int) -> SectionExtents | None:
    """Bounding box of section ``section_id`` about its reference axis, None if unknown.

    An :class:`ElasticSection` uses its shape hint when it has one (a pipe, the
    legs of an angle, the depth and width of the other profiles) and otherwise the rectangle with the same
    ``A``, ``Iz`` and ``Iy``; a fibre section the extent of its patches, layers
    and fibres; an aggregator the extent of the section it wraps.
    """
    section = next((s for s in project.sections if s.id == section_id), None)
    if isinstance(section, SectionAggregator):
        if section.section_id is None:
            return None
        return section_extents(project, section.section_id)
    if isinstance(section, ElasticSection):
        shape = section.shape
        if isinstance(shape, PipeShape):
            return _symmetric(shape.od, shape.od)
        if shape is not None:
            # The hint stands with its depth along local z (a 3D beam); a 2D frame bends in
            # the x-y plane, so there the depth lies along local y.
            width = shape.b if isinstance(shape, (RectShape, AngleShape, TubeShape)) else shape.bf
            return _symmetric(shape.d, width) if project.ndm == 2 else _symmetric(width, shape.d)
        return _elastic_extents(section.A, section.Iz, section.Iy)
    if isinstance(section, FiberSection):
        ys: list[float] = []
        zs: list[float] = []
        for patch in section.patches:
            if isinstance(patch, RectangularPatch):
                ys += [patch.y_i, patch.y_j]
                zs += [patch.z_i, patch.z_j]
            elif isinstance(patch, CircularPatch):
                ys += [patch.y_center - patch.r_outer, patch.y_center + patch.r_outer]
                zs += [patch.z_center - patch.r_outer, patch.z_center + patch.r_outer]
        for layer in section.layers:
            if isinstance(layer, StraightLayer):
                ys += [layer.y_start, layer.y_end]
                zs += [layer.z_start, layer.z_end]
        for fibre in section.fibres:
            ys.append(fibre.y)
            zs.append(fibre.z)
        if not ys:
            return None
        return SectionExtents(min(ys), max(ys), min(zs), max(zs))
    return None


def member_extents(project: Project, element: Any) -> SectionExtents | None:
    """Bounding box of the cross section a frame member is drawn and inserted with."""
    if isinstance(element, BeamWithHingesElement):
        return _elastic_extents(element.A, element.Iz, element.Iy)
    section_id = getattr(element, "section_id", None)
    return None if section_id is None else section_extents(project, section_id)


def cardinal_offset(cardinal_point: int, extents: SectionExtents | None) -> tuple[float, float]:
    """``(d2, d3)``: how far the reference axis moves so ``cardinal_point`` sits on the joints.

    Cardinal point 10 (centroid) and 11 (shear center, taken at the centroid)
    keep the section's reference axis on the joint line.
    """
    grid = _CARDINAL_GRID.get(cardinal_point)
    if grid is None:
        return (0.0, 0.0)
    if extents is None:
        raise ValueError(
            f"Cardinal point {cardinal_point} needs the section's size, and this section's "
            "size is not known (give the elastic section a shape or use a fibre section)."
        )
    row, col = grid
    y = (extents.y_min, (extents.y_min + extents.y_max) / 2.0, extents.y_max)[row + 1]
    z = (extents.z_min, (extents.z_min + extents.z_max) / 2.0, extents.z_max)[col + 1]
    return (-y, -z)


# ──────────────────────────── offsets from connectivity ────────────────────────────
#: Two members whose axes make an angle below this (|cos| above the limit) are parallel
#: for the connectivity rule: neither one's section reaches into the other along its axis.
_PARALLEL_COS = 0.99


def connectivity_offsets(project: Project, element_id: int) -> tuple[float, float]:
    """``(length_i, length_j)``: end offsets of a member from the members framing into its joints.

    SAP2000 "automatic from connectivity": at each end the offset is the
    largest half-extent, measured along this member's axis, of the section of
    any other frame member that meets it at that joint. A column of width ``b``
    along a beam gives ``b / 2``. Members parallel to this one, and members
    whose section size is unknown, add nothing.

    Raises ``ValueError`` for an element that is not a frame member.
    """
    elements = {el.id: el for el in project.elements}
    element = elements.get(element_id)
    if not isinstance(element, FrameMember):
        raise ValueError(f"Element {element_id} is not a frame member.")
    coords = {node.id: np.asarray(node.coords, dtype=float) for node in project.nodes}

    def axes_of(el: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        p_i, p_j = coords[el.nodes[0]].copy(), coords[el.nodes[1]].copy()
        if project.ndm == 2:
            p_i[1] = p_j[1] = 0.0  # 2D: the X-Z plane
        return frame_local_axes(project.ndm, p_i.tolist(), p_j.tolist())

    own = axes_of(element)
    if own is None:
        return (0.0, 0.0)
    x = own[0]
    result: list[float] = []
    for node_id in element.nodes[:2]:
        reach = 0.0
        for other in project.elements:
            if other.id == element.id or not isinstance(other, FrameMember):
                continue
            if node_id not in other.nodes[:2]:
                continue
            axes = axes_of(other)
            extents = member_extents(project, other)
            if axes is None or extents is None or abs(float(x @ axes[0])) > _PARALLEL_COS:
                continue
            _, oy, oz = axes
            half_y = (extents.y_max - extents.y_min) / 2.0
            half_z = (extents.z_max - extents.z_min) / 2.0
            along = abs(float(x @ oy)) * half_y
            if project.ndm == 3:
                along += abs(float(x @ oz)) * half_z
            reach = max(reach, along)
        result.append(reach)
    return (result[0], result[1])


# ──────────────────────────── layout ────────────────────────────
@dataclass(frozen=True)
class MemberLayout:
    """Where a member's flexible part lies relative to its two joints (global coordinates)."""

    ndm: int
    joint_i: np.ndarray
    joint_j: np.ndarray
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    length: float
    rigid_i: float = 0.0
    rigid_j: float = 0.0
    transverse: np.ndarray = field(default_factory=lambda: np.zeros(3))

    @property
    def clear_length(self) -> float:
        """Length of the flexible part, between the two rigid zones."""
        return self.length - self.rigid_i - self.rigid_j

    @property
    def offset_i(self) -> np.ndarray:
        """Rigid joint offset at end i: joint i to the start of the flexible part."""
        return self.transverse + self.rigid_i * self.x

    @property
    def offset_j(self) -> np.ndarray:
        """Rigid joint offset at end j: joint j to the end of the flexible part."""
        return self.transverse - self.rigid_j * self.x

    @property
    def face_i(self) -> np.ndarray:
        """Start of the flexible part, where the end-i forces are reported."""
        return np.asarray(self.joint_i + self.offset_i, dtype=float)

    @property
    def face_j(self) -> np.ndarray:
        """End of the flexible part, where the end-j forces are reported."""
        return np.asarray(self.joint_j + self.offset_j, dtype=float)

    def has_offset(self, end: str) -> bool:
        """The flexible part does not start (``"i"``) or end (``"j"``) at the joint."""
        offset = self.offset_i if end == "i" else self.offset_j
        return bool(np.any(np.abs(offset) > 1e-12 * max(self.length, 1.0)))

    @property
    def has_rigid_zones(self) -> bool:
        return self.rigid_i > 0.0 or self.rigid_j > 0.0

    @property
    def rotation(self) -> np.ndarray:
        """3 x 3 matrix whose columns are the local axes: local → global."""
        return np.column_stack([self.x, self.y, self.z])

    def point_at(self, distance: float) -> np.ndarray:
        """Point on the member line ``distance`` from joint i, measured along the member."""
        return np.asarray(self.joint_i + self.transverse + distance * self.x, dtype=float)


def member_layout(project: Project, element: Any) -> MemberLayout | None:
    """The layout of frame member ``element``; None for a zero-length member.

    Raises ``ValueError`` when the rigid zones leave no flexible length, or a
    cardinal point needs a section size that is not known.
    """
    coords = {node.id: node.coords for node in project.nodes}
    p_i = np.asarray(coords[element.nodes[0]], dtype=float)
    p_j = np.asarray(coords[element.nodes[1]], dtype=float)
    if project.ndm == 2:
        p_i[1] = p_j[1] = 0.0  # 2D: the X-Z plane
    axes = frame_local_axes(project.ndm, p_i.tolist(), p_j.tolist())
    if axes is None:
        return None
    x, y, z = axes
    length = float(np.linalg.norm(p_j - p_i))
    rigid_i = rigid_j = 0.0
    transverse = np.zeros(3)
    if isinstance(element, FrameMember):
        offsets = element.end_offsets
        rigid_i, rigid_j = offsets.rigid_i, offsets.rigid_j
        if length - rigid_i - rigid_j < MIN_CLEAR_FRACTION * length:
            raise ValueError(
                f"Element {element.id}: the rigid end zones ({rigid_i:g} + {rigid_j:g}) leave "
                f"no flexible length on a member {length:g} long."
            )
        insertion = element.insertion
        if not insertion.is_default():
            extents = member_extents(project, element) if insertion.cardinal_point <= 9 else None
            d2, d3 = cardinal_offset(insertion.cardinal_point, extents)
            d2 += insertion.offset_2
            d3 += insertion.offset_3
            transverse = d2 * y + (d3 * z if project.ndm == 3 else 0.0)
    return MemberLayout(
        ndm=project.ndm,
        joint_i=p_i,
        joint_j=p_j,
        x=x,
        y=y,
        z=z,
        length=length,
        rigid_i=rigid_i,
        rigid_j=rigid_j,
        transverse=transverse,
    )


# ──────────────────────────── loads ────────────────────────────
@dataclass(frozen=True)
class ClearPiece:
    """A linearly varying load on the flexible part: ``a`` < ``b`` are fractions of it.

    ``w_a`` / ``w_b`` are the local ``(wx, wy, wz)`` per unit length at ``a`` and ``b``.
    """

    a: float
    b: float
    w_a: np.ndarray
    w_b: np.ndarray

    @property
    def is_uniform_full(self) -> bool:
        return self.a <= 0.0 and self.b >= 1.0 and bool(np.allclose(self.w_a, self.w_b))


@dataclass(frozen=True)
class ClearPoint:
    """A concentrated local ``(px, py, pz)`` at fraction ``x`` of the flexible part."""

    x: float
    p: np.ndarray


@dataclass
class SplitLoads:
    """A member's loads, as OpenSees takes them (see :func:`split_member_loads`)."""

    pieces: list[ClearPiece] = field(default_factory=list)
    points: list[ClearPoint] = field(default_factory=list)
    #: ``end → (force, moment)`` in global axes, applied at joint i or j.
    joint: dict[str, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)

    def add_joint(self, end: str, force: np.ndarray, moment: np.ndarray) -> None:
        f, m = self.joint.get(end, (np.zeros(3), np.zeros(3)))
        self.joint[end] = (f + force, m + moment)


#: 3-point Gauss-Legendre rule on [-1, 1]: exact to degree 5.
GAUSS3 = (
    (-math.sqrt(3.0 / 5.0), 5.0 / 9.0),
    (0.0, 8.0 / 9.0),
    (math.sqrt(3.0 / 5.0), 5.0 / 9.0),
)


def _interp(w_a: np.ndarray, w_b: np.ndarray, d_a: float, d_b: float, d: float) -> np.ndarray:
    t = 0.0 if d_b == d_a else (d - d_a) / (d_b - d_a)
    return np.asarray(w_a + t * (w_b - w_a), dtype=float)


def _joint_load(
    layout: MemberLayout, split: SplitLoads, distance: float, force_local: np.ndarray
) -> None:
    """A local force at ``distance`` on a rigid zone, carried to its joint."""
    end = "i" if distance <= layout.rigid_i else "j"
    joint = layout.joint_i if end == "i" else layout.joint_j
    force = layout.rotation @ force_local
    arm = layout.point_at(distance) - joint
    split.add_joint(end, force, np.cross(arm, force))


def split_member_loads(
    layout: MemberLayout,
    segments: Iterable[tuple[float, float, Sequence[float], Sequence[float]]] = (),
    points: Iterable[tuple[float, Sequence[float]]] = (),
) -> SplitLoads:
    """Split a member's loads between its flexible part and its two joints.

    ``segments`` are ``(s0, s1, w0, w1)``: a load varying linearly from local
    ``w0 = (wx, wy, wz)`` at ``s0`` to ``w1`` at ``s1``, both fractions of the
    joint-to-joint length. ``points`` are ``(s, (px, py, pz))``. A piece on a
    rigid zone becomes a joint force and moment (exact: the moment of a linear
    load is integrated with 3 Gauss points); the rest is re-measured along the
    flexible length.
    """
    out = SplitLoads()
    L = layout.length
    clear_start, clear_end = layout.rigid_i, L - layout.rigid_j
    clear = layout.clear_length
    for s0, s1, w0, w1 in segments:
        d0, d1 = s0 * L, s1 * L
        w0a, w1a = np.asarray(w0, dtype=float), np.asarray(w1, dtype=float)
        for lo, hi in ((d0, min(d1, clear_start)), (max(d0, clear_end), d1)):
            if hi - lo <= 1e-12 * L:
                continue
            for xi, weight in GAUSS3:
                d = lo + (hi - lo) * (1.0 + xi) / 2.0
                w = _interp(w0a, w1a, d0, d1, d)
                _joint_load(layout, out, d, w * weight * (hi - lo) / 2.0)
        lo, hi = max(d0, clear_start), min(d1, clear_end)
        if hi - lo > 1e-12 * L:
            out.pieces.append(
                ClearPiece(
                    a=(lo - clear_start) / clear,
                    b=(hi - clear_start) / clear,
                    w_a=_interp(w0a, w1a, d0, d1, lo),
                    w_b=_interp(w0a, w1a, d0, d1, hi),
                )
            )
    for s, p in points:
        d = s * L
        p_arr = np.asarray(p, dtype=float)
        if d < clear_start or d > clear_end:
            _joint_load(layout, out, d, p_arr)
        else:
            out.points.append(ClearPoint(x=(d - clear_start) / clear, p=p_arr))
    return out


def gauss_point_loads(piece: ClearPiece, clear_length: float) -> list[ClearPoint]:
    """Three point loads with the same fixed-end forces as ``piece`` on an elastic member.

    The fixed-end forces of a load are its integral against cubic influence
    functions, so a linear load needs a rule exact to degree 4: the 3-point
    Gauss rule is exact to 5. Point loads carry the same total, the same
    first moment and the same end forces; only the shape of the internal
    diagrams between the three points differs.
    """
    span = piece.b - piece.a
    out: list[ClearPoint] = []
    for xi, weight in GAUSS3:
        x = piece.a + span * (1.0 + xi) / 2.0
        w = _interp(piece.w_a, piece.w_b, piece.a, piece.b, x)
        out.append(ClearPoint(x=x, p=w * weight * span * clear_length / 2.0))
    return out
