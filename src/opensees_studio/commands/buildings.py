"""Commands for the building data: storeys, rigid diaphragms, rigid links and the mass source."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands.base import ProjectCommand
from opensees_studio.core import (
    EqualDOFConstraint,
    MassSource,
    Node,
    Project,
    RigidDiaphragm,
    RigidLink,
    Storey,
)
from opensees_studio.core.design.settings import DesignSettings

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


_Constraints = tuple[list[EqualDOFConstraint], list[RigidLink], list[RigidDiaphragm]]


class SetStoreysCommand(ProjectCommand):
    """Replace the storey list (Define → Storeys)."""

    def __init__(self, vm: ProjectViewModel, storeys: list[Storey]) -> None:
        super().__init__(vm, f"Set {len(storeys)} storey(s)")
        self._new = list(storeys)
        self._old: list[Storey] = []

    def redo(self) -> None:
        kept = {s.id for s in self._new}
        orphaned = [
            d.id
            for d in self.project.diaphragms
            if d.storey_id is not None and d.storey_id not in kept
        ]
        if orphaned:
            raise ValueError(
                "Diaphragm(s) "
                + ", ".join(str(i) for i in orphaned)
                + " use a storey that would be removed; delete them first."
            )
        self._old = list(self.project.storeys)
        self.project.storeys[:] = self._new
        self._notify()

    def undo(self) -> None:
        self.project.storeys[:] = self._old
        self._notify()


class SetMassSourceCommand(ProjectCommand):
    """Set or clear the mass source (Define → Mass Source)."""

    def __init__(self, vm: ProjectViewModel, source: MassSource | None) -> None:
        super().__init__(vm, "Set mass source" if source is not None else "Clear mass source")
        self._new = source
        self._old: MassSource | None = None

    def redo(self) -> None:
        self._old = self.project.mass_source
        self.project.mass_source = self._new
        self._notify()

    def undo(self) -> None:
        self.project.mass_source = self._old
        self._notify()


class SetDesignSettingsCommand(ProjectCommand):
    """Set the design check settings (Design → Steel Frame Check / Storey Drift Check)."""

    def __init__(self, vm: ProjectViewModel, settings: DesignSettings | None) -> None:
        super().__init__(vm, "Set design settings")
        self._new = settings
        self._old: DesignSettings | None = None

    def redo(self) -> None:
        self._old = self.project.design
        self.project.design = self._new
        self._notify()

    def undo(self) -> None:
        self.project.design = self._old
        self._notify()


class AddDiaphragmCommand(ProjectCommand):
    """Add a rigid diaphragm, and the retained node it needs when that node is new."""

    def __init__(
        self, vm: ProjectViewModel, diaphragm: RigidDiaphragm, retained: Node | None = None
    ) -> None:
        super().__init__(vm, f"Add diaphragm {diaphragm.name or diaphragm.id}")
        self._diaphragm = diaphragm
        self._retained = retained

    def redo(self) -> None:
        project = self.project
        if any(d.id == self._diaphragm.id for d in project.diaphragms):
            raise ValueError(f"Diaphragm id {self._diaphragm.id} already exists.")
        if self._retained is not None:
            if any(n.id == self._retained.id for n in project.nodes):
                raise ValueError(f"Node id {self._retained.id} already exists.")
            project.nodes.append(self._retained)
        project.diaphragms.append(self._diaphragm)
        self._notify()

    def undo(self) -> None:
        project = self.project
        project.diaphragms[:] = [d for d in project.diaphragms if d.id != self._diaphragm.id]
        if self._retained is not None:
            project.nodes[:] = [n for n in project.nodes if n.id != self._retained.id]
        self._notify()


class AddRigidLinkCommand(ProjectCommand):
    """Add a ``rigidLink`` between two nodes."""

    def __init__(self, vm: ProjectViewModel, link: RigidLink) -> None:
        super().__init__(
            vm, f"Add rigid {link.kind} link {link.retained_node}->{link.constrained_node}"
        )
        self._link = link

    def redo(self) -> None:
        pair = {self._link.retained_node, self._link.constrained_node}
        if any({k.retained_node, k.constrained_node} == pair for k in self.project.rigid_links):
            raise ValueError("These two nodes are already joined by a rigid link.")
        self.project.rigid_links.append(self._link)
        self._notify()

    def undo(self) -> None:
        self.project.rigid_links[:] = [k for k in self.project.rigid_links if k != self._link]
        self._notify()


class RemoveConstraintsCommand(ProjectCommand):
    """Remove every constraint touching the given nodes: equalDOF, rigid links, diaphragms.

    A diaphragm goes when its retained node is one of them; a listed
    constrained node just leaves its diaphragm (which goes when none is left).
    A storey diaphragm keeps following its storey.
    """

    def __init__(self, vm: ProjectViewModel, node_ids: set[int]) -> None:
        super().__init__(vm, f"Remove constraints of {len(node_ids)} node(s)")
        self._node_ids = set(node_ids)
        self._before: _Constraints = ([], [], [])

    def redo(self) -> None:
        project = self.project
        self._before = (
            list(project.mp_constraints),
            list(project.rigid_links),
            list(project.diaphragms),
        )
        project.mp_constraints[:], project.rigid_links[:], project.diaphragms[:] = (
            constraints_without_nodes(project, self._node_ids)
        )
        self._notify()

    def undo(self) -> None:
        project = self.project
        project.mp_constraints[:], project.rigid_links[:], project.diaphragms[:] = self._before
        self._notify()


def constraints_without_nodes(project: Project, node_ids: set[int]) -> _Constraints:
    """The project's equalDOF, rigid link and diaphragm lists with ``node_ids`` taken out."""
    equal = [
        mp
        for mp in project.mp_constraints
        if mp.retained_node not in node_ids and mp.constrained_node not in node_ids
    ]
    links = [
        k
        for k in project.rigid_links
        if k.retained_node not in node_ids and k.constrained_node not in node_ids
    ]
    diaphragms = []
    for d in project.diaphragms:
        if d.retained_node in node_ids:
            continue
        if d.constrained_nodes:
            remaining = tuple(n for n in d.constrained_nodes if n not in node_ids)
            if not remaining:
                continue
            if remaining != d.constrained_nodes:
                d = d.model_copy(update={"constrained_nodes": remaining})
        diaphragms.append(d)
    return equal, links, diaphragms
