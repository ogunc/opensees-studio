"""A drawing of the structure for the report cover, as an SVG string (no Qt, no VTK).

The model is projected without a render window, so the report is built the
same way headless, in the analysis-free GUI process and in tests:

- a 3D model in isometric view from (+X, -Y, +Z), Z up — X runs to the lower
  right and Y to the upper right, as View → Isometric shows it;
- a 2D model (the global X-Z plane) in elevation.

Members are lines, shells and other area elements filled polygons drawn far to
near, supports small triangles under their joints. Zero-length elements are
left out. The browser shows the SVG as is; the PDF writer rasterises it
(:mod:`views.report_pdf`).
"""

from __future__ import annotations

import base64
import math
from collections.abc import Sequence

from opensees_studio.core import Project

_COS30 = math.cos(math.radians(30.0))
_SIN30 = 0.5
_FRAME = "#1f3b5c"
_AREA_FILL = "#dde5ee"
_AREA_EDGE = "#7a8a9a"
_SUPPORT = "#b0402a"


def _project(project: Project) -> tuple[dict[int, tuple[float, float]], dict[int, float]]:
    """Screen position (x right, y up) and closeness to the viewer of every joint."""
    planar = project.ndm == 2
    screen: dict[int, tuple[float, float]] = {}
    depth: dict[int, float] = {}
    for node in project.nodes:
        x, y, z = (*node.coords, 0.0, 0.0, 0.0)[:3]
        if planar:
            screen[node.id] = (x, z)
            depth[node.id] = -y
        else:
            screen[node.id] = ((x + y) * _COS30, z + (y - x) * _SIN30)
            depth[node.id] = x - y + z
    return screen, depth


def model_svg(project: Project, *, width: int = 520, height: int = 340) -> str | None:
    """The structure drawn to fit ``width`` × ``height`` pixels, or ``None`` with no element."""
    screen, depth = _project(project)
    lines: list[tuple[int, int]] = []
    areas: list[Sequence[int]] = []
    for element in project.elements:
        ids = [n for n in getattr(element, "nodes", ()) if n in screen]
        if len(set(ids)) < 2:
            continue
        if len(ids) == 2:
            a, b = ids
            if screen[a] != screen[b]:
                lines.append((a, b))
        else:
            areas.append(ids[:4] if len(ids) >= 4 else ids)
    if not lines and not areas:
        return None
    used = {n for pair in lines for n in pair} | {n for poly in areas for n in poly}
    xs = [screen[n][0] for n in used]
    ys = [screen[n][1] for n in used]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    margin = 18.0
    size = max(span_x / (width - 2 * margin), span_y / (height - 2 * margin), 1e-12)
    scale = 1.0 / size
    off_x = (width - span_x * scale) / 2.0 - min(xs) * scale
    off_y = (height - span_y * scale) / 2.0 + max(ys) * scale

    def at(n: int) -> tuple[float, float]:
        x, y = screen[n]
        return off_x + x * scale, off_y - y * scale

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">'
    ]
    for poly in sorted(areas, key=lambda p: sum(depth[n] for n in p) / len(p)):
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in map(at, poly))
        out.append(
            f'<polygon points="{points}" fill="{_AREA_FILL}" stroke="{_AREA_EDGE}" '
            'stroke-width="0.6"/>'
        )
    stroke = 1.6 if len(lines) < 400 else 1.0
    for a, b in sorted(lines, key=lambda p: depth[p[0]] + depth[p[1]]):
        (x1, y1), (x2, y2) = at(a), at(b)
        out.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{_FRAME}" stroke-width="{stroke}" stroke-linecap="round"/>'
        )
    tri = 5.0
    for node in project.nodes:
        if node.id in used and any(node.restraint):
            x, y = at(node.id)
            out.append(
                f'<polygon points="{x:.1f},{y:.1f} {x - tri:.1f},{y + 1.6 * tri:.1f} '
                f'{x + tri:.1f},{y + 1.6 * tri:.1f}" fill="{_SUPPORT}"/>'
            )
    out.append("</svg>")
    return "".join(out)


def svg_data_uri(svg: str) -> str:
    """``svg`` as a ``data:`` URI an ``<img>`` can carry in a self-contained page."""
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
