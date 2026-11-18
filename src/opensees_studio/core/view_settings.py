"""Per-viewport display settings.

Pure data (no Qt, no OpenSeesPy): the same object is used by the renderer, by
the View menu, and — later — by project persistence, so it must stay cheap to
copy and independent of any widget.

Every viewport owns one immutable :class:`ViewSettings`; a change produces a
new instance through :meth:`ViewSettings.with_changes`, which keeps the
renderer's "if the settings changed, rebuild" check a simple identity test.

``RenderStyle`` keeps the geometry sizes and the glyph colours that belong to
the model semantics (supports, loads, mass); the colours the user can
customise live here so a view can be themed without touching the others.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from opensees_studio.core._base import omit_when_default

#: View → Color By: one colour, or a colour per section, material or group.
ColorBy = Literal["none", "section", "material", "group"]

_HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")


class ViewSettings(BaseModel):
    """Visibility toggles, colours and screen-space sizes of one 3D viewport."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # ── visibility ───────────────────────────────────────────────────
    show_grids: bool = True
    show_grid_labels: bool = True
    show_nodes: bool = True
    show_frames: bool = True
    show_surfaces: bool = True
    show_supports: bool = True
    show_constraints: bool = True
    show_frame_assignments: bool = True
    show_releases: bool = True
    show_loads: bool = True
    show_masses: bool = False
    show_node_labels: bool = False
    show_element_labels: bool = False
    show_extruded: bool = False
    color_by: ColorBy = Field(
        default="none",
        description="Paint frames and shells by section, material or group (core.color_by).",
    )

    # ── screen-space sizes ─────────────────────────────────────────────
    #: Percentages of the viewport height, independent of the model's units.
    #: The renderer converts them to world units with the camera, so a marker
    #: keeps the same on-screen size at every zoom level.
    node_size_percent: float = Field(default=1.5, ge=0.05, le=25.0)
    support_size_percent: float = Field(default=1.5, ge=0.05, le=25.0)
    load_size_percent: float = Field(default=5.0, ge=0.05, le=25.0)
    reaction_size_percent: float = Field(default=12.0, ge=0.05, le=25.0)
    mass_size_percent: float = Field(default=1.5, ge=0.05, le=25.0)
    release_size_percent: float = Field(default=1.0, ge=0.05, le=25.0)
    #: Text is separate: pixel height, not a fraction of the model.
    label_size_px: int = Field(default=12, ge=6, le=72)

    # ── colours ──────────────────────────────────────────────────────
    background_top: str = Field(default="#dbe2ef")
    background_bottom: str = Field(default="#f5f7fb")
    node_color: str = Field(default="#d9d9d9")
    frame_color: str = Field(default="#338cd9")
    surface_color: str = Field(default="#a8b6c4")
    selected_color: str = Field(default="#00ffff")

    @field_validator(
        "background_top",
        "background_bottom",
        "node_color",
        "frame_color",
        "surface_color",
        "selected_color",
    )
    @classmethod
    def _check_hex(cls, value: str) -> str:
        """Reject anything the VTK colour maps cannot parse."""
        if not _HEX_COLOUR.match(value):
            raise ValueError(f"expected a #rrggbb colour, got {value!r}")
        return value

    serialize_without_defaults = omit_when_default(
        "color_by",
        "show_masses",
        "show_releases",
        "node_size_percent",
        "support_size_percent",
        "load_size_percent",
        "reaction_size_percent",
        "mass_size_percent",
        "release_size_percent",
        "label_size_px",
    )

    def with_changes(self, **changes: object) -> ViewSettings:
        """Return a copy with ``changes`` applied (the instance is immutable)."""
        unknown = set(changes) - set(type(self).model_fields)
        if unknown:
            raise ValueError(f"unknown view setting(s): {', '.join(sorted(unknown))}")
        return self.model_copy(update=changes)

    @property
    def node_lut(self) -> list[str]:
        """Colour lookup table for node glyphs: normal, selected."""
        return [self.node_color, self.selected_color]

    @property
    def frame_lut(self) -> list[str]:
        """Colour lookup table for frame glyphs: normal, selected."""
        return [self.frame_color, self.selected_color]

    @property
    def surface_lut(self) -> list[str]:
        """Colour lookup table for shell/area glyphs: normal, selected."""
        return [self.surface_color, self.selected_color]
