"""Common base class for all domain entities.

Every entity carries a positive integer ``id`` (used as the OpenSees tag
when the model is built) and an optional human-readable ``name``.
The base class is frozen by default — entities are immutable once
created; mutations go through the ``Project`` aggregator which produces
new instances. This keeps undo/redo and change tracking trivial.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, PositiveInt


class Entity(BaseModel):
    """Base class for every persisted domain object."""

    model_config = ConfigDict(
        frozen=False,            # individual setters allowed; we lock at the Project boundary
        extra="forbid",          # unknown JSON keys are an error, not a silent ignore
        validate_assignment=True,
        populate_by_name=True,
    )

    id: PositiveInt = Field(..., description="Unique tag within its kind. Used as the OpenSees tag.")
    name: str = Field(default="", description="Optional human-readable label.")
