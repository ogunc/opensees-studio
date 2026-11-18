"""Paint frame members by their design ratio (Design → Display Steel Ratios).

An overlay layer like the force diagram: one thick line per member checked,
coloured by the band of its governing demand/capacity ratio
(:mod:`core.design.ratio_bands`), with the ratio written at mid-length. A member
the check did not cover is drawn grey and unlabelled, so the picture also shows
what was left out.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterable
from typing import Any

import numpy as np
import pyvista as pv

from opensees_studio.core.design.ratio_bands import ratio_color

#: Width of the coloured members, in pixels.
LINE_WIDTH = 7.0


def _rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


class DesignRatioRenderer:
    """Draws one design ratio overlay on a plotter."""

    def __init__(self, plotter: Any) -> None:
        self._plotter = plotter
        self._actor: Any = None
        self._label_actor: Any = None
        self.members = 0
        """Members drawn by the last :meth:`render` (designed or not)."""

    def render(self, project: Any, members: Iterable[Any], *, limit: float = 1.0) -> None:
        """Draw ``members`` (``MemberResult`` rows of a steel check)."""
        self.clear()
        coords = {n.id: np.asarray(n.coords, dtype=float) for n in project.nodes}
        elements = {e.id: e for e in project.elements}
        points: list[np.ndarray] = []
        colors: list[tuple[int, int, int]] = []
        label_points: list[np.ndarray] = []
        labels: list[str] = []
        for member in members:
            element = elements.get(member.element_id)
            if element is None or len(element.nodes) != 2:
                continue
            pi, pj = coords.get(element.nodes[0]), coords.get(element.nodes[1])
            if pi is None or pj is None:
                continue
            designed = member.status != "not designed"
            points += [pi, pj]
            colors.append(_rgb(ratio_color(member.ratio, designed=designed, limit=limit)))
            if designed:
                label_points.append((pi + pj) / 2.0)
                labels.append(f"{member.ratio:.2f}")
        self.members = len(colors)
        if not colors:
            return
        lines = np.hstack([[2, 2 * k, 2 * k + 1] for k in range(len(colors))]).astype(np.int64)
        mesh = pv.PolyData(np.vstack(points), lines=lines)
        mesh.cell_data["rgb"] = np.asarray(colors, dtype=np.uint8)
        self._actor = self._plotter.add_mesh(
            mesh,
            scalars="rgb",
            rgb=True,
            line_width=LINE_WIDTH,
            render_lines_as_tubes=True,
            lighting=False,
            pickable=False,
            render=False,
        )
        if labels:
            with contextlib.suppress(Exception):
                self._label_actor = self._plotter.add_point_labels(
                    np.vstack(label_points),
                    labels,
                    font_size=12,
                    point_size=0,
                    shape=None,
                    always_visible=True,
                    pickable=False,
                    render=False,
                )

    def clear(self) -> None:
        for actor in (self._actor, self._label_actor):
            if actor is not None:
                with contextlib.suppress(Exception):
                    self._plotter.remove_actor(actor, render=False)
        self._actor = None
        self._label_actor = None
        self.members = 0

    @property
    def is_drawn(self) -> bool:
        return self._actor is not None
