"""The saved AISC 360 Chapter J connection check (a leaf module: pydantic only)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

from opensees_studio.core._base import omit_when_default

ChapterJType = Literal[
    "fillet_weld",
    "bolt_shear",
    "bolt_tension",
    "bolt_bearing",
    "slip_critical",
    "plate_shear_yielding",
    "plate_shear_rupture",
    "block_shear",
    "bearing_strength",
    "concrete_bearing",
    "splice",
    "flange_local_bending",
    "web_local_yielding",
    "web_local_crippling",
    "web_sidesway_buckling",
    "web_compression_buckling",
]


class ChapterJCheck(BaseModel):
    """One user-defined AISC 360 Chapter J limit state."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    serialize_without_defaults = omit_when_default(
        "name",
        "fexx",
        "weld_leg",
        "weld_length",
        "weld_both_sides",
        "filler_thickness",
        "filler_transfers_force",
        "fn",
        "bolt_diameter",
        "bolt_count",
        "fu",
        "thickness",
        "edge_distance",
        "hole_diameter",
        "deformation",
        "mu",
        "tb",
        "slip_planes",
        "hole_type",
        "fy",
        "agv",
        "anv",
        "ant",
        "uniform_tension",
        "apb",
        "fc",
        "a1",
        "a2",
        "splice_nominal",
        "flange_thickness",
        "web_thickness",
        "flange_width",
        "clear_web_height",
        "member_depth",
        "fillet_k",
        "bearing_length",
        "distance_to_end",
        "elastic_modulus",
        "chord_factor",
        "required_moment",
        "section_modulus",
        "flange_restrained",
    )

    id: PositiveInt
    name: str = ""
    check_type: ChapterJType
    demand: PositiveFloat = Field(description="Required strength Vu or Tu.")
    # J2.4 fillet weld
    fexx: PositiveFloat | None = None
    weld_leg: PositiveFloat | None = None
    weld_length: PositiveFloat | None = None
    weld_both_sides: bool = True
    filler_thickness: PositiveFloat | None = None
    filler_transfers_force: bool = False
    # J3.1 / J3.6 bolts
    fn: PositiveFloat | None = Field(default=None, description="Nominal bolt stress Fnv or Fnt.")
    bolt_diameter: PositiveFloat | None = None
    bolt_count: PositiveInt | None = None
    fu: PositiveFloat | None = Field(
        default=None, description="Tensile strength of the connected material."
    )
    thickness: PositiveFloat | None = None
    edge_distance: PositiveFloat | None = Field(
        default=None, description="Bolt center to the material edge."
    )
    hole_diameter: PositiveFloat | None = None
    deformation: bool = Field(
        default=True, description="Deformation at the bolt hole is a design consideration."
    )
    # J3.4 slip-critical
    mu: PositiveFloat | None = Field(default=None, description="Slip coefficient.")
    tb: PositiveFloat | None = Field(default=None, description="Bolt pretension Tb.")
    slip_planes: PositiveInt | None = None
    hole_type: Literal["standard", "oversized", "long_slotted"] = "standard"
    # J4 plate and block shear
    fy: PositiveFloat | None = None
    agv: PositiveFloat | None = None
    anv: PositiveFloat | None = None
    ant: PositiveFloat | None = None
    uniform_tension: bool = True
    apb: PositiveFloat | None = Field(default=None, description="Projected bearing area for J7-1.")
    fc: PositiveFloat | None = Field(default=None, description="Concrete compressive strength f'c.")
    a1: PositiveFloat | None = Field(
        default=None, description="Steel area bearing on the concrete."
    )
    a2: PositiveFloat | None = Field(default=None, description="Concentric supporting area A2.")
    splice_nominal: PositiveFloat | None = Field(
        default=None, description="Nominal strength of the smaller spliced section."
    )
    # J10 concentrated forces
    flange_thickness: PositiveFloat | None = None
    web_thickness: PositiveFloat | None = None
    flange_width: PositiveFloat | None = None
    clear_web_height: PositiveFloat | None = None
    member_depth: PositiveFloat | None = None
    fillet_k: PositiveFloat | None = Field(
        default=None, description="Distance from the flange face to the web toe of the fillet."
    )
    bearing_length: PositiveFloat | None = Field(
        default=None,
        description=(
            "Length of bearing lb (J10.1-J10.3 and J10.5) or the unbraced "
            "length Lb of the compression flange (J10.4)."
        ),
    )
    distance_to_end: PositiveFloat | None = Field(
        default=None, description="Distance from the concentrated force to the member end."
    )
    elastic_modulus: PositiveFloat | None = None
    chord_factor: PositiveFloat = Field(default=1.0, description="Chord-stress interaction Qf.")
    required_moment: PositiveFloat | None = Field(
        default=None, description="Required flexural strength Mr at the force."
    )
    section_modulus: PositiveFloat | None = Field(
        default=None, description="Elastic section modulus Sx for My = Fy Sx."
    )
    flange_restrained: bool = Field(
        default=True, description="Compression flange restrained against rotation."
    )
