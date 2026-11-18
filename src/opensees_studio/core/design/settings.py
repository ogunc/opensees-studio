"""What a project saves about its design checks (Design → Steel Frame Check).

``Project.design`` is ``None`` until the user opens the check, so a project that
never used it saves byte-identical. Every field below is left out of the file
while it holds its default.

Member overrides are keyed by element id. An override whose element is gone is
ignored by the check rather than refused: deleting a member must not make the
project invalid.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

from opensees_studio.core._base import omit_when_default

#: ASCE 7-22 Table 12.12-1 and other common allowable storey drift ratios.
DRIFT_PRESETS: dict[str, tuple[float, float]] = {
    "ASCE 7-22, Risk Category I/II (0.020 h, Δ = Cd δe / Ie)": (0.020, 1.0),
    "ASCE 7-22, Risk Category III (0.015 h)": (0.015, 1.0),
    "ASCE 7-22, Risk Category IV (0.010 h)": (0.010, 1.0),
    "NCh433, centre of mass (0.002 h)": (0.002, 1.0),
    "Eurocode 8, brittle non-structural (0.005 h / ν)": (0.005, 1.0),
}
"""Label → (allowable drift ratio, default amplification). The amplification
multiplies the computed (elastic) drift: Cd / Ie for ASCE 7, 1 for a spectrum
that already gives design displacements."""


class SteelMemberDesign(BaseModel):
    """Design overrides of one frame element; every field defaults to "as modelled"."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    serialize_without_defaults = omit_when_default(
        "shape",
        "k_major",
        "k_minor",
        "length_major",
        "length_minor",
        "length_ltb",
        "cb",
    )

    element_id: PositiveInt
    shape: str | None = Field(
        default=None,
        description="AISC shape name to design with; None takes the section's name.",
    )
    k_major: PositiveFloat = Field(default=1.0, description="Effective length factor, major axis.")
    k_minor: PositiveFloat = Field(default=1.0, description="Effective length factor, minor axis.")
    length_major: PositiveFloat | None = Field(
        default=None, description="Unbraced length for major-axis buckling; None = member length."
    )
    length_minor: PositiveFloat | None = Field(
        default=None, description="Unbraced length for minor-axis buckling; None = member length."
    )
    length_ltb: PositiveFloat | None = Field(
        default=None,
        description="Unbraced length of the compression flange (LTB); None = member length.",
    )
    cb: PositiveFloat | None = Field(
        default=None, description="Moment gradient factor; None = from the moment diagram (F1-1)."
    )


class DesignLoadSet(BaseModel):
    """One analysis case or load combination the check envelopes."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    source: Literal["case", "combination"]
    ref_id: PositiveInt


class DesignSettings(BaseModel):
    """Steel frame check and storey drift check settings of a project."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    serialize_without_defaults = omit_when_default(
        "method",
        "fy",
        "ratio_limit",
        "load_sets",
        "members",
        "drift_limit",
        "drift_amplification",
    )

    code: Literal["AISC 360-16"] = "AISC 360-16"
    method: Literal["LRFD", "ASD"] = "LRFD"
    fy: PositiveFloat | None = Field(
        default=None,
        description="Yield stress in project units; None = 50 ksi (345 MPa) in those units.",
    )
    ratio_limit: PositiveFloat = Field(
        default=1.0, description="Demand/capacity ratio above which a member fails."
    )
    load_sets: list[DesignLoadSet] = Field(
        default_factory=list,
        description="Cases and combinations to envelope; empty = every combination, "
        "or every static case when there is none.",
    )
    members: list[SteelMemberDesign] = Field(default_factory=list)
    drift_limit: PositiveFloat = Field(
        default=0.020, description="Allowable storey drift ratio (drift / storey height)."
    )
    drift_amplification: PositiveFloat = Field(
        default=1.0,
        description="Factor on the computed drift before the limit, e.g. Cd / Ie (ASCE 7).",
    )

    def member(self, element_id: int) -> SteelMemberDesign:
        """The overrides of ``element_id``, all defaults when it has none."""
        for member in self.members:
            if member.element_id == element_id:
                return member
        return SteelMemberDesign(element_id=element_id)
