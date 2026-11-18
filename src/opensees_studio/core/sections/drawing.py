"""Drawing commands of the Section Designer (Define → Section Designer).

A command line like a CAD program's: each command adds regions to the section,
or edits the ones there, in the project's length unit. Coordinates are local
``(y, z)``: y up the depth, z across the width.

=====================================  =========================================
``rect W H [Y Z]``                     rectangle W wide (z) by H deep (y), centred
                                       at (Y, Z), default the origin
``circle D [Y Z]``                     circle of diameter D
``poly Y1,Z1 Y2,Z2 Y3,Z3 ...``         polygon through the vertices
``ishape D BF TF TW [Y Z]``            I-shape: depth, flange width and
                                       thickness, web thickness
``channel D BF TF TW [Y Z]``           channel, web on the left (-z), open to +z
``tee D BF TF TW [Y Z]``               tee, flange on top
``angle D B T [Y Z]``                  angle: vertical leg D, horizontal leg B,
                                       thickness T, heel at (Y, Z)
``tube W H T [Y Z]``                   rectangular tube, wall T
``pipe D T [Y Z]``                     round tube, wall T
``hole <rect|circle|poly> ...``        the same shapes, as a hole
``move N DY DZ``                       move region N (1 = first; ``last`` too)
``delete N``                           remove region N
``center``                             move everything so the centroid is at 0
``clear``                              remove every region
=====================================  =========================================

:func:`elastic_section` and :func:`fiber_section` turn the regions into a
section the model can use.

:func:`run_command` returns the new list of regions and a message; a bad
command raises :class:`CommandError` with what was wrong.

No Qt.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from opensees_studio.core.sections import ElasticSection, FiberSection, Fibre
from opensees_studio.core.sections.geometry import (
    CircleRegion,
    Point,
    PolygonRegion,
    Region,
    rectangle,
    region_fibres,
    section_properties,
    torsion_constant,
)

COMMANDS = (
    "rect",
    "circle",
    "poly",
    "ishape",
    "channel",
    "tee",
    "angle",
    "tube",
    "pipe",
    "hole",
    "move",
    "delete",
    "center",
    "clear",
)


class CommandError(ValueError):
    """A command the designer cannot run."""


@dataclass(frozen=True)
class CommandResult:
    regions: list[Region]
    message: str


def _numbers(words: Sequence[str], needed: int, optional: int, usage: str) -> list[float]:
    if not needed <= len(words) <= needed + optional:
        raise CommandError(f"Usage: {usage}")
    try:
        return [float(w) for w in words]
    except ValueError as exc:
        raise CommandError(f"Not a number in {' '.join(words)!r}. Usage: {usage}") from exc


def _positive(values: Sequence[float], usage: str) -> None:
    if any(v <= 0 for v in values):
        raise CommandError(f"Dimensions must be positive. Usage: {usage}")


def _at(values: list[float], count: int) -> tuple[float, float]:
    return (values[count], values[count + 1]) if len(values) > count else (0.0, 0.0)


def _poly(points: Sequence[tuple[float, float]], y: float, z: float, hole: bool) -> PolygonRegion:
    return PolygonRegion(tuple((py + y, pz + z) for py, pz in points), hole)


def profile_outline(kind: str, d: float, bf: float, tf: float, tw: float) -> list[Point]:
    """Vertices of an ``ishape``, ``channel`` or ``tee``, depth along y, centred on its box."""
    if kind == "ishape":
        h, b, t, w = d / 2.0, bf / 2.0, tf, tw / 2.0
        return [
            (-h, -b),
            (-h, b),
            (-h + t, b),
            (-h + t, w),
            (h - t, w),
            (h - t, b),
            (h, b),
            (h, -b),
            (h - t, -b),
            (h - t, -w),
            (-h + t, -w),
            (-h + t, -b),
        ]
    if kind == "channel":
        h = d / 2.0
        outline = [
            (-h, 0.0),
            (-h, bf),
            (-h + tf, bf),
            (-h + tf, tw),
            (h - tf, tw),
            (h - tf, bf),
            (h, bf),
            (h, 0.0),
        ]
        return [(py, pz - bf / 2.0) for py, pz in outline]
    if kind == "tee":
        h, b, w = d / 2.0, bf / 2.0, tw / 2.0
        return [
            (-h, -w),
            (-h, w),
            (h - tf, w),
            (h - tf, b),
            (h, b),
            (h, -b),
            (h - tf, -b),
            (h - tf, -w),
        ]
    raise ValueError(f"Unknown profile {kind!r}.")


def shape_regions(kind: str, words: Sequence[str], *, hole: bool = False) -> list[Region]:
    """The regions one shape command draws (``kind`` without the ``hole`` prefix)."""
    if kind == "rect":
        usage = "rect W H [Y Z]"
        v = _numbers(words, 2, 2, usage)
        _positive(v[:2], usage)
        y, z = _at(v, 2)
        return [rectangle(v[0], v[1], y, z, hole=hole)]
    if kind == "circle":
        usage = "circle D [Y Z]"
        v = _numbers(words, 1, 2, usage)
        _positive(v[:1], usage)
        y, z = _at(v, 1)
        return [CircleRegion(y, z, v[0] / 2.0, hole)]
    if kind == "poly":
        usage = "poly Y1,Z1 Y2,Z2 Y3,Z3 ..."
        points: list[tuple[float, float]] = []
        try:
            for word in words:
                y_text, z_text = word.split(",")
                points.append((float(y_text), float(z_text)))
        except ValueError as exc:
            raise CommandError(f"Vertices are Y,Z pairs. Usage: {usage}") from exc
        if len(points) < 3:
            raise CommandError(f"A polygon needs three vertices. Usage: {usage}")
        return [PolygonRegion(tuple(points), hole)]
    if kind in ("ishape", "channel", "tee"):
        usage = f"{kind} D BF TF TW [Y Z]"
        v = _numbers(words, 4, 2, usage)
        _positive(v[:4], usage)
        d, bf, tf, tw = v[:4]
        y, z = _at(v, 4)
        if tw >= bf or (2 if kind != "tee" else 1) * tf >= d:
            raise CommandError("The web and the flanges do not fit in the depth and width.")
        outline = profile_outline(kind, d, bf, tf, tw)
        return [_poly(outline, y, z, hole)]
    if kind == "angle":
        usage = "angle D B T [Y Z]"
        v = _numbers(words, 3, 2, usage)
        _positive(v[:3], usage)
        d, b, t = v[:3]
        if t >= min(d, b):
            raise CommandError("The thickness must be less than both legs.")
        y, z = _at(v, 3)
        return [_poly([(0.0, 0.0), (0.0, b), (t, b), (t, t), (d, t), (d, 0.0)], y, z, hole)]
    if kind == "tube":
        usage = "tube W H T [Y Z]"
        v = _numbers(words, 3, 2, usage)
        _positive(v[:3], usage)
        w, h, t = v[:3]
        if 2.0 * t >= min(w, h):
            raise CommandError("The wall is too thick for the tube.")
        y, z = _at(v, 3)
        return [
            rectangle(w, h, y, z, hole=hole),
            rectangle(w - 2 * t, h - 2 * t, y, z, hole=not hole),
        ]
    if kind == "pipe":
        usage = "pipe D T [Y Z]"
        v = _numbers(words, 2, 2, usage)
        _positive(v[:2], usage)
        d, t = v[:2]
        if 2.0 * t >= d:
            raise CommandError("The wall is too thick for the pipe.")
        y, z = _at(v, 2)
        return [CircleRegion(y, z, d / 2.0, hole), CircleRegion(y, z, d / 2.0 - t, not hole)]
    raise CommandError(f"Unknown shape {kind!r}.")


def _index(word: str, regions: Sequence[Region]) -> int:
    if not regions:
        raise CommandError("There is no region yet.")
    if word.lower() == "last":
        return len(regions) - 1
    try:
        k = int(word)
    except ValueError as exc:
        raise CommandError(f"{word!r} is not a region number.") from exc
    if not 1 <= k <= len(regions):
        raise CommandError(f"There is no region {k} (1 to {len(regions)}).")
    return k - 1


def moved(region: Region, dy: float, dz: float) -> Region:
    if isinstance(region, CircleRegion):
        return replace(region, y=region.y + dy, z=region.z + dz)
    return replace(region, points=tuple((y + dy, z + dz) for y, z in region.points))


def run_command(text: str, regions: Sequence[Region]) -> CommandResult:
    """Run one command line on ``regions`` (left unchanged) and return the new list."""
    words = text.replace(";", " ").split()
    if not words:
        raise CommandError("Type a command: " + ", ".join(COMMANDS) + ".")
    verb, rest = words[0].lower(), words[1:]
    current = list(regions)
    if verb == "hole":
        if not rest:
            raise CommandError("Usage: hole <rect|circle|poly|...> ...")
        added = shape_regions(rest[0].lower(), rest[1:], hole=True)
        return CommandResult(current + added, f"Added a {rest[0].lower()} hole.")
    if verb in ("rect", "circle", "poly", "ishape", "channel", "tee", "angle", "tube", "pipe"):
        added = shape_regions(verb, rest)
        return CommandResult(current + added, f"Added a {verb} ({len(added)} region(s)).")
    if verb == "move":
        if len(rest) != 3:
            raise CommandError("Usage: move N DY DZ")
        k = _index(rest[0], current)
        dy, dz = _numbers(rest[1:], 2, 0, "move N DY DZ")
        current[k] = moved(current[k], dy, dz)
        return CommandResult(current, f"Moved region {k + 1}.")
    if verb == "delete":
        if len(rest) != 1:
            raise CommandError("Usage: delete N")
        k = _index(rest[0], current)
        del current[k]
        return CommandResult(current, f"Deleted region {k + 1}.")
    if verb == "center":
        if not current:
            raise CommandError("There is no region yet.")
        props = section_properties(current, plastic=False)
        shifted = [moved(r, -props.y_c, -props.z_c) for r in current]
        return CommandResult(shifted, f"Moved the centroid ({props.y_c:g}, {props.z_c:g}) to 0.")
    if verb == "clear":
        return CommandResult([], "Cleared the section.")
    raise CommandError(f"Unknown command {verb!r}. Commands: " + ", ".join(COMMANDS) + ".")


def describe(region: Region) -> str:
    """One line for the region list."""
    kind = "hole" if region.hole else "solid"
    if isinstance(region, CircleRegion):
        return f"{kind} circle D={2 * region.radius:g} at ({region.y:g}, {region.z:g})"
    return f"{kind} polygon, {len(region.points)} vertices"


# ──────────────────────────── the section ────────────────────────────
def elastic_section(
    regions: Sequence[Region],
    *,
    section_id: int,
    name: str,
    modulus: float,
    poisson: float = 0.3,
    torsion: float | None = None,
) -> ElasticSection:
    """An elastic section with the regions' area and centroidal second moments.

    ``torsion`` (J) defaults to :func:`core.sections.geometry.torsion_constant`.
    The product of inertia is left out (OpenSees' elastic section has none).
    """
    props = section_properties(regions, plastic=False)
    return ElasticSection(
        id=section_id,
        name=name,
        E=modulus,
        A=props.A,
        Iz=props.Iz,
        Iy=props.Iy,
        G=modulus / (2.0 * (1.0 + poisson)),
        J=torsion if torsion is not None else torsion_constant(regions),
    )


def fiber_section(
    regions: Sequence[Region],
    *,
    section_id: int,
    name: str,
    material_id: int,
    torsional_rigidity: float | None = None,
    cells: int = 30,
) -> FiberSection:
    """A fibre section of one material: a ``cells × cells`` grid over the regions.

    The fibres sit at the centroid of the region inside each cell
    (:func:`core.sections.geometry.region_fibres`), relative to the regions' own
    centroid, so the section's axes pass through it whatever the drawing's origin.
    """
    props = section_properties(regions, plastic=False)
    grid = region_fibres(regions, cells, cells)
    fibres = [
        Fibre(
            y=float(y - props.y_c), z=float(z - props.z_c), area=float(a), material_id=material_id
        )
        for y, z, a in zip(grid.y, grid.z, grid.area, strict=True)
        if a > 0
    ]
    return FiberSection(id=section_id, name=name, fibres=fibres, GJ=torsional_rigidity)
