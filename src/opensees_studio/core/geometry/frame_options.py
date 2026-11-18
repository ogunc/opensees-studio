"""Frame member assignments: end releases, end offsets, insertion point, modifiers.

These are the SAP2000 *Assign → Frame* options. Each lives on a frame element
(``FRAME_ELEMENT_CLASSES``) as one field that is left out of the saved file
while it holds its default, so a project that uses none of them saves
byte-identical to before.

Axis names follow the rest of the application: local 1 is the member axis
(OpenSees local x, end i to end j), local 2 is OpenSees local y and local 3 is
OpenSees local z. ``M3`` is the moment about local 3 (local z), the in-plane
moment of a 2D frame; ``M2`` the moment about local 2; ``T`` the torsion.

How the runner realises them in OpenSees is described in
``services/frame_members.py``; the geometry they imply (rigid zones, joint
offsets, clear length) is computed in :mod:`opensees_studio.core.frame_members`.
"""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ReleaseDof = Literal["T", "M2", "M3"]
"""A member-end action that can be released: torsion or one of the two bending moments."""

RELEASE_DOFS: tuple[str, ...] = get_args(ReleaseDof)

#: Release DOF → index of the matching rotation in the member's local axes (x, y, z).
RELEASE_AXIS: dict[str, int] = {"T": 0, "M2": 1, "M3": 2}


#: Per-class field dict of a default instance, built once. pydantic v2 keeps a
#: model's fields in ``__dict__``, so ``self.__dict__ == defaults`` is a dict
#: comparison in C: constructing a throwaway model and comparing it with ``==``
#: ran validation twice per call, and the renderer asks once per member per
#: category (27k calls on a 13.6k-member model).
_DEFAULTS: dict[type, dict[str, Any]] = {}


def _default_values(cls: type) -> dict[str, Any]:
    """The field dict of a default ``cls``, computed at most once per class."""
    cached = _DEFAULTS.get(cls)
    if cached is None:
        cached = cls().__dict__
        _DEFAULTS[cls] = cached
    return cached


class _Options(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    def is_default(self) -> bool:
        """Every field holds its default: the member behaves as if it was never assigned."""
        return self.__dict__ == _default_values(type(self))


class EndRelease(BaseModel):
    """What is released at one end of a member, with optional partial-fixity springs.

    A released action carries no force at that end. A spring turns the release
    into partial fixity: the end then transfers ``k * relative rotation``
    (force × length per radian), the SAP2000 "partial fixity" value.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    released: tuple[ReleaseDof, ...] = Field(
        default=(), description="Released actions at this end (T, M2, M3)."
    )
    springs: dict[ReleaseDof, float] = Field(
        default_factory=dict,
        description=(
            "Partial-fixity stiffness per released action (moment per radian). "
            "Only released actions may carry one; leave an action out for a full release."
        ),
    )

    @field_validator("released")
    @classmethod
    def _canonical_order(cls, released: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(released)) != len(released):
            raise ValueError(f"A release is listed twice: {released}.")
        return tuple(sorted(released, key=RELEASE_DOFS.index))

    @model_validator(mode="after")
    def _check(self) -> EndRelease:
        for dof, k in self.springs.items():
            if dof not in self.released:
                raise ValueError(
                    f"A partial-fixity spring on {dof} needs {dof} to be released at that end."
                )
            if not k > 0.0:
                raise ValueError(f"The {dof} partial-fixity stiffness must be positive, not {k}.")
        return self

    def spring(self, dof: str) -> float:
        """Partial-fixity stiffness of ``dof``, 0 for a full release or a fixed action."""
        return float(self.springs.get(dof, 0.0))  # type: ignore[call-overload]


class FrameReleases(_Options):
    """End releases of a frame member (SAP2000 *Assign → Frame → Releases/Partial Fixity*)."""

    i: EndRelease = Field(default_factory=EndRelease, description="Releases at end i.")
    j: EndRelease = Field(default_factory=EndRelease, description="Releases at end j.")

    @model_validator(mode="after")
    def _stable(self) -> FrameReleases:
        both = "T" in self.i.released and "T" in self.j.released
        if both and not (self.i.spring("T") or self.j.spring("T")):
            raise ValueError(
                "Torsion released at both ends leaves the member free to spin about its "
                "own axis. Keep torsion at one end or give one end a torsion spring."
            )
        return self

    def end(self, which: str) -> EndRelease:
        """The release of end ``"i"`` or ``"j"``."""
        return self.i if which == "i" else self.j

    @property
    def any(self) -> bool:
        """Something is released at either end."""
        return bool(self.i.released or self.j.released)


class FrameEndOffsets(_Options):
    """Rigid end zones (SAP2000 *Assign → Frame → End (Length) Offsets*).

    ``length_i`` / ``length_j`` are the offset lengths measured along the
    member from each joint, typically half the depth of the member framing
    into that joint. ``rigid_factor`` is the part of each offset that is
    rigid: the member's flexible length is
    ``L - rigid_factor * (length_i + length_j)`` and its end forces are
    reported at the ends of that flexible length.
    """

    length_i: float = Field(default=0.0, ge=0.0, description="Offset length at end i.")
    length_j: float = Field(default=0.0, ge=0.0, description="Offset length at end j.")
    rigid_factor: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Rigid-zone factor, 0 (flexible) to 1 (rigid)."
    )

    @property
    def rigid_i(self) -> float:
        return self.rigid_factor * self.length_i

    @property
    def rigid_j(self) -> float:
        return self.rigid_factor * self.length_j


CardinalPoint = Literal[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

CARDINAL_POINT_NAMES: dict[int, str] = {
    1: "Bottom left",
    2: "Bottom center",
    3: "Bottom right",
    4: "Middle left",
    5: "Middle center",
    6: "Middle right",
    7: "Top left",
    8: "Top center",
    9: "Top right",
    10: "Centroid",
    11: "Shear center",
}
"""SAP2000 cardinal point names. Bottom/top are -/+ local 2, left/right are -/+ local 3,
seen looking from end i towards end j."""


class FrameInsertion(_Options):
    """Insertion point (SAP2000 *Assign → Frame → Insertion Point*).

    The cardinal point is the point of the cross section that sits on the line
    between the two joints; ``offset_2`` / ``offset_3`` move the member further
    along local 2 / local 3 at both ends. Both are realised as rigid joint
    offsets, so the member's flexible length is unchanged. The shear center
    (11) is taken at the centroid: the sections here carry no shear-center data.
    """

    cardinal_point: CardinalPoint = Field(default=10, description="SAP2000 cardinal point 1-11.")
    offset_2: float = Field(default=0.0, description="Extra offset along local 2 (both ends).")
    offset_3: float = Field(default=0.0, description="Extra offset along local 3 (both ends).")


class FrameModifiers(_Options):
    """Property modifiers (SAP2000 *Assign → Frame → Property Modifiers*).

    Multipliers on the section properties the member uses, e.g. ``i33 = 0.35``
    for a cracked concrete beam. They apply to members with an elastic section
    (``ElasticSection``, and the elastic interior of a ``BeamWithHinges``); a
    fibre section has no property to scale and the run refuses stiffness
    modifiers on one. ``mass`` scales an elastic member's mass per length and
    ``weight`` its self weight.

    ``as2`` / ``as3`` scale the shear areas ``As2`` / ``As3`` of an elastic
    section. A multiplier of **0** turns shear deformation off for the member
    (it runs as Euler-Bernoulli, not ``ElasticTimoshenkoBeam``), as in
    SAP2000; any positive multiplier keeps the Timoshenko route. In 3D both
    shear areas must be positive for that route, because OpenSees' Timoshenko
    element takes both.
    """

    area: float = Field(default=1.0, gt=0.0, description="Cross-section area A.")
    as2: float = Field(
        default=1.0, ge=0.0, description="Shear area in the 2 direction (0 = no shear)."
    )
    as3: float = Field(
        default=1.0, ge=0.0, description="Shear area in the 3 direction (0 = no shear)."
    )
    torsion: float = Field(default=1.0, gt=0.0, description="Torsional constant J.")
    i22: float = Field(default=1.0, gt=0.0, description="Moment of inertia about local 2 (Iy).")
    i33: float = Field(default=1.0, gt=0.0, description="Moment of inertia about local 3 (Iz).")
    mass: float = Field(default=1.0, ge=0.0, description="Mass per unit length.")
    weight: float = Field(default=1.0, ge=0.0, description="Self weight.")

    @property
    def scales_stiffness(self) -> bool:
        """A stiffness property (A, J, I22, I33) is modified."""
        return any(v != 1.0 for v in (self.area, self.torsion, self.i22, self.i33))


FRAME_OPTION_FIELDS: tuple[str, ...] = ("releases", "end_offsets", "insertion", "modifiers")
"""Fields every frame element carries for the options above (left out of a dump at default)."""
