"""Edit → Extrude: joints into frames, frames into shells.

Extruding repeats an object along an offset ``(dx, dy, dz)`` ``count`` times
and fills the gap with the next dimension: a joint sweeps a line of frames
(a column stack), a frame sweeps a strip of shells (a wall or a slab). A
point of the sweep that falls on an existing joint reuses it, so an
extrusion connects to the model it reaches instead of doubling its joints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opensees_studio.commands.base import ProjectCommand
from opensees_studio.core import (
    ElasticBeamColumn,
    FiberSection,
    ForceBeamColumn,
    Node,
    SectionAggregator,
    ShellMITC4Element,
)

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel

#: Two points closer than this are the same joint.
COINCIDENT_TOL = 1e-6


def section_choices(project: Any, *, shells: bool) -> list[tuple[int, str]]:
    """``(id, name)`` of the plate sections (``shells``) or the frame sections of a project."""
    from opensees_studio.core.sections import SHELL_SECTION_CLASSES

    return [
        (s.id, s.name or f"Section {s.id}")
        for s in getattr(project, "sections", [])
        if isinstance(s, SHELL_SECTION_CLASSES) == shells
    ]


def frame_element(element_id: int, nodes: tuple[int, int], section: Any) -> Any:
    """The frame a section draws: force-based for a fibre section, elastic otherwise."""
    if isinstance(section, FiberSection | SectionAggregator):
        return ForceBeamColumn(id=element_id, nodes=nodes, section_id=section.id)
    return ElasticBeamColumn(id=element_id, nodes=nodes, section_id=section.id)


class ExtrudeCommand(ProjectCommand):
    """Sweep joints into frames, or frames into shells, along an offset.

    ``node_ids`` are extruded into frames with section ``section_id`` when
    ``element_ids`` is empty; otherwise the frames ``element_ids`` are
    extruded into ``ShellMITC4`` shells with plate section ``section_id``.
    """

    def __init__(
        self,
        vm: ProjectViewModel,
        node_ids: set[int],
        element_ids: set[int],
        offset: tuple[float, float, float],
        count: int,
        section_id: int,
    ) -> None:
        if count < 1:
            raise ValueError("Extrude needs at least one step.")
        if not any(abs(c) > COINCIDENT_TOL for c in offset):
            raise ValueError("Extrude needs a non-zero offset.")
        kind = "shells" if element_ids else "frames"
        super().__init__(vm, f"Extrude into {kind} × {count}")
        self._node_ids = set(node_ids)
        self._element_ids = set(element_ids)
        self._offset = offset
        self._count = count
        self._section_id = section_id
        self.added_nodes: list[int] = []
        self.added_elements: list[int] = []

    # ── helpers ──────────────────────────────────────────────────────
    def _joint_at(self, point: tuple[float, float, float]) -> int:
        """The joint at ``point``: an existing one, or a new one."""
        for node in self.project.nodes:
            if all(abs(a - b) <= COINCIDENT_TOL for a, b in zip(node.coords, point, strict=True)):
                return node.id
        node_id = self.project.next_node_id()
        self.project.nodes.append(Node(id=node_id, coords=point))
        self.added_nodes.append(node_id)
        return node_id

    def _swept(self, node_id: int) -> list[int]:
        """``node_id`` and its ``count`` copies along the offset."""
        coords = next(n.coords for n in self.project.nodes if n.id == node_id)
        dx, dy, dz = self._offset
        return [node_id] + [
            self._joint_at((coords[0] + k * dx, coords[1] + k * dy, coords[2] + k * dz))
            for k in range(1, self._count + 1)
        ]

    # ── do / undo ────────────────────────────────────────────────────
    def redo(self) -> None:
        self.added_nodes = []
        self.added_elements = []
        section = next((s for s in self.project.sections if s.id == self._section_id), None)
        if section is None:
            raise ValueError(f"Section {self._section_id} does not exist.")
        new: list[Any] = []
        next_id = self.project.next_element_id()
        if self._element_ids:
            frames = [e for e in self.project.elements if e.id in self._element_ids]
            for frame in frames:
                if len(frame.nodes) != 2:
                    continue
                start, end = self._swept(frame.nodes[0]), self._swept(frame.nodes[1])
                for k in range(self._count):
                    nodes = (start[k], end[k], end[k + 1], start[k + 1])
                    new.append(ShellMITC4Element(id=next_id, nodes=nodes, section_id=section.id))
                    next_id += 1
        else:
            for node_id in sorted(self._node_ids):
                line = self._swept(node_id)
                for k in range(self._count):
                    new.append(frame_element(next_id, (line[k], line[k + 1]), section))
                    next_id += 1
        self.project.elements.extend(new)
        self.added_elements = [e.id for e in new]
        self._notify()

    def undo(self) -> None:
        added_elements = set(self.added_elements)
        added_nodes = set(self.added_nodes)
        self.project.elements[:] = [e for e in self.project.elements if e.id not in added_elements]
        self.project.nodes[:] = [n for n in self.project.nodes if n.id not in added_nodes]
        self._notify()
