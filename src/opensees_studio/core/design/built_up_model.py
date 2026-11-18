"""The built-up I-shapes a project defines (Design → Built-Up Shapes).

Kept apart from :mod:`core.design.built_up`, which turns them into the shapes
the member check uses: ``core.design.settings`` imports this model and
``Project`` imports the settings, so it must not pull the checks back in.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, model_validator


class BuiltUpShape(BaseModel):
    """A doubly symmetric I-shape welded from three plates, in project units."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    name: str = Field(min_length=1, description="The name sections and members refer to.")
    d: PositiveFloat = Field(description="Overall depth.")
    bf: PositiveFloat = Field(description="Flange width.")
    tf: PositiveFloat = Field(description="Flange thickness.")
    tw: PositiveFloat = Field(description="Web thickness.")
    stiffener_spacing: PositiveFloat | None = Field(
        default=None,
        description="Clear spacing a of transverse web stiffeners; None = unstiffened.",
    )

    @model_validator(mode="after")
    def _proportions(self) -> BuiltUpShape:
        if 2.0 * self.tf >= self.d:
            raise ValueError(f"{self.name}: the flanges (2 tf) take the whole depth d.")
        if self.tw >= self.bf:
            raise ValueError(f"{self.name}: the web is not thinner than the flange is wide.")
        return self
