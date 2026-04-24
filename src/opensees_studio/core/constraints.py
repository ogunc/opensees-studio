"""Multi-point constraint models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, PositiveInt


class EqualDOFConstraint(BaseModel):
    """``equalDOF`` - slave node follows the retained node in chosen DOFs."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    retained_node: PositiveInt = Field(..., description="Master / retained node tag.")
    constrained_node: PositiveInt = Field(..., description="Slave / constrained node tag.")
    dofs: tuple[int, ...] = Field(
        ...,
        min_length=1,
        description="1-based DOF ids constrained to move together.",
    )
