"""The saved column-splice entity (a leaf module: pydantic only)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

from opensees_studio.core._base import omit_when_default


class ColumnSplice(BaseModel):
    """A column splice at a node between two column elements (AISC 341-22 F2.6d)."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    serialize_without_defaults = omit_when_default("name")

    id: PositiveInt
    name: str = ""
    node_id: PositiveInt
    top_element_id: PositiveInt
    bottom_element_id: PositiveInt
    clear_height: PositiveFloat = Field(description="Clear height Hc between beam connections.")
