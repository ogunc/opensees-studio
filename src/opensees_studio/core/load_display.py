"""What the canvas draws of the loads: which patterns, in which colour, with what text.

Display → Show Load Assigns picks one load pattern or every pattern, and the
kinds of load drawn (joint, frame point, frame distributed, shell). With every
pattern each one gets a colour of :data:`PATTERN_PALETTE`, in project order, and
the canvas stacks the loads that share a member or a joint so none hides
another; a legend names the colours. The magnitudes are written in the display
units, with N and Pa promoted to kN and kPa once they reach a thousand.

No Qt, no OpenSees: the renderer and the dialog both read it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from opensees_studio.core.units import UnitConverter

#: Colours of the load patterns when every pattern is drawn, in project order.
#: Blue and cyan are left out: they are the frames and the selection.
PATTERN_PALETTE: tuple[str, ...] = (
    "#e6550d",  # orange
    "#c51b8a",  # magenta
    "#31a354",  # green
    "#d62728",  # red
    "#8c564b",  # brown
    "#9467bd",  # purple
    "#bcbd22",  # olive
    "#636363",  # grey
    "#fd8d3c",  # light orange
    "#e377c2",  # pink
)

#: Colours of the kinds of load when one pattern is drawn (and in older views).
KIND_COLORS: dict[str, str] = {
    "joint": "#33d933",
    "frame_point": "#d933bf",
    "frame_distributed": "#ff8c33",
    "shell": "#40bff2",
}

#: Names of the kinds of load, in the order the dialog lists them.
KIND_LABELS: dict[str, str] = {
    "joint": "Joint loads",
    "frame_point": "Frame point loads",
    "frame_distributed": "Frame distributed loads",
    "shell": "Shell loads",
}


def shown_patterns(patterns: Sequence[Any], pattern_id: int | None) -> list[Any]:
    """The patterns to draw: all of them, or the one ``pattern_id`` names.

    A view saved with a pattern that has since been deleted shows every
    pattern rather than nothing.
    """
    if pattern_id is None:
        return list(patterns)
    chosen = [p for p in patterns if p.id == pattern_id]
    return chosen or list(patterns)


def pattern_colors(patterns: Iterable[Any]) -> dict[int, str]:
    """A palette colour per pattern id, in project order (it wraps after ten)."""
    return {
        pattern.id: PATTERN_PALETTE[index % len(PATTERN_PALETTE)]
        for index, pattern in enumerate(patterns)
    }


def hex_to_rgb(color: str) -> tuple[float, float, float]:
    """``#rrggbb`` as three floats from 0 to 1."""
    value = color.lstrip("#")
    return (int(value[0:2], 16) / 255.0, int(value[2:4], 16) / 255.0, int(value[4:6], 16) / 255.0)


def _number(value: float) -> str:
    """Three significant figures, without a trailing ``.0``."""
    text = f"{value:.3g}"
    return text[:-2] if text.endswith(".0") else text


def _scaled(value: float, unit: str, base: str, kilo: str) -> tuple[float, str]:
    """``value`` in ``unit``, promoted to ``kilo`` when ``unit`` is ``base`` and it is large."""
    if unit == base and abs(value) >= 1000.0:
        return value / 1000.0, kilo
    return value, unit


def format_force(value: float, units: UnitConverter) -> str:
    """A force in the display units: ``50 kN``, ``11.2 kip``."""
    shown, unit = _scaled(value * units.force, units.labels.force, "N", "kN")
    return f"{_number(shown)} {unit}"


def format_line_load(start: float, end: float | None, units: UnitConverter) -> str:
    """A load per length: ``10 kN/m``, or ``0 to 15 kN/m`` when it varies.

    Plain ASCII between the values: the canvas font has no arrow glyph.
    """
    factor = units.force / units.length
    force_unit = units.labels.force
    peak = max(abs(start), abs(end if end is not None else start)) * factor
    _, unit = _scaled(peak, force_unit, "N", "kN")
    divisor = 1000.0 if unit != force_unit else 1.0
    first = _number(start * factor / divisor)
    text = (
        first
        if end is None or abs(end - start) <= 1e-9 * max(abs(start), abs(end), 1.0)
        else f"{first} to {_number(end * factor / divisor)}"
    )
    return f"{text} {unit}/{units.labels.length}"


def format_pressure(value: float, units: UnitConverter) -> str:
    """A pressure in the display units: ``2.5 kPa``, ``0.05 ksf``."""
    shown, unit = _scaled(value * units.stress, units.labels.stress, "Pa", "kPa")
    return f"{_number(shown)} {unit}"
