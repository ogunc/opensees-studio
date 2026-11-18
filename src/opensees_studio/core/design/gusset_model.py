"""The saved gusset-plate entity (a leaf module: pydantic only)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

from opensees_studio.core._base import omit_when_default


class Gusset(BaseModel):
    """A gusset plate at one end of a brace (AISC 341-22 F2.6c)."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    serialize_without_defaults = omit_when_default(
        "name", "weld_leg", "weld_both_sides", "weld_fexx"
    )

    id: PositiveInt
    name: str = ""
    brace_element_id: PositiveInt
    t: PositiveFloat = Field(description="Plate thickness.")
    b: PositiveFloat = Field(description="Plate width (Whitmore width provided).")
    lw: PositiveFloat = Field(description="Whitmore length along the brace.")
    free_length: PositiveFloat = Field(description="Free length Lc for plate buckling.")
    weld_leg: PositiveFloat | None = Field(
        default=None,
        description="Fillet weld leg size; None leaves the F2.6c.4 weld unchecked.",
    )
    weld_both_sides: bool = Field(
        default=True, description="Weld on both sides of the gusset plate."
    )
    weld_fexx: PositiveFloat | None = Field(
        default=None,
        description="Electrode strength Fexx; None takes 70 ksi (480 MPa) in project units.",
    )
