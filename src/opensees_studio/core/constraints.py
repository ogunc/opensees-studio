"""Multi-point constraint models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

from opensees_studio.core._base import Entity


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


class RigidDiaphragm(Entity):
    """``rigidDiaphragm`` - a floor that is rigid in its own plane.

    Every constrained node follows the retained node in the two in-plane
    translations and the rotation about ``perp_dirn``; the out-of-plane DOFs
    stay free (slabs bend, columns shorten). The constrained nodes are either
    listed (``constrained_nodes``) or every joint of a storey (``storey_id``,
    resolved when the model is built, so joints drawn later join the floor).

    The retained node is a model node: usually one placed at the centre of
    mass of the floor and connected to no element, whose out-of-plane DOFs
    the runner then fixes (it has no stiffness there), or an existing joint.
    See :mod:`core.diaphragms`.
    """

    perp_dirn: Literal[1, 2, 3] = Field(
        default=3, description="Axis perpendicular to the plane (3 = Z, a horizontal floor)."
    )
    retained_node: PositiveInt = Field(..., description="Master / retained node tag.")
    constrained_nodes: tuple[PositiveInt, ...] = Field(
        default=(), description="Slave nodes; empty when the storey supplies them."
    )
    storey_id: PositiveInt | None = Field(
        default=None, description="Constrain every joint of this storey."
    )

    @model_validator(mode="after")
    def _one_source(self) -> RigidDiaphragm:
        if self.storey_id is None and not self.constrained_nodes:
            raise ValueError("A rigid diaphragm needs constrained nodes or a storey.")
        if self.storey_id is not None and self.constrained_nodes:
            raise ValueError("A rigid diaphragm takes either a node list or a storey, not both.")
        if self.storey_id is not None and self.perp_dirn != 3:
            raise ValueError("A storey diaphragm is horizontal: perp_dirn must be 3.")
        if self.retained_node in self.constrained_nodes:
            raise ValueError("The retained node cannot also be a constrained node.")
        return self


class RigidLink(BaseModel):
    """``rigidLink`` - a rigid ``beam`` (all DOFs, with the lever arm) or ``bar`` (translations)."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    kind: Literal["beam", "bar"] = "beam"
    retained_node: PositiveInt = Field(..., description="Master / retained node tag.")
    constrained_node: PositiveInt = Field(..., description="Slave / constrained node tag.")

    @model_validator(mode="after")
    def _distinct(self) -> RigidLink:
        if self.retained_node == self.constrained_node:
            raise ValueError("A rigid link needs two different nodes.")
        return self
