"""Multi-point constraint models."""

from __future__ import annotations

from typing import Literal

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


class RigidLinkConstraint(BaseModel):
    """``rigidLink beam`` - the constrained node moves with the retained node as a
    rigid body in every DOF: u_c = u_r + theta_r x (x_c - x_r), theta_c = theta_r.

    Needs rotational DOF (ndm 2 with ndf 3, or ndm 3 with ndf 6). A model with at
    least one rigid link runs every analysis with the Transformation constraint
    handler, which enforces it exactly. The ``type`` key tells it apart from
    :class:`EqualDOFConstraint` in ``Project.mp_constraints``.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    type: Literal["RigidLinkBeam"] = "RigidLinkBeam"
    retained_node: PositiveInt = Field(..., description="Master / retained node tag.")
    constrained_node: PositiveInt = Field(..., description="Slave / constrained node tag.")


MPConstraint = EqualDOFConstraint | RigidLinkConstraint
"""One entry of ``Project.mp_constraints``."""
