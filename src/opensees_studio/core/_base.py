"""Common base class for all domain entities.

Every entity carries a positive integer ``id`` (used as the OpenSees tag
when the model is built) and an optional human-readable ``name``.
Entities are mutable: a field can be set in place, and
``validate_assignment`` checks every assignment against the field's type and
constraints. The GUI changes the model only through undo commands
(``commands/``), which record the previous value, so undo/redo does not need
immutable entities. Unknown keys are refused (``extra="forbid"``).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_serializer


class Entity(BaseModel):
    """Base class for every persisted domain object."""

    model_config = ConfigDict(
        frozen=False,  # individual setters allowed; we lock at the Project boundary
        extra="forbid",  # unknown JSON keys are an error, not a silent ignore
        validate_assignment=True,
        populate_by_name=True,
    )

    id: PositiveInt = Field(
        ..., description="Unique tag within its kind. Used as the OpenSees tag."
    )
    name: str = Field(default="", description="Optional human-readable label.")


def omit_when_default(*names: str) -> Any:
    """A ``model_serializer`` leaving ``names`` out of a dump while they hold their default.

    For options added to an existing model: a project that does not use the
    option saves byte-identical to before, and loading fills the default back
    in. Assign the result to a class attribute::

        serialize_without_defaults = omit_when_default("integration")
    """

    @model_serializer(mode="wrap")
    def _serialize(self: BaseModel, handler: Any) -> Any:
        data = handler(self)
        fields = type(self).model_fields
        for name in names:
            if getattr(self, name) == fields[name].get_default(call_default_factory=True):
                data.pop(fields[name].alias or name, None)
        return data

    return _serialize
