"""The shear tab a project saves, and the bolt grades it can take.

Kept apart from :mod:`core.design.shear_tab`, which checks it with the Chapter J
functions: ``core.design.settings`` imports this model, and ``Project`` imports
the settings, so it must not pull the checks (and through them ``core``) back
in. Same split as ``chapter_j_model`` and ``gusset_model``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

BOLT_GRADES: dict[str, tuple[str, float]] = {
    "A325-N": ("ASTM F3125 A325, threads included (N)", 54.0),
    "A325-X": ("ASTM F3125 A325, threads excluded (X)", 68.0),
    "A490-N": ("ASTM F3125 A490, threads included (N)", 68.0),
    "A490-X": ("ASTM F3125 A490, threads excluded (X)", 84.0),
}
"""Bolt grades: label and Fnv in ksi (AISC 360 Table J3.2)."""


class ShearTabDesign(BaseModel):
    """The shear tab at one end of one beam, as a project saves it (project units)."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    element_id: PositiveInt
    end: str = Field(pattern="^[ij]$", description="Which end of the beam: 'i' or 'j'.")
    bolts: PositiveInt = Field(ge=2, le=12)
    bolt_diameter: PositiveFloat
    bolt_grade: str = "A325-N"
    spacing: PositiveFloat
    """Bolt spacing s."""
    edge_vertical: PositiveFloat
    """Lev: from the end bolts to the top and bottom of the plate."""
    edge_horizontal: PositiveFloat
    """Leh: from the bolt line to the plate's free edge."""
    weld_to_bolts: PositiveFloat
    """a: from the weld (the support face) to the bolt line."""
    tp: PositiveFloat
    plate_grade: str = "A36"
    weld_leg: PositiveFloat
    fexx: PositiveFloat
    """Weld metal strength, in project units (70 ksi for E70)."""

    @property
    def length(self) -> float:
        """Plate length: ``(n - 1) s + 2 Lev``."""
        return (self.bolts - 1) * self.spacing + 2.0 * self.edge_vertical
