"""Colour bands of a demand/capacity ratio, as a SAP2000-style design display.

A member checked by a design code is painted by its governing ratio: the bands
step at 0.5, 0.7, 0.9 and the ratio limit (1.0 by default), so a member over the
limit is red whatever its number, and a member that was not designed (no shape
the provisions cover) is grey. The view reads the colours from here, the report
and the legend too, so the three never disagree.

No Qt.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Colour of a member the check did not cover.
NOT_DESIGNED_COLOR = "#9e9e9e"


@dataclass(frozen=True)
class RatioBand:
    """Ratios up to ``upper`` (inclusive) of a band take ``color``."""

    upper: float
    color: str
    label: str


def ratio_bands(limit: float = 1.0) -> tuple[RatioBand, ...]:
    """The bands for a ratio ``limit``: the last band holds everything above it.

    The intermediate steps are 0.5, 0.7 and 0.9 times the limit, so a project
    that checks against 0.95 keeps the same reading.
    """
    steps = (0.5 * limit, 0.7 * limit, 0.9 * limit, limit)
    colors = ("#4a7fd4", "#2ea8a0", "#5cb85c", "#f0ad4e")
    bands: list[RatioBand] = []
    lower = 0.0
    for upper, color in zip(steps, colors, strict=True):
        bands.append(RatioBand(upper, color, f"{lower:.2f} to {upper:.2f}"))
        lower = upper
    bands.append(RatioBand(float("inf"), "#d9534f", f"> {limit:.2f}"))
    return tuple(bands)


def ratio_color(ratio: float, *, designed: bool = True, limit: float = 1.0) -> str:
    """The colour of a governing ``ratio`` (grey when the member was not designed)."""
    if not designed:
        return NOT_DESIGNED_COLOR
    for band in ratio_bands(limit):
        if ratio <= band.upper:
            return band.color
    return ratio_bands(limit)[-1].color
