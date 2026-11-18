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
from opensees_studio.core.design.base_plate import BasePlateDesign
from opensees_studio.core.design.built_up_model import BuiltUpShape
from opensees_studio.core.design.shear_tab_model import ShearTabDesign

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

SeismicSystem = Literal["none", "R3", "OMF", "IMF", "SMF", "OCBF", "SCBF", "EBF", "BRBF"]
"""Lateral system of a direction: ``none`` (wind or gravity only), ``R3`` (a
steel system not specifically detailed for seismic resistance, ASCE 7 Table
12.2-1 H) or an AISC 341-22 system."""

SEISMIC_SYSTEM_LABELS: dict[str, str] = {
    "none": "None (no seismic design)",
    "R3": "Steel system not detailed for seismic (R = 3)",
    "OMF": "Ordinary moment frame (OMF)",
    "IMF": "Intermediate moment frame (IMF)",
    "SMF": "Special moment frame (SMF)",
    "OCBF": "Ordinary concentrically braced frame (OCBF)",
    "SCBF": "Special concentrically braced frame (SCBF)",
    "EBF": "Eccentrically braced frame (EBF)",
    "BRBF": "Buckling-restrained braced frame (BRBF)",
}

SYSTEM_COEFFICIENTS: dict[str, tuple[float, float, float]] = {
    "R3": (3.0, 3.0, 3.0),
    "OMF": (3.5, 3.0, 3.0),
    "IMF": (4.5, 3.0, 4.0),
    "SMF": (8.0, 3.0, 5.5),
    "OCBF": (3.25, 2.0, 3.25),
    "SCBF": (6.0, 2.0, 5.0),
    "EBF": (8.0, 2.0, 4.0),
    "BRBF": (8.0, 2.5, 5.0),
}
"""ASCE 7-22 Table 12.2-1, steel systems: ``(R, Omega0, Cd)``. EBF and BRBF are
the versions with moment-resisting beam-column connections."""

CHECKED_SEISMIC_SYSTEMS = frozenset({"none", "SMF", "IMF", "SCBF", "OCBF"})
"""Systems whose AISC 341 provisions the member check applies; the others are
checked against AISC 360 only, with a note."""

StabilityMethod = Literal["unset", "direct", "effective_length", "first_order"]
"""AISC 360 design for stability: Chapter C direct analysis method, Appendix 7
effective length or first-order method. ``unset`` keeps the check as it was
before the method was chosen (the K factors and the B1 switch as given)."""

STABILITY_METHOD_LABELS: dict[str, str] = {
    "unset": "Not chosen (K factors and B1 as entered)",
    "direct": "Direct Analysis Method (Chapter C)",
    "effective_length": "Effective Length Method (Appendix 7.2)",
    "first_order": "First-Order Analysis Method (Appendix 7.3)",
}


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
        "net_area",
        "shear_lag",
        "grade",
        "role",
    )

    element_id: PositiveInt
    role: Literal["column", "beam", "brace"] | None = Field(
        default=None,
        description="Member role for the design checks; None = from the member's direction.",
    )
    shape: str | None = Field(
        default=None,
        description="AISC shape name to design with; None takes the section's name.",
    )
    grade: str | None = Field(
        default=None,
        description="Steel grade key (core.design.steel_grades); None = the family's grade.",
    )
    k_major: PositiveFloat = Field(default=1.0, description="Effective length factor, major axis.")
    k_minor: PositiveFloat = Field(default=1.0, description="Effective length factor, minor axis.")
    length_major: PositiveFloat | None = Field(
        default=None,
        description=(
            "Unbraced length for major-axis buckling; None = between the bracing points "
            "of the physical member (core.design.members)."
        ),
    )
    length_minor: PositiveFloat | None = Field(
        default=None,
        description="Unbraced length for minor-axis buckling; None = between the bracing points.",
    )
    length_ltb: PositiveFloat | None = Field(
        default=None,
        description=(
            "Unbraced length of the compression flange (LTB); None = between the lateral "
            "bracing points."
        ),
    )
    cb: PositiveFloat | None = Field(
        default=None, description="Moment gradient factor; None = from the moment diagram (F1-1)."
    )
    net_area: PositiveFloat | None = Field(
        default=None,
        description="Net area for D2-2 tension rupture; None leaves rupture unchecked.",
    )
    shear_lag: float = Field(
        default=1.0,
        gt=0.0,
        le=1.0,
        description="Shear-lag factor U for D2-2 (1.0 for a fully effective connection).",
    )


class DesignLoadSet(BaseModel):
    """One analysis case or load combination the check envelopes."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    source: Literal["case", "combination"]
    ref_id: PositiveInt


class ConcreteDesign(BaseModel):
    """ACI 318-19 settings of Design → Concrete Frame Check (project units)."""

    model_config = ConfigDict(extra="forbid")

    stirrup_area: PositiveFloat | None = Field(
        default=None, description="Av of one stirrup set; None = two 10 mm legs (157 mm²)."
    )
    stirrup_spacing: PositiveFloat | None = Field(
        default=None, description="Stirrup spacing s; None = 150 mm."
    )
    fyt: PositiveFloat | None = Field(
        default=None, description="Yield stress of the stirrups; None = 420 MPa."
    )
    lam: float = Field(default=1.0, gt=0.0, le=1.0, description="Lightweight factor λ.")
    transverse: Literal["tied", "spiral"] = "tied"


class DesignSettings(BaseModel):
    """Steel frame check and storey drift check settings of a project."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    serialize_without_defaults = omit_when_default(
        "method",
        "fy",
        "fu",
        "ratio_limit",
        "p_delta",
        "seismic_system",
        "ry",
        "load_sets",
        "members",
        "drift_limit",
        "drift_amplification",
        "concrete",
        "stability_method",
        "seismic_system_y",
        "sds",
        "steel_grades",
        "base_plates",
        "shear_tabs",
        "built_up",
    )

    code: Literal["AISC 360-16"] = "AISC 360-16"
    stability_method: StabilityMethod = Field(
        default="unset",
        description=(
            "AISC 360 design for stability. 'direct' checks every member with K = 1 "
            "and B1 for P-delta, over the direct analysis cases when they exist."
        ),
    )
    steel_grades: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Shape family → steel grade key (core.design.steel_grades). A family "
            "without one takes fy / fu below."
        ),
    )
    concrete: ConcreteDesign | None = Field(
        default=None, description="ACI 318-19 settings of the concrete frame check."
    )
    method: Literal["LRFD", "ASD"] = "LRFD"
    fy: PositiveFloat | None = Field(
        default=None,
        description="Yield stress in project units; None = 50 ksi (345 MPa) in those units.",
    )
    fu: PositiveFloat | None = Field(
        default=None,
        description="Ultimate stress in project units; None = 65 ksi (450 MPa) in those units.",
    )
    ratio_limit: PositiveFloat = Field(
        default=1.0, description="Demand/capacity ratio above which a member fails."
    )
    p_delta: bool = Field(
        default=False,
        description=(
            "Amplify the moments of members in compression by B1 (AISC 360-16 "
            "C2.1b) when the analysis captures P-Delta but not member curvature."
        ),
    )
    seismic_system: SeismicSystem = Field(
        default="none",
        description=(
            "Lateral system along X (and Y while seismic_system_y is None). An AISC "
            "341-22 system the check covers adds its Table D1.1 width-to-thickness "
            "and capacity design checks; none leaves the AISC 360 check alone."
        ),
    )
    seismic_system_y: SeismicSystem | None = Field(
        default=None, description="Lateral system along Y; None = the same as X."
    )
    sds: PositiveFloat | None = Field(
        default=None,
        description=(
            "Design short-period spectral acceleration SDS (g) of the overstrength "
            "combinations; None = 1.0."
        ),
    )
    ry: PositiveFloat = Field(
        default=1.1,
        description="Ratio of expected to specified yield stress Ry (AISC 341).",
    )
    load_sets: list[DesignLoadSet] = Field(
        default_factory=list,
        description="Cases and combinations to envelope; empty = every combination, "
        "or every static case when there is none.",
    )
    members: list[SteelMemberDesign] = Field(default_factory=list)
    base_plates: list[BasePlateDesign] = Field(
        default_factory=list,
        description="Base plate and anchor rods of each column base (Design → Base Plates).",
    )
    shear_tabs: list[ShearTabDesign] = Field(
        default_factory=list,
        description="Shear tab of each simple beam end (Design → Connections by Joint).",
    )
    built_up: list[BuiltUpShape] = Field(
        default_factory=list,
        description=(
            "Welded I-shapes defined from their plates (Design → Built-Up Shapes); a "
            "section or member override naming one is checked with its properties."
        ),
    )

    def built_up_by_name(self) -> dict[str, BuiltUpShape]:
        """Built-up shapes by upper-case name (names are matched case-blind)."""
        return {shape.name.strip().upper(): shape for shape in self.built_up}

    drift_limit: PositiveFloat = Field(
        default=0.020, description="Allowable storey drift ratio (drift / storey height)."
    )
    drift_amplification: PositiveFloat = Field(
        default=1.0,
        description="Factor on the computed drift before the limit, e.g. Cd / Ie (ASCE 7).",
    )

    def omega0(self) -> float | None:
        """Overstrength factor of the seismic systems (the larger of X and Y), None without one."""
        systems = {self.seismic_system, self.seismic_system_y or self.seismic_system}
        values = [SYSTEM_COEFFICIENTS[s][1] for s in systems if s in SYSTEM_COEFFICIENTS]
        return max(values) if values else None

    def member(self, element_id: int) -> SteelMemberDesign:
        """The overrides of ``element_id``, all defaults when it has none."""
        for member in self.members:
            if member.element_id == element_id:
                return member
        return SteelMemberDesign(element_id=element_id)
