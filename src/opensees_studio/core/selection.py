"""Selection queries that depend only on the project model.

The canvas uses these rules to turn a rubber-band rectangle into a set of
entity ids. Keeping the rule here makes it testable without Qt or VTK.
"""

from __future__ import annotations

from collections.abc import Iterable

from opensees_studio.core.project import Project


def elements_with_nodes_inside(project: Project, node_ids: Iterable[int]) -> set[int]:
    """Elements whose every joint is in ``node_ids``.

    The rule for a box selection: a member counts only when all of its joints
    are inside, so a member that merely crosses the rectangle is left out.
    """
    inside = set(node_ids)
    return {
        element.id
        for element in project.elements
        if element.nodes and all(nid in inside for nid in element.nodes)
    }
