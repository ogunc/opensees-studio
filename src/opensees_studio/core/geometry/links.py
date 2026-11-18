"""Link elements between two joints: ``twoNodeLink`` and ``TripleFrictionPendulum``.

* :class:`TwoNodeLinkElement` — one uniaxial material per local direction
  (OpenSees ``twoNodeLink``): dampers, gap or hook links, an isolator built from
  any hysteretic material, a panel spring. Its local axes default to OpenSees'
  (x along i→j; coincident joints need ``orient``).
* :class:`TripleFrictionPendulumElement` — the triple friction pendulum
  isolator (``TripleFrictionPendulum``, 3D only): three friction models for the
  four sliding surfaces (the two inner ones share the first), a vertical
  material and three rotational ones, the effective radii ``L1..L3`` and the
  displacement limits ``d1..d3``. It needs the gravity load on it before any
  lateral load (a preload case), as OpenSees' own examples do.

No Qt, no OpenSees.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, PositiveFloat, PositiveInt, model_validator

from opensees_studio.core._base import Entity


class TwoNodeLinkElement(Entity):
    """``twoNodeLink``: a uniaxial material in each chosen local direction."""

    type: Literal["TwoNodeLink"] = "TwoNodeLink"
    nodes: tuple[PositiveInt, PositiveInt]
    material_ids: tuple[PositiveInt, ...] = Field(..., min_length=1)
    dirs: tuple[int, ...] = Field(
        ..., min_length=1, description="Local directions, 1..6 (3D) or 1..3 (2D), one per material."
    )
    orient: tuple[float, float, float, float, float, float] | None = Field(
        default=None,
        description="Local x and y vectors (x1 x2 x3 y1 y2 y3); None = OpenSees' default axes.",
    )
    do_rayleigh: bool = Field(default=False, description="Emit -doRayleigh.")
    mass: float = Field(default=0.0, ge=0.0, description="Lumped element mass (-mass).")

    @model_validator(mode="after")
    def _one_material_per_direction(self) -> TwoNodeLinkElement:
        if len(self.material_ids) != len(self.dirs):
            raise ValueError("twoNodeLink: give one material per direction.")
        if len(set(self.dirs)) != len(self.dirs) or not all(1 <= d <= 6 for d in self.dirs):
            raise ValueError("twoNodeLink: directions are distinct numbers 1..6.")
        return self

    def opensees_args(self, ndm: int) -> list[object]:
        args: list[object] = ["-mat", *self.material_ids, "-dir", *self.dirs]
        if self.orient is not None:
            args += ["-orient", *(self.orient if ndm == 3 else self.orient[:3])]
        if self.do_rayleigh:
            args.append("-doRayleigh")
        if self.mass:
            args += ["-mass", self.mass]
        return args


class TripleFrictionPendulumElement(Entity):
    """``TripleFrictionPendulum`` (3D): the triple friction pendulum isolator."""

    type: Literal["TripleFrictionPendulum"] = "TripleFrictionPendulum"
    nodes: tuple[PositiveInt, PositiveInt]
    friction_model_ids: tuple[PositiveInt, PositiveInt, PositiveInt] = Field(
        ..., description="Friction models of surfaces 1 (inner), 2 and 3 (outer)."
    )
    vertical_material_id: PositiveInt = Field(..., description="Vertical (axial) material.")
    rot_z_material_id: PositiveInt = Field(..., description="Torsion material.")
    rot_x_material_id: PositiveInt = Field(..., description="Rotation about X material.")
    rot_y_material_id: PositiveInt = Field(..., description="Rotation about Y material.")
    L1: PositiveFloat = Field(..., description="Effective radius, surface 1")
    L2: PositiveFloat = Field(..., description="Effective radius, surface 2")
    L3: PositiveFloat = Field(..., description="Effective radius, surface 3")
    d1: PositiveFloat = Field(..., description="Displacement limit, surface 1")
    d2: PositiveFloat = Field(..., description="Displacement limit, surface 2")
    d3: PositiveFloat = Field(..., description="Displacement limit, surface 3")
    W: PositiveFloat = Field(..., description="Axial force for the initial friction")
    uy: PositiveFloat = Field(0.001, description="Lateral displacement where sliding starts")
    kvt: PositiveFloat = Field(1e10, description="Tension stiffness of the vertical direction")
    min_fv: float = Field(0.1, ge=0.0, description="Minimum vertical compression")
    tol: PositiveFloat = Field(1e-5, description="Convergence tolerance")

    @property
    def material_reference_ids(self) -> tuple[int, ...]:
        return (
            self.vertical_material_id,
            self.rot_z_material_id,
            self.rot_x_material_id,
            self.rot_y_material_id,
        )

    def opensees_args(self) -> list[object]:
        return [
            *self.friction_model_ids,
            *self.material_reference_ids,
            self.L1,
            self.L2,
            self.L3,
            self.d1,
            self.d2,
            self.d3,
            self.W,
            self.uy,
            self.kvt,
            self.min_fv,
            self.tol,
        ]
