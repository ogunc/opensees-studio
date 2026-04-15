"""Cross sections.

We currently support:
- ``ElasticSection``: closed-form linear-elastic frame section.
- ``FiberSection``: arbitrary cross section composed of patches/layers
  of uniaxial fibres. The fibre material refs are resolved at the
  Project level (string IDs are validated against the materials table).

For Phase 1 the fibre section is intentionally minimal — a flat list
of fibres with (y, z, area, material_id). Patch and layer generators
(rectangular patch, circular patch, straight layer) belong to a small
helper module added in Phase 5; they produce these flat fibres.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

from opensees_studio.core._base import Entity


class ElasticSection(Entity):
    """Linear-elastic frame section — ``section Elastic``."""

    type: Literal["ElasticSection"] = "ElasticSection"
    E: PositiveFloat
    A: PositiveFloat
    Iz: PositiveFloat = Field(..., description="Moment of inertia about local z-axis.")
    Iy: PositiveFloat | None = Field(default=None, description="Required for 3D frames.")
    G: PositiveFloat | None = Field(default=None, description="Shear modulus; required for 3D frames.")
    J: PositiveFloat | None = Field(default=None, description="Torsional constant; required for 3D frames.")


class Fibre(BaseModel):
    """A single fibre inside a ``FiberSection``."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    y: float = Field(..., description="Local y-coordinate of the fibre centroid.")
    z: float = Field(..., description="Local z-coordinate of the fibre centroid.")
    area: PositiveFloat
    material_id: PositiveInt


class FiberSection(Entity):
    """Discretised section — ``section Fiber``."""

    type: Literal["FiberSection"] = "FiberSection"
    GJ: PositiveFloat | None = Field(default=None, description="Optional torsional rigidity.")
    fibres: list[Fibre] = Field(default_factory=list)


Section = Annotated[
    Union[ElasticSection, FiberSection],
    Field(discriminator="type"),
]
