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

    node_color: str = "#f0a500"            # warm gold
    node_selected_color: str = "#00d4ff"   # bright cyan

    frame_color: str = "#1f1f1f"
    truss_color: str = "#2e5cb8"
    zerolength_color: str = "#a020f0"
    selected_color: str = "#00d4ff"

    fix_color: str = "#c0392b"             # firebrick
    pin_color: str = "#c0392b"
    roller_color: str = "#e67e22"
    custom_support_color: str = "#7f8c8d"

    load_color: str = "#27ae60"
    mass_color: str = "#9b59b6"

    # ── sizes (relative to bbox diagonal unless absolute) ────────────
    node_relative_radius: float = 0.008
    node_min_radius: float = 0.05

    tube_relative_radius: float = 0.004
    tube_min_radius: float = 0.02

    support_relative_size: float = 0.025
    support_min_size: float = 0.10

    load_relative_length: float = 0.10     # arrow length / bbox_diag
    load_min_length: float = 0.5

    selection_thickness_factor: float = 1.6  # multiplier for selected actors
