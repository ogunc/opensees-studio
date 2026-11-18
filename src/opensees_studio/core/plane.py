"""Global axes and how they reach OpenSees.

Z is the elevation axis of every model. A 3D model uses X, Y and Z as they
are. A 2D model lives in the global **X-Z plane** (every node at y = 0), and
OpenSees, whose 2D models are in its own x-y plane, receives

- the coordinates ``(X, Z)`` as its ``(x, y)``,
- the DOFs ``(Ux, Uz, Ry)`` (frame) or ``(Ux, Uz)`` (truss) as its DOFs 1, 2, 3.

The in-plane rotation changes sign on the way: OpenSees' ``rz`` turns x
toward y, that is X toward Z, which is a rotation about **-Y**. So a rotation
or a moment about global Y is ``-1`` times the OpenSees value, both ways
(:func:`dof_signs`). Translations and forces keep their sign.

Nodes always store three coordinates and six DOF slots
``(Ux, Uy, Uz, Rx, Ry, Rz)``; :func:`dof_indices` says which slot each
OpenSees DOF of a model reads. Results the runner returns are in OpenSees DOF
order with the global sign already applied, so column ``j`` of a 2D frame
result is ``(Ux, Uz, Ry)[j]``.

This module is part of ``core``: no Qt, no openseespy.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

VERTICAL_AXIS = 2
"""Index of the elevation axis (Z) in a coordinate triple, in 2D and in 3D."""

Vector = Sequence[float] | np.ndarray
"""A coordinate triple or DOF vector, as a sequence or a NumPy array."""

AXIS_NAMES = ("X", "Y", "Z")
DOF_NAMES = ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")
FORCE_NAMES = ("Fx", "Fy", "Fz", "Mx", "My", "Mz")

_DOF_TABLE: dict[tuple[int, int], tuple[int, ...]] = {
    (2, 2): (0, 2),
    (2, 3): (0, 2, 4),
    (3, 3): (0, 1, 2),
    (3, 6): (0, 1, 2, 3, 4, 5),
}


def dof_indices(ndm: int, ndf: int) -> tuple[int, ...]:
    """Slot of the 6-DOF node storage that each OpenSees DOF ``1..ndf`` reads.

    - (2, 2): 2D truss, ``(Ux, Uz)`` = (0, 2)
    - (2, 3): 2D frame, ``(Ux, Uz, Ry)`` = (0, 2, 4)
    - (3, 3): 3D truss or brick, ``(Ux, Uy, Uz)`` = (0, 1, 2)
    - (3, 6): 3D frame, all six
    """
    if (ndm, ndf) not in _DOF_TABLE:
        raise ValueError(f"Unsupported (ndm, ndf): ({ndm}, {ndf}).")
    return _DOF_TABLE[(ndm, ndf)]


def dof_signs(ndm: int, ndf: int) -> tuple[float, ...]:
    """Factor from an OpenSees DOF value to the global one (and back): -1 for a 2D rotation."""
    return tuple(-1.0 if slot == 4 and ndm == 2 else 1.0 for slot in dof_indices(ndm, ndf))


def dof_labels(ndm: int, ndf: int) -> tuple[str, ...]:
    """``Ux``, ``Uz``, ``Ry`` … for OpenSees DOFs ``1..ndf`` of a model."""
    return tuple(DOF_NAMES[i] for i in dof_indices(ndm, ndf))


def force_labels(ndm: int, ndf: int) -> tuple[str, ...]:
    """``Fx``, ``Fz``, ``My`` … for OpenSees DOFs ``1..ndf`` of a model."""
    return tuple(FORCE_NAMES[i] for i in dof_indices(ndm, ndf))


def coord_axes(ndm: int) -> tuple[int, ...]:
    """Global axes OpenSees' coordinates are: (X, Z) in 2D, (X, Y, Z) in 3D."""
    return (0, VERTICAL_AXIS) if ndm == 2 else (0, 1, 2)


def lateral_axes(ndm: int) -> tuple[int, ...]:
    """Horizontal global axes of a model: X in 2D, X and Y in 3D."""
    return (0,) if ndm == 2 else (0, 1)


def to_solver_coords(coords: Vector, ndm: int) -> tuple[float, ...]:
    """Global ``(x, y, z)`` to the coordinates OpenSees takes."""
    return tuple(float(coords[i]) for i in coord_axes(ndm))


def from_solver_coords(values: Vector, ndm: int) -> tuple[float, float, float]:
    """OpenSees coordinates back to a global ``(x, y, z)``."""
    out = [0.0, 0.0, 0.0]
    for axis, value in zip(coord_axes(ndm), values, strict=False):
        out[axis] = float(value)
    return (out[0], out[1], out[2])


def to_solver_dofs(values6: Vector, ndm: int, ndf: int) -> tuple[float, ...]:
    """A global 6-component vector (load, displacement) as OpenSees DOF values."""
    return tuple(
        float(values6[i]) * s
        for i, s in zip(dof_indices(ndm, ndf), dof_signs(ndm, ndf), strict=True)
    )


def from_solver_dofs(values: Vector, ndm: int, ndf: int) -> tuple[float, ...]:
    """OpenSees DOF values as a global 6-component vector (unused slots 0)."""
    out = [0.0] * 6
    for i, s, v in zip(dof_indices(ndm, ndf), dof_signs(ndm, ndf), values, strict=False):
        out[i] = float(v) * s
    return tuple(out)


def translation_from_dofs(values: Vector, ndm: int, ndf: int) -> np.ndarray:
    """The global ``(ux, uy, uz)`` of a node from its DOF-ordered result row."""
    out = np.zeros(3)
    for slot, value in zip(dof_indices(ndm, ndf), values, strict=False):
        if slot < 3:
            out[slot] = float(value)
    return out


def solver_vector(vector: Vector, ndm: int) -> tuple[float, ...]:
    """A global direction ``(x, y, z)`` in OpenSees coordinates (2D: ``(x, z)``)."""
    return to_solver_coords(vector, ndm)


def to_solver_vector3(vector: Vector, ndm: int) -> tuple[float, float, float]:
    """A global 3-vector in OpenSees' own frame, for ``-orient``-style arguments.

    OpenSees' 2D x, y and z are the global X, Z and -Y, so ``(a, b, c)``
    becomes ``(a, c, -b)``; a 3D vector is unchanged.
    """
    a, b, c = (float(v) for v in vector[:3])
    return (a, c, -b) if ndm == 2 else (a, b, c)


def from_solver_vector3(vector: Vector, ndm: int) -> tuple[float, float, float]:
    """Inverse of :func:`to_solver_vector3`."""
    a, b, c = (float(v) for v in vector[:3])
    return (a, -c, b) if ndm == 2 else (a, b, c)


def out_of_plane(ndm: int) -> np.ndarray:
    """The axis a 2D model's in-plane rotation turns about, as OpenSees counts it: -Y.

    OpenSees' 2D local ``y`` of a member is ``out_of_plane × x``. In 3D there
    is no such axis; this returns +Z only for symmetry and is not used there.
    """
    return np.array([0.0, -1.0, 0.0]) if ndm == 2 else np.array([0.0, 0.0, 1.0])


# ─────────────────────────── file migration ───────────────────────────
XZ_SCHEMA_VERSION = 3
"""First ``.osmodel`` schema whose 2D models live in the X-Z plane."""


def _rotate(vector: Sequence[float]) -> list[float]:
    """+90 degrees about X: ``(x, y, z) -> (x, -z, y)``, so the old 2D Y becomes Z."""
    x, y, z = (float(v) for v in vector[:3])
    return [x, -z, y]


def _swap_slots(values: Sequence[Any]) -> list[Any]:
    """Restraint flags or masses of the rotated node: Y and Z swap, translations and rotations."""
    v = list(values)
    return [v[0], v[2], v[1], v[3], v[5], v[4]]


def _rotate6(values: Sequence[float]) -> list[float]:
    """A force-and-moment 6-vector under the same rotation as :func:`_rotate`."""
    return [*_rotate(values[:3]), *_rotate(values[3:6])]


def migrate_2d_payload_to_xz(payload: dict[str, Any]) -> bool:
    """Move a schema < 3 2D project from the X-Y plane (Y up) to X-Z (Z up), in place.

    The whole model turns +90 degrees about X: a point ``(x, y, 0)`` lands on
    ``(x, 0, y)``, nodal forces and moments turn with it (the old in-plane
    moment Mz becomes ``My = -Mz``, the same physical moment), restraints and
    masses follow their axes, grid lines along Y become lines along Z, and a
    bearing's ``orient`` vectors turn too. Member loads are in the members'
    local axes, which turn with the model, so they stay as they are; DOF
    numbers (equalDOF, excitation direction, pushover control DOF) are
    OpenSees' and keep their meaning. Returns True when it changed anything.
    """
    if payload.get("ndm") != 2:
        return False
    version = payload.get("schema_version", 1)
    if isinstance(version, int) and version >= XZ_SCHEMA_VERSION:
        return False
    for node in payload.get("nodes", []) or []:
        if "coords" in node:
            node["coords"] = _rotate(node["coords"])
        if "restraint" in node:
            node["restraint"] = _swap_slots(node["restraint"])
        if "mass" in node:
            node["mass"] = _swap_slots(node["mass"])
    for pattern in payload.get("load_patterns", []) or []:
        for load in pattern.get("nodal_loads", []) or []:
            if "forces" in load:
                load["forces"] = _rotate6(load["forces"])
    for element in payload.get("elements", []) or []:
        orient = element.get("orient")
        if isinstance(orient, list) and len(orient) == 6:
            element["orient"] = [*_rotate(orient[:3]), *_rotate(orient[3:])]
    for system in payload.get("coord_systems", []) or []:
        coord = system.get("coord") or {}
        if "origin" in coord:
            coord["origin"] = _rotate(coord["origin"])
        rotation = coord.get("rotation_deg")
        if rotation and any(float(r) for r in rotation):
            # In-plane (about the old Z) is the only rotation a 2D grid has;
            # about the new axis that is -Y.
            rx, ry, rz = (float(r) for r in rotation)
            coord["rotation_deg"] = [rx, -rz, ry]
        grid = system.get("grid") or {}
        for prefix in ("_grid_lines", "_lines"):
            keys = (f"x{prefix}", f"y{prefix}", f"z{prefix}")
            if not any(k in grid for k in keys[1:]):
                continue
            old_y, old_z = grid.get(keys[1], []), grid.get(keys[2], [])
            grid[keys[2]] = _relabel(old_y, "Y", "Z")
            grid[keys[1]] = _relabel(_negate(old_z), "Z", "Y")
    # Stamped here, so a payload this produced can never be turned a second time.
    payload["schema_version"] = XZ_SCHEMA_VERSION
    return True


def _negate(lines: list[Any]) -> list[Any]:
    out: list[Any] = []
    for line in lines:
        if isinstance(line, dict) and "ordinate" in line:
            out.append({**line, "ordinate": -float(line["ordinate"])})
        elif isinstance(line, (int, float)):
            out.append(-float(line))
        else:
            out.append(line)
    return out


def _relabel(lines: list[Any], old: str, new: str) -> list[Any]:
    out: list[Any] = []
    for line in lines:
        if isinstance(line, dict) and str(line.get("id", "")).startswith(old):
            out.append({**line, "id": new + str(line["id"])[len(old) :]})
        else:
            out.append(line)
    return out
