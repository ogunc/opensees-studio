"""Rigid diaphragms: which nodes they tie, which DOFs the runner fixes, where the mass sits.

A :class:`~core.constraints.RigidDiaphragm` ties its constrained nodes to the
retained node in the in-plane DOFs (two translations and the rotation about
the perpendicular axis). Everything here is the model-side reading of that
constraint, shared by the runner, the exported script, the canvas and the
storey table:

* :func:`constrained_node_ids` resolves "every joint of storey N" (minus the
  retained node and minus joints restrained in the plane: a support cannot
  also follow the floor).
* :func:`auto_fixed_slots`: a retained node that no element touches has no
  stiffness out of the plane; the runner fixes those three DOFs, OpenSees'
  own recipe for a centre-of-mass master node.
* :func:`centre_of_mass` places a new retained node.
* :func:`diaphragm_problems` lists what OpenSees would refuse or silently
  ignore (a node out of the plane is dropped with a warning only).
* :func:`constraint_chain_problems` does the same for the equalDOFs and rigid
  links among themselves: the Transformation handler cannot chain them.

No Qt, no OpenSees.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING

import numpy as np

from opensees_studio.core.constraints import EqualDOFConstraint, RigidDiaphragm, RigidLink
from opensees_studio.core.storeys import elevation_tolerance, storey_node_ids

if TYPE_CHECKING:
    from opensees_studio.core.project import Project

IN_PLANE_SLOTS: dict[int, tuple[int, int, int]] = {3: (0, 1, 5), 1: (1, 2, 3), 2: (0, 2, 4)}
"""Canonical 6-DOF slots a diaphragm ties, per perpendicular axis: two
translations in the plane, then the rotation about the perpendicular axis."""

OUT_OF_PLANE_SLOTS: dict[int, tuple[int, int, int]] = {3: (2, 3, 4), 1: (0, 4, 5), 2: (1, 3, 5)}
"""Canonical 6-DOF slots a diaphragm leaves free, per perpendicular axis."""


def diaphragms_supported(project: Project) -> bool:
    """OpenSees' ``rigidDiaphragm`` needs a 3D model with 6 DOF per node."""
    return project.ndm == 3 and project.ndf == 6


def constrained_node_ids(project: Project, diaphragm: RigidDiaphragm) -> tuple[int, ...]:
    """The nodes ``diaphragm`` ties to its retained node, sorted.

    A storey diaphragm takes every joint on the storey's floor except the
    retained node and the joints restrained in one of the in-plane DOFs.
    """
    if diaphragm.storey_id is None:
        return tuple(sorted(diaphragm.constrained_nodes))
    storey = next((s for s in project.storeys if s.id == diaphragm.storey_id), None)
    if storey is None:
        return ()
    by_id = {n.id: n for n in project.nodes}
    slots = IN_PLANE_SLOTS[diaphragm.perp_dirn]
    return tuple(
        nid
        for nid in storey_node_ids(project, storey)
        if nid != diaphragm.retained_node and not any(by_id[nid].restraint[s] for s in slots)
    )


def _element_node_ids(project: Project) -> set[int]:
    return {nid for element in project.elements for nid in element.nodes}


def is_floating(project: Project, node_id: int) -> bool:
    """True when no element connects to ``node_id`` (a centre-of-mass node)."""
    return node_id not in _element_node_ids(project)


def auto_fixed_slots(project: Project) -> dict[int, set[int]]:
    """Node id -> canonical slots the runner fixes on a floating retained node.

    Only nodes no element touches get them: a retained node that is a real
    joint has its out-of-plane stiffness from the members framing into it.
    """
    used = _element_node_ids(project)
    fixed: dict[int, set[int]] = {}
    for diaphragm in project.diaphragms:
        if diaphragm.retained_node in used:
            continue
        fixed.setdefault(diaphragm.retained_node, set()).update(
            OUT_OF_PLANE_SLOTS[diaphragm.perp_dirn]
        )
    return fixed


def retained_in_plane_slots(project: Project) -> dict[int, set[int]]:
    """Node id -> canonical slots a retained node gets stiffness in through its diaphragm."""
    slots: dict[int, set[int]] = {}
    for diaphragm in project.diaphragms:
        slots.setdefault(diaphragm.retained_node, set()).update(IN_PLANE_SLOTS[diaphragm.perp_dirn])
    return slots


def centre_of_mass(
    coords: Mapping[int, Sequence[float]],
    masses: Mapping[int, float],
    node_ids: Iterable[int],
) -> tuple[float, float, float]:
    """Mass-weighted centre of ``node_ids``; their centroid when they carry no mass."""
    ids = list(node_ids)
    if not ids:
        raise ValueError("No nodes to take a centre of mass of.")
    points = np.array([coords[nid] for nid in ids], dtype=float)
    weights = np.array([max(float(masses.get(nid, 0.0)), 0.0) for nid in ids])
    if weights.sum() <= 0.0:
        weights = np.ones(len(ids))
    centre = (weights[:, None] * points).sum(axis=0) / weights.sum()
    return (float(centre[0]), float(centre[1]), float(centre[2]))


def diaphragm_problems(project: Project) -> list[str]:
    """Why OpenSees would refuse or quietly mangle the project's diaphragms (empty when fine)."""
    if not project.diaphragms:
        return []
    problems: list[str] = []
    if not diaphragms_supported(project):
        problems.append(
            f"Rigid diaphragms need a 3D model with 6 DOF per node "
            f"(this one is ndm={project.ndm}, ndf={project.ndf})."
        )
        return problems
    by_id = {n.id: n for n in project.nodes}
    storey_ids = {s.id for s in project.storeys}
    tol = elevation_tolerance(project)
    owner: dict[int, int] = {}
    others = {mp.constrained_node for mp in project.mp_constraints} | {
        link.constrained_node for link in project.rigid_links
    }
    # OpenSees' Transformation handler cannot chain constraints: a node a
    # diaphragm constrains must not retain another constraint. (A frame end
    # released at such a joint does not use one: services.frame_members
    # releases it inside the element or holds it with springs.)
    retaining: dict[int, str] = {}
    for mp in project.mp_constraints:
        retaining.setdefault(mp.retained_node, "the retained node of an equalDOF")
    for link in project.rigid_links:
        retaining.setdefault(link.retained_node, "the retained node of a rigid link")
    for diaphragm in project.diaphragms:
        label = f"Diaphragm {diaphragm.id}" + (f" '{diaphragm.name}'" if diaphragm.name else "")
        retained = by_id.get(diaphragm.retained_node)
        if retained is None:
            problems.append(f"{label} refers to missing retained node {diaphragm.retained_node}.")
            continue
        if diaphragm.storey_id is not None and diaphragm.storey_id not in storey_ids:
            problems.append(f"{label} refers to missing storey {diaphragm.storey_id}.")
            continue
        constrained = constrained_node_ids(project, diaphragm)
        if not constrained:
            problems.append(f"{label} constrains no node.")
        axis = diaphragm.perp_dirn - 1
        slots = IN_PLANE_SLOTS[diaphragm.perp_dirn]
        for nid in constrained:
            node = by_id.get(nid)
            if node is None:
                problems.append(f"{label} refers to missing constrained node {nid}.")
                continue
            if abs(node.coords[axis] - retained.coords[axis]) > tol:
                problems.append(
                    f"{label}: node {nid} is not in the plane of retained node "
                    f"{retained.id} (OpenSees would drop it)."
                )
            if any(node.restraint[s] for s in slots):
                problems.append(f"{label}: node {nid} is restrained in the plane of the diaphragm.")
            if nid in owner and owner[nid] != diaphragm.id:
                problems.append(
                    f"Node {nid} is constrained by diaphragms {owner[nid]} and {diaphragm.id}."
                )
            owner[nid] = diaphragm.id
            if nid in others:
                problems.append(
                    f"{label}: node {nid} is already constrained by an equalDOF or rigid link."
                )
            if nid in retaining:
                problems.append(
                    f"{label}: node {nid} is {retaining[nid]}; OpenSees cannot chain that "
                    "constraint through a diaphragm (it would solve without an error and give "
                    "wrong results). Take the joint out of the diaphragm or remove that constraint."
                )
        if diaphragm.retained_node in others:
            problems.append(
                f"{label}: its retained node {diaphragm.retained_node} is constrained by an "
                "equalDOF or rigid link."
            )
    return problems


def _describe_mp(mp: EqualDOFConstraint) -> str:
    dofs = ", ".join(str(d) for d in mp.dofs)
    return f"equalDOF {mp.retained_node}->{mp.constrained_node} (DOF {dofs})"


def _describe_link(link: RigidLink) -> str:
    return f"rigid link ({link.kind}) {link.retained_node}->{link.constrained_node}"


def constraint_chain_problems(project: Project) -> list[str]:
    """Why OpenSees would quietly mangle the project's equalDOFs and rigid links (empty when fine).

    OpenSees 3.8's Transformation handler (the one every eigen analysis uses)
    keeps one constraint per constrained node and indexes a constrained
    retained node by its reduced DOF numbering. It reports no error and gives
    wrong results for:

    * a node constrained twice (the second constraint is dropped);
    * a chain, where the retained node of one constraint is the constrained
      node of another. The one chain it solves right is the one through a
      node an ``equalDOF`` of every DOF constrains: that node keeps no DOF of
      its own, so its reduced numbering is its retained node's;
    * a loop (displacements come out zero), or an ``equalDOF`` of a node to
      itself.

    Chains through a rigid diaphragm are :func:`diaphragm_problems`' job.
    """
    every_dof = set(range(1, project.ndf + 1))
    constrained_by: dict[int, list[tuple[int, str, bool]]] = {}
    problems: list[str] = []
    for mp in project.mp_constraints:
        if mp.retained_node == mp.constrained_node:
            problems.append(
                f"{_describe_mp(mp)} ties node {mp.retained_node} to itself; remove it."
            )
            continue
        constrained_by.setdefault(mp.constrained_node, []).append(
            (mp.retained_node, _describe_mp(mp), set(mp.dofs) == every_dof)
        )
    for link in project.rigid_links:
        constrained_by.setdefault(link.constrained_node, []).append(
            (link.retained_node, _describe_link(link), False)
        )
    retaining: dict[int, list[str]] = {}
    for mp in project.mp_constraints:
        if mp.retained_node != mp.constrained_node:
            retaining.setdefault(mp.retained_node, []).append(_describe_mp(mp))
    for link in project.rigid_links:
        retaining.setdefault(link.retained_node, []).append(_describe_link(link))

    for nid, owners in sorted(constrained_by.items()):
        if len(owners) > 1:
            problems.append(
                f"Node {nid} is the constrained node of {len(owners)} constraints "
                f"({'; '.join(text for _, text, _ in owners)}). OpenSees keeps only one "
                "constraint per constrained node and would ignore the others without an error. "
                "Merge them into one equalDOF with all their DOFs, or tie the node to a single "
                "retained node."
            )
            continue
        retained, text, full = owners[0]
        if full or nid not in retaining:
            continue
        problems.append(
            f"Node {nid} is the constrained node of {text} and the retained node of "
            f"{'; '.join(retaining[nid])}. OpenSees cannot chain these constraints (it would "
            f"solve without an error and give wrong results). Tie those nodes to node "
            f"{retained} directly (two rigid links in a row are one rigid link), or make the "
            f"constraint on node {nid} an equalDOF of every DOF (1-{project.ndf})."
        )

    # A loop through a partial constraint is a chain reported above. What is
    # left is a loop of full-DOF equalDOFs, each node with one retained node:
    # a cycle of that map.
    parent = {
        nid: owners[0][0]
        for nid, owners in constrained_by.items()
        if len(owners) == 1 and owners[0][2]
    }
    reported: set[int] = set()
    for start in sorted(parent):
        path: list[int] = []
        node = start
        while node in parent and node not in path and node not in reported:
            path.append(node)
            node = parent[node]
        reported.update(path)
        if node in path:
            # Retained -> constrained, from the lowest node id round to itself.
            loop = path[path.index(node) :][::-1]
            first = loop.index(min(loop))
            loop = loop[first:] + loop[:first]
            chain = "->".join(str(n) for n in [*loop, loop[0]])
            problems.append(
                f"The constraints between nodes {chain} form a loop; OpenSees would solve it "
                "without an error into zero displacements. Remove one of them."
            )
    return problems
