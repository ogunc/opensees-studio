"""Influence lines and moving loads: where the unit load stops, and what a vehicle does.

An :class:`~opensees_studio.core.analysis.InfluenceLineCase` walks a load along a
chain of frame members. :func:`influence_positions` lays out the stops: every
member of the path is walked from the joint it shares with the previous one,
split into ``stations`` equal intervals, and a joint shared by two members is a
stop once. A stop at a joint loads the joint; a stop inside a member loads the
member at that fraction of its length.

:func:`moving_load_envelope` takes one influence line (a response per stop,
with the stops' distances along the path) and a vehicle (axle loads and their
distances behind the front axle) and returns the largest and the smallest value
of the response as the vehicle crosses the path, in both directions of travel.
The influence line is linear between stops and zero off the path, which is how
an axle that has not yet entered the bridge, or has left it, counts.

No Qt, no OpenSees.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from opensees_studio.core.project import Project


@dataclass(frozen=True)
class InfluencePosition:
    """One stop of the moving load."""

    element_id: int
    fraction: float
    """Position along the element from its end i (0 = node i, 1 = node j)."""
    distance: float
    """Distance travelled along the path, from its start."""
    node_id: int | None
    """The joint the stop is at, None inside a member."""


class InfluencePathError(ValueError):
    """The path is not a chain of frame members."""


def _ends(project: Project, element_id: int) -> tuple[int, int]:
    from opensees_studio.core.geometry.elements import FRAME_ELEMENT_CLASSES

    element = next((e for e in project.elements if e.id == element_id), None)
    if element is None:
        raise InfluencePathError(f"Element {element_id} of the path does not exist.")
    if not isinstance(element, FRAME_ELEMENT_CLASSES):
        raise InfluencePathError(f"Element {element_id} of the path is not a frame member.")
    return int(element.nodes[0]), int(element.nodes[1])


def influence_positions(
    project: Project, path: Sequence[int], stations: int
) -> list[InfluencePosition]:
    """The stops of a load walked along ``path`` (see the module docstring).

    Raises:
        InfluencePathError: a member is missing, is not a frame, or does not
            share a joint with the previous one.
    """
    if not path:
        raise InfluencePathError("The path has no members.")
    coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
    ends = [_ends(project, eid) for eid in path]
    # The first member starts at the joint it does not share with the second.
    if len(ends) > 1:
        a, b = ends[0]
        start = b if a in ends[1] and b not in ends[1] else a
    else:
        start = ends[0][0]
    stops: list[InfluencePosition] = []
    travelled = 0.0
    here = start
    for k, (eid, (i, j)) in enumerate(zip(path, ends, strict=True)):
        if here not in (i, j):
            raise InfluencePathError(
                f"Element {eid} does not touch joint {here}, where element {path[k - 1]} ends: "
                "the path must be a chain of members in travel order."
            )
        forward = here == i
        far = j if forward else i
        length = float(np.linalg.norm(coords[far] - coords[here]))
        first = 0 if k == 0 else 1
        for step in range(first, stations + 1):
            t = step / stations
            fraction = t if forward else 1.0 - t
            node = here if step == 0 else far if step == stations else None
            stops.append(InfluencePosition(eid, fraction, travelled + t * length, node))
        travelled += length
        here = far
    return stops


def path_length(positions: Sequence[InfluencePosition]) -> float:
    return positions[-1].distance if positions else 0.0


@dataclass(frozen=True)
class MovingLoadEnvelope:
    """Extremes of one response under a vehicle crossing the path."""

    maximum: float
    minimum: float
    front_at_maximum: float
    """Position of the front axle along the path when the maximum occurs."""
    front_at_minimum: float
    reversed_at_maximum: bool
    """The maximum occurs with the vehicle travelling from the end of the path."""
    reversed_at_minimum: bool


def _sweep(
    distances: np.ndarray, values: np.ndarray, loads: np.ndarray, offsets: np.ndarray, samples: int
) -> tuple[np.ndarray, np.ndarray]:
    """Front-axle positions and the response at each, the vehicle travelling forward."""
    length = float(distances[-1])
    span = float(offsets.max()) if offsets.size else 0.0
    # Every stop of every axle is a breakpoint of the piecewise-linear total.
    fronts = np.unique(
        np.concatenate(
            [
                np.linspace(0.0, length + span, samples),
                *(distances + offset for offset in offsets),
            ]
        )
    )
    total = np.zeros_like(fronts)
    for load, offset in zip(loads, offsets, strict=True):
        at = fronts - offset
        inside = (at >= 0.0) & (at <= length)
        total += load * np.where(inside, np.interp(at, distances, values), 0.0)
    return fronts, total


def moving_load_envelope(
    distances: Sequence[float] | np.ndarray,
    values: Sequence[float] | np.ndarray,
    axles: Sequence[Any],
    *,
    samples: int = 400,
) -> MovingLoadEnvelope:
    """Largest and smallest response of a vehicle crossing the path, both ways.

    ``distances`` / ``values`` are the influence line of a **unit** load; each
    axle has a ``load`` (in the case's own sign convention, so a downward axle
    under a ``load = -1`` case is positive) and an ``offset`` behind the front axle.
    """
    d = np.asarray(distances, dtype=float)
    v = np.asarray(values, dtype=float)
    if d.size < 2:
        raise ValueError("An influence line needs at least two stops.")
    loads = np.asarray([float(a.load) for a in axles], dtype=float)
    offsets = np.asarray([float(a.offset) for a in axles], dtype=float)
    if loads.size == 0:
        raise ValueError("The vehicle has no axles.")
    forward_x, forward = _sweep(d, v, loads, offsets, samples)
    # Travelling the other way is the same vehicle on the mirrored line.
    mirrored_d = d[-1] - d[::-1]
    backward_x, backward = _sweep(mirrored_d, v[::-1], loads, offsets, samples)
    candidates = [
        (float(forward.max()), float(forward_x[int(forward.argmax())]), False),
        (float(backward.max()), float(d[-1] - backward_x[int(backward.argmax())]), True),
    ]
    lows = [
        (float(forward.min()), float(forward_x[int(forward.argmin())]), False),
        (float(backward.min()), float(d[-1] - backward_x[int(backward.argmin())]), True),
    ]
    high = max(candidates, key=lambda c: c[0])
    low = min(lows, key=lambda c: c[0])
    return MovingLoadEnvelope(
        maximum=high[0],
        minimum=low[0],
        front_at_maximum=high[1],
        front_at_minimum=low[1],
        reversed_at_maximum=high[2],
        reversed_at_minimum=low[2],
    )
