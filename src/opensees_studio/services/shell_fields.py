"""Which scalar a shell contour shows, and the numbers behind it.

Two sources, one shape of answer:

- **Deformations** — the nodal displacements the runner already records, per
  node: ``ux``, ``uy``, ``uz`` or the magnitude ``umag``.
- **Resultants** — the section resultants of ``StaticResults.element_stresses``
  (:mod:`opensees_studio.core.shell_results`), per element: the eight components,
  the principal membrane and bending values, and the transverse shear magnitude.

A contour needs a value per *node* to colour a face mesh smoothly, so
:func:`nodal_values` averages each element's value onto its own corners; the
elements with no recorded resultants simply do not contribute, which keeps a
model that mixes shells and bars honest — the bars are not painted with zeros.
Unit labels are built from the project's own system, so a kip-in model reads
``kip/in`` and ``kip·in/in``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from opensees_studio.core.shell_results import (
    FIELD_NAMES as RESULTANT_FIELD_NAMES,
)
from opensees_studio.core.shell_results import (
    field_label as resultant_field_label,
)
from opensees_studio.core.shell_results import (
    field_value,
)
from opensees_studio.core.units import UnitLabels, labels_for

#: Displacement fields, in the order the picker shows them.
DISPLACEMENT_KEYS: tuple[str, ...] = ("umag", "ux", "uy", "uz")


@dataclass(frozen=True)
class ShellField:
    """One thing a shell contour can show."""

    key: str
    label: str
    group: str
    """Picker group: ``Deformation``, ``Membrane``, ``Bending``, ``Shear``."""
    kind: str
    """``displacement`` (per node) or ``resultant`` (per element)."""
    unit: str
    """``length``, ``force/length`` or ``moment/length``."""
    direction: bool = False
    """True when a principal direction can be drawn as a glyph."""

    def unit_label(self, units: Any) -> str:
        """The unit text for a colour bar, in the project's system."""
        labels: UnitLabels = labels_for(units)
        if self.unit == "length":
            return labels.length
        if self.unit == "force/length":
            return f"{labels.force}/{labels.length}"
        return f"{labels.moment}/{labels.length}"


_DISPLACEMENT_LABELS = {
    "umag": "|u| — displacement magnitude",
    "ux": "ux — displacement along X",
    "uy": "uy — displacement along Y",
    "uz": "uz — displacement along Z",
}

#: Groups a resultant field belongs to, by its first letter.
_RESULTANT_GROUPS = {"N": "Membrane", "M": "Bending", "V": "Shear"}


def _resultant_fields() -> tuple[ShellField, ...]:
    fields = []
    for key in RESULTANT_FIELD_NAMES:
        group = _RESULTANT_GROUPS[key[0]]
        fields.append(
            ShellField(
                key=key,
                label=resultant_field_label(key),
                group=group,
                kind="resultant",
                unit="moment/length" if key.startswith("M") else "force/length",
                direction=key in ("N1", "N2", "M1", "M2"),
            ),
        )
    fields.append(
        ShellField(
            key="V",
            label=resultant_field_label("V"),
            group="Shear",
            kind="resultant",
            unit="force/length",
        ),
    )
    return tuple(fields)


SHELL_FIELDS: tuple[ShellField, ...] = (
    tuple(
        ShellField(
            key=key,
            label=_DISPLACEMENT_LABELS[key],
            group="Deformation",
            kind="displacement",
            unit="length",
        )
        for key in DISPLACEMENT_KEYS
    )
    + _resultant_fields()
)

_FIELDS_BY_KEY = {field.key: field for field in SHELL_FIELDS}


def field_by_key(key: str) -> ShellField:
    """The field with that key.

    Raises:
        KeyError: if no field has it — a typo must not silently draw nothing.
    """
    return _FIELDS_BY_KEY[key]


def field_keys() -> tuple[str, ...]:
    """Every field key, in picker order."""
    return tuple(field.key for field in SHELL_FIELDS)


def shell_elements(project: Any) -> list[Any]:
    """The face elements of a model: those with three or more nodes."""
    return [element for element in project.elements if len(element.nodes) >= 3]


def _displacement_component(project: Any, results: Any, dof: int, step: int) -> dict[int, float]:
    values: dict[int, float] = {}
    for node in project.nodes:
        history = results.node_disp.get(node.id)
        if history is None or len(history) == 0:
            continue
        row = np.asarray(history)[step]
        values[node.id] = float(row[dof - 1]) if dof - 1 < len(row) else 0.0
    return values


def nodal_values(
    project: Any,
    results: Any,
    key: str,
    step: int = -1,
) -> dict[int, float]:
    """One value per node, ready to colour a face mesh.

    A displacement field is read straight from the node's history; a resultant
    field is the mean of the values of the elements that share the node, so a
    shell contour is continuous across elements and a bar contributes nothing.
    """
    field = field_by_key(key)
    if field.kind == "displacement":
        if key == "umag":
            components = {
                dof: _displacement_component(project, results, dof, step) for dof in (1, 2, 3)
            }
            return {
                nid: float(np.linalg.norm([components[dof].get(nid, 0.0) for dof in (1, 2, 3)]))
                for nid in components[1]
            }
        dof = {"ux": 1, "uy": 2, "uz": 3}[key]
        return _displacement_component(project, results, dof, step)

    per_element = element_values(project, results, key, step)
    totals: dict[int, float] = {}
    counts: dict[int, int] = {}
    for element in shell_elements(project):
        if element.id not in per_element:
            continue
        value = per_element[element.id]
        for node_id in element.nodes:
            totals[node_id] = totals.get(node_id, 0.0) + value
            counts[node_id] = counts.get(node_id, 0) + 1
    return {nid: totals[nid] / counts[nid] for nid in totals}


def element_values(
    project: Any,
    results: Any,
    key: str,
    step: int = -1,
) -> dict[int, float]:
    """One value per element.

    For a resultant field this is the element's own number; for a displacement
    field it is the mean of its corners, so both kinds can colour a face mesh
    the same way.
    """
    field = field_by_key(key)
    if field.kind == "resultant":
        stresses = getattr(results, "element_stresses", {}) or {}
        values: dict[int, float] = {}
        for element_id, history in stresses.items():
            rows = np.asarray(history)
            if rows.size == 0:
                continue
            values[int(element_id)] = float(field_value(rows[step], key))
        return values

    nodal = nodal_values(project, results, key, step)
    out: dict[int, float] = {}
    for element in shell_elements(project):
        corners = [nodal[nid] for nid in element.nodes if nid in nodal]
        if corners:
            out[element.id] = float(sum(corners) / len(corners))
    return out


def displacement_scale(project: Any, results: Any, step: int = -1, fraction: float = 0.05) -> float:
    """A multiplier that makes the largest displacement ``fraction`` of the model.

    Same convention as the deformed-shape view (5 % of the bounding-box
    diagonal), so a contour and the deformed shape zoom alike.
    """
    coords = np.array([node.coords for node in project.nodes], dtype=float)
    if len(coords) < 2:
        return 1.0
    bbox = float(np.linalg.norm(coords.max(axis=0) - coords.min(axis=0)))
    peak = max((abs(v) for v in nodal_values(project, results, "umag", step).values()), default=0.0)
    if bbox <= 0.0 or peak <= 0.0:
        return 1.0
    return (bbox * fraction) / peak


def warped_positions(
    project: Any,
    results: Any,
    scale: float,
    step: int = -1,
) -> dict[int, tuple[float, float, float]]:
    """Node coordinates with ``scale × displacement`` added, for the deformed view."""
    if scale == 0.0:
        return {
            node.id: (float(node.coords[0]), float(node.coords[1]), float(node.coords[2]))
            for node in project.nodes
        }
    components = {dof: _displacement_component(project, results, dof, step) for dof in (1, 2, 3)}
    positions: dict[int, tuple[float, float, float]] = {}
    for node in project.nodes:
        coords = tuple(float(c) for c in node.coords)
        positions[node.id] = (
            coords[0] + scale * components[1].get(node.id, 0.0),
            coords[1] + scale * components[2].get(node.id, 0.0),
            coords[2] + scale * components[3].get(node.id, 0.0),
        )
    return positions
