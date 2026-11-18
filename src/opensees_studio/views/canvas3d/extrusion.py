"""Meshes of View → Show Extruded Sections: each member's section swept along it.

A section's regions (``core.section_outline``) become one template, in local
coordinates with x running 0..1: both end caps (triangulated with their holes),
the side walls of every loop, and the outline edges (each end, plus a line along
the member at every sharp corner). Members that share a section reuse it, so a
member costs one matrix product. Every member lands in one surface mesh and one
line mesh, so the overlay is two actors whatever the model size.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pyvista as pv
from vtkmodules.vtkFiltersGeneral import vtkContourTriangulator

from opensees_studio.core.sections.geometry import CircleRegion, Region, circle_points

#: Segments of a circle in the extruded view (a pipe, a round bar).
CIRCLE_SEGMENTS = 24

#: A loop vertex whose two edges turn by more than this gets a line along the member.
SHARP_TURN_DEG = 30.0


@dataclass(frozen=True)
class Template:
    """A section swept along x = 0..1 in local (x, y, z)."""

    points: np.ndarray  # (n, 3)
    faces: np.ndarray  # VTK face array (triangles and quads)
    n_faces: int
    edge_points: np.ndarray  # (m, 3)
    edges: np.ndarray  # VTK line array (two-point segments)
    n_edges: int

    face_index: np.ndarray  # 1 where ``faces`` holds a point index, 0 at a cell size
    edge_index: np.ndarray


def _index_mask(cells: np.ndarray) -> np.ndarray:
    mask = np.ones(len(cells), dtype=np.int64)
    k = 0
    while k < len(cells):
        mask[k] = 0
        k += int(cells[k]) + 1
    return mask


def _loop(region: Region) -> np.ndarray:
    if isinstance(region, CircleRegion):
        return np.asarray(circle_points(region, CIRCLE_SEGMENTS), dtype=float)
    return np.asarray(region.points, dtype=float)


def _groups(regions: Sequence[Region]) -> list[list[np.ndarray]]:
    """Each solid with the holes that follow it, as ``[outer, hole, ...]`` loops."""
    groups: list[list[np.ndarray]] = []
    for region in regions:
        if region.hole and groups:
            groups[-1].append(_loop(region))
        elif not region.hole:
            groups.append([_loop(region)])
    return groups


def _cap_triangles(loops: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """``(points (n, 2), triangles (t, 3))`` filling the outer loop minus the holes."""
    pts = np.vstack(loops)
    lines: list[int] = []
    start = 0
    for loop in loops:
        n = len(loop)
        for k in range(n):
            lines += [2, start + k, start + (k + 1) % n]
        start += n
    contour = pv.PolyData(np.column_stack([pts, np.zeros(len(pts))]), lines=np.asarray(lines))
    triangulator = vtkContourTriangulator()
    triangulator.SetInputData(contour)
    triangulator.Update()
    filled = pv.wrap(triangulator.GetOutput()).triangulate()
    if filled.n_cells == 0:
        return pts, np.zeros((0, 3), dtype=np.int64)
    tris = np.asarray(filled.faces).reshape(-1, 4)[:, 1:]
    return np.asarray(filled.points)[:, :2], tris


def _sharp(loop: np.ndarray) -> np.ndarray:
    """Indices of the loop's vertices where its outline turns sharply."""
    before = loop - np.roll(loop, 1, axis=0)
    after = np.roll(loop, -1, axis=0) - loop
    cos = np.einsum("ij,ij->i", before, after) / np.maximum(
        np.linalg.norm(before, axis=1) * np.linalg.norm(after, axis=1), 1e-300
    )
    return np.flatnonzero(cos < np.cos(np.radians(SHARP_TURN_DEG)))


def build_template(regions: Sequence[Region]) -> Template | None:
    """The swept mesh of ``regions``; None when nothing is solid."""
    points: list[np.ndarray] = []
    faces: list[np.ndarray] = []
    edge_points: list[np.ndarray] = []
    edges: list[np.ndarray] = []
    n_points = n_faces = n_edge_points = n_edges = 0

    def lift(yz: np.ndarray, x: float) -> np.ndarray:
        return np.column_stack([np.full(len(yz), x), yz])

    for loops in _groups(regions):
        cap, tris = _cap_triangles(loops)
        for x, order in ((0.0, [0, 2, 1]), (1.0, [0, 1, 2])):
            points.append(lift(cap, x))
            if len(tris):
                cells = np.column_stack([np.full(len(tris), 3), tris[:, order] + n_points])
                faces.append(cells.ravel())
                n_faces += len(tris)
            n_points += len(cap)
        for loop in loops:
            n = len(loop)
            points += [lift(loop, 0.0), lift(loop, 1.0)]
            k = np.arange(n)
            nxt = (k + 1) % n
            quads = np.column_stack(
                [np.full(n, 4), n_points + k, n_points + nxt, n_points + n + nxt, n_points + n + k]
            )
            faces.append(quads.ravel())
            n_faces += n
            n_points += 2 * n

            edge_points += [lift(loop, 0.0), lift(loop, 1.0)]
            rings = np.vstack([np.column_stack([k, nxt]), np.column_stack([k + n, nxt + n])])
            sharp = _sharp(loop)
            segments = np.vstack([rings, np.column_stack([sharp, sharp + n])]) + n_edge_points
            edges.append(np.column_stack([np.full(len(segments), 2), segments]).ravel())
            n_edges += len(segments)
            n_edge_points += 2 * n
    if not points or n_faces == 0:
        return None
    face_cells = np.concatenate(faces).astype(np.int64)
    edge_cells = np.concatenate(edges).astype(np.int64)
    return Template(
        points=np.vstack(points),
        faces=face_cells,
        n_faces=n_faces,
        edge_points=np.vstack(edge_points),
        edges=edge_cells,
        n_edges=n_edges,
        face_index=_index_mask(face_cells),
        edge_index=_index_mask(edge_cells),
    )


@dataclass
class SweptMeshes:
    """Accumulates placed templates into one surface and one line mesh."""

    _points: list[np.ndarray]
    _faces: list[np.ndarray]
    _edge_points: list[np.ndarray]
    _edges: list[np.ndarray]
    _n_points: int = 0
    _n_edge_points: int = 0

    @classmethod
    def empty(cls) -> SweptMeshes:
        return cls([], [], [], [])

    def add(
        self, template: Template, origin: np.ndarray, rotation: np.ndarray, length: float
    ) -> None:
        """Place ``template`` from ``origin`` along ``rotation``'s x for ``length``.

        ``rotation``'s columns are the member's local x, y, z in global coordinates.
        """
        scale = np.array([length, 1.0, 1.0])
        self._points.append(origin + (template.points * scale) @ rotation.T)
        self._faces.append(template.faces + template.face_index * self._n_points)
        self._n_points += len(template.points)
        self._edge_points.append(origin + (template.edge_points * scale) @ rotation.T)
        self._edges.append(template.edges + template.edge_index * self._n_edge_points)
        self._n_edge_points += len(template.edge_points)

    def meshes(self) -> tuple[pv.PolyData, pv.PolyData] | None:
        """``(surface, outline)``, None when nothing was added."""
        if not self._points:
            return None
        surface = pv.PolyData(np.vstack(self._points), faces=np.concatenate(self._faces))
        outline = pv.PolyData(np.vstack(self._edge_points), lines=np.concatenate(self._edges))
        return surface, outline
