"""Visual style for the 3D model viewport.

All colors, sizes, and glyph parameters live here. Changes apply
globally through the renderer; downstream code never hard-codes a
color or radius. A future "theme" feature can simply swap a different
RenderStyle instance.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RenderStyle:
    """Immutable style bundle. Construct with overrides if needed."""

    # ── colors ───────────────────────────────────────────────────────
    background_top: str = "#dbe2ef"
    background_bottom: str = "#f5f7fb"

    node_color: str = "#f0a500"  # warm gold
    node_selected_color: str = "#00d4ff"  # bright cyan

    frame_color: str = "#1f1f1f"
    truss_color: str = "#2e5cb8"
    zerolength_color: str = "#a020f0"
    selected_color: str = "#00d4ff"

    fix_color: str = "#c0392b"  # firebrick
    pin_color: str = "#c0392b"
    roller_color: str = "#e67e22"
    custom_support_color: str = "#7f8c8d"

    #: Support and support-spring symbols: every part takes the colour of the
    #: axis it holds, as the origin triad does (X red, Y green, Z blue). The
    #: outline is the edge of a 3D solid whose faces show two axes.
    support_x_color: str = "#d0402f"
    support_y_color: str = "#2f9e4f"
    support_z_color: str = "#2f5fcf"
    support_outline_color: str = "#2b3440"

    load_color: str = "#27ae60"
    mass_color: str = "#9b59b6"

    # ── sizes (relative to bbox diagonal unless absolute) ────────────
    node_relative_radius: float = 0.008
    node_min_radius: float = 0.05

    tube_relative_radius: float = 0.004
    tube_min_radius: float = 0.02

    support_relative_size: float = 0.025
    support_min_size: float = 0.10

    load_relative_length: float = 0.10  # arrow length / bbox_diag
    load_min_length: float = 0.5

    selection_thickness_factor: float = 1.6  # multiplier for selected actors

    @property
    def is_dark(self) -> bool:
        """Whether the viewport background is dark (labels then need light ink)."""
        mean = (
            relative_luminance(self.background_top) + relative_luminance(self.background_bottom)
        ) / 2.0
        return mean < 0.18

    @property
    def background(self) -> str:
        """The end of the gradient where label text has the least contrast."""
        ends = sorted((self.background_top, self.background_bottom), key=relative_luminance)
        return ends[1] if self.is_dark else ends[0]

    @property
    def label_ink(self) -> str:
        """Text colour of node, element, load-value and axis labels."""
        return "#f1f5f9" if self.is_dark else "#111111"

    @property
    def label_paper(self) -> str:
        """The translucent box behind those labels."""
        return "#0b0d11" if self.is_dark else "#ffffff"


def relative_luminance(colour: str) -> float:
    """WCAG 2.x relative luminance of an ``#rrggbb`` (or ``#rgb``) colour."""
    hex_digits = colour.lstrip("#")
    if len(hex_digits) == 3:
        hex_digits = "".join(ch * 2 for ch in hex_digits)
    channels = []
    for k in range(3):
        value = int(hex_digits[2 * k : 2 * k + 2], 16) / 255.0
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2.x contrast ratio between two colours (1 to 21)."""
    a, b = relative_luminance(foreground), relative_luminance(background)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def legible(colour: str, background: str, minimum: float = 3.0) -> str:
    """``colour`` mixed towards white or black until it reaches ``minimum`` on ``background``.

    Keeps the hue of a data colour (a load pattern, a Color By category) while
    making text drawn in it readable on either viewport background.
    """
    if contrast_ratio(colour, background) >= minimum:
        return colour
    target = 255 if relative_luminance(background) < 0.18 else 0
    rgb = [int(colour.lstrip("#")[2 * k : 2 * k + 2], 16) for k in range(3)]
    for step in range(1, 21):
        t = step / 20.0
        mixed = "#" + "".join(f"{round(c + (target - c) * t):02x}" for c in rgb)
        if contrast_ratio(mixed, background) >= minimum:
            return mixed
    return "#ffffff" if target else "#000000"
