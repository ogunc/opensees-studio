"""The AISC v16 shape table: consistency, independent checks, and conversion.

The table is generated from `steelpy` (see `data/README.md`), so a test that
only compared it with itself would prove nothing. These do three things
instead:

- check every row's internal consistency (radius of gyration against area and
  inertia, section modulus against depth, plastic modulus against elastic);
- recompute one whole family from first principles — round HSS, where the
  closed form and AISC's design-wall-thickness rule give the published values
  to within their rounding;
- pin a handful of values and the unit conversion, so a regeneration that
  changes them fails loudly.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from opensees_studio.core.aisc import (
    FAMILY_LABELS,
    SOURCE_UNITS,
    AISCShape,
    converted_geometry,
    families,
    get_shape,
    load_shapes,
    shape_hint,
    shape_to_elastic_section,
    shape_to_fiber_section,
    shapes_of,
)
from opensees_studio.core.sections import AngleShape, PipeShape, RectShape
from opensees_studio.core.units import UnitSystem, length_scale

#: AISC publishes three significant figures. A radius of gyration recomputed
#: from two rounded values compounds their rounding, and the worst row in the
#: table (Pipe10STD: ry 3.68 published, 3.624 recomputed) is 1.5% out, so the
#: tolerance is 2% — tight enough that a wrong value could not hide, loose
#: enough for the published precision. The closed-form family check below is
#: what actually pins the numbers.
ROUNDING = 0.02


# ─────────────────────── the table ───────────────────────
def test_the_table_is_complete_and_typed() -> None:
    shapes = load_shapes()

    assert len(shapes) >= 1600
    for family in ("W", "HP", "M", "S", "C", "MC", "WT", "MT", "ST", "L", "PIPE", "HSS", "HSS_R"):
        assert family in families(), family
        assert shapes_of(family), family


def test_every_family_has_a_label() -> None:
    assert set(families()) <= set(FAMILY_LABELS)


@pytest.mark.parametrize("name", ["W14X90", "W24X76", "C10X20", "L4X4X1_4", "Pipe8STD"])
def test_published_values_are_pinned(name: str) -> None:
    """A regression guard, not the verification.

    These are the values the vendored table carries today. The verification is
    elsewhere in this module (the closed-form recomputation of a whole family,
    the consistency of every row) and in `data/README.md`, which records the
    cross-check against an independent AISC dataset: 303 W/M/S/HP shapes agree
    on Ix to within 1%, and 248 of them on the area to within its published
    0.1 in² rounding.
    """
    shape = get_shape(name)
    expected = {
        "W14X90": (26.5, 999.0, 362.0, 4.06),
        "W24X76": (22.4, 2100.0, 82.5, 2.68),
        "C10X20": (5.87, 78.9, 2.80, 0.368),
        "L4X4X1_4": (1.93, 3.00, 3.00, 0.0438),
        "Pipe8STD": (7.85, 68.1, 68.1, 136.0),
    }[name]
    assert (shape.area, shape.ix, shape.iy, shape.j) == expected


# ─────────────────────── internal consistency ───────────────────────
def test_every_radius_of_gyration_matches_its_area_and_inertia() -> None:
    """r = sqrt(I/A), on all 1660 rows."""
    checked = 0
    for shape in load_shapes().values():
        assert shape.rx is not None and shape.area > 0, shape.name
        assert math.sqrt(shape.ix / shape.area) == pytest.approx(shape.rx, rel=ROUNDING), shape.name
        if shape.iy is not None and shape.ry is not None:
            assert math.sqrt(shape.iy / shape.area) == pytest.approx(shape.ry, rel=ROUNDING), (
                shape.name
            )
        checked += 1
    assert checked >= 1600


def test_a_plastic_modulus_is_never_below_the_elastic_one() -> None:
    for shape in load_shapes().values():
        if shape.zx is not None and shape.sx is not None:
            assert shape.zx >= shape.sx - 1e-9, shape.name
        if shape.zy is not None and shape.sy is not None:
            assert shape.zy >= shape.sy - 1e-9, shape.name


def test_round_tube_properties_follow_the_design_wall_thickness() -> None:
    """An independent recomputation of a whole family.

    AISC computes round HSS properties with the design wall thickness
    ``0.93 t_nom``. Recomputing A, I and J that way has to land on the
    published values to within their three-significant-figure rounding; if the
    table were transcribed wrongly, or the convention were different, this is
    where it would show.
    """
    for shape in shapes_of("HSS_R"):
        assert shape.od and shape.tnom
        t = 0.93 * shape.tnom
        inner = shape.od - 2.0 * t
        area = math.pi / 4.0 * (shape.od**2 - inner**2)
        inertia = math.pi / 64.0 * (shape.od**4 - inner**4)
        assert area == pytest.approx(shape.area, rel=ROUNDING), shape.name
        assert inertia == pytest.approx(shape.ix, rel=ROUNDING), shape.name
        assert 2.0 * inertia == pytest.approx(shape.j, rel=ROUNDING), shape.name


def test_ishape_families_carry_their_geometry() -> None:
    """The fibre route needs d, bf, tf, tw; the table must supply them."""
    for family in ("W", "HP", "M", "S", "C", "MC", "WT", "MT", "ST"):
        for shape in shapes_of(family):
            assert shape.has_ishape_geometry, f"{shape.name} is missing flange/web geometry"
            assert shape.d and shape.d > 2.0 * (shape.tf or 0.0), shape.name


# ─────────────────────── lookup and hints ───────────────────────
def test_an_unknown_shape_suggests_near_misses() -> None:
    with pytest.raises(KeyError, match="not an AISC v16 shape"):
        get_shape("W14X999")
    with pytest.raises(KeyError, match="W14X90"):
        get_shape("W14X9")


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("Pipe8STD", "pipe"),
        ("HSS10_000X0_500", "pipe"),
        ("HSS10X10X1_2", "rect"),
        ("L4X4X1_4", "angle"),
    ],
)
def test_a_truthful_hint_is_attached_where_one_exists(name: str, kind: str) -> None:
    shape = get_shape(name)

    hint = shape_hint(shape)

    assert hint is not None and hint.kind == kind


def test_an_ishape_gets_no_rectangle_hint() -> None:
    """Drawing a wide flange as a solid rectangle would misrepresent it."""
    assert shape_hint(get_shape("W14X90")) is None
    assert isinstance(shape_hint(get_shape("HSS10X10X1_2")), RectShape)
    assert isinstance(shape_hint(get_shape("Pipe8STD")), PipeShape)
    assert isinstance(shape_hint(get_shape("L4X4X1_4")), AngleShape)


# ─────────────────────── conversion ───────────────────────
def test_us_units_are_inserted_exactly_as_published() -> None:
    shape = get_shape("W14X90")

    section = shape_to_elastic_section(shape, elastic_modulus=29000.0, units=UnitSystem.US_IN_KIP)

    assert shape.area == section.A
    assert section.Iz == shape.ix
    assert section.Iy == shape.iy
    assert shape.j == section.J
    assert section.name == "W14X90"


@pytest.mark.parametrize(
    ("units", "length"),
    [
        (UnitSystem.SI_M_N, 0.0254),
        (UnitSystem.SI_MM_N, 25.4),
        (UnitSystem.US_FT_KIP, 1.0 / 12.0),
    ],
)
def test_the_geometry_is_scaled_to_the_project_units(units: UnitSystem, length: float) -> None:
    shape = get_shape("W14X90")

    section = shape_to_elastic_section(shape, elastic_modulus=200e9, units=units)

    # The factor is the documented one, not a fitted number.
    assert length == pytest.approx(length_scale(SOURCE_UNITS, units), rel=1e-12)
    assert pytest.approx(shape.area * length**2, rel=1e-12) == section.A
    assert section.Iz == pytest.approx(shape.ix * length**4, rel=1e-12)
    assert pytest.approx(shape.j * length**4, rel=1e-12) == section.J


def test_the_dialog_preview_matches_what_is_inserted() -> None:
    shape = get_shape("W24X76")
    preview = converted_geometry(shape, UnitSystem.SI_M_N)
    section = shape_to_elastic_section(shape, elastic_modulus=1.0, units=UnitSystem.SI_M_N)

    assert preview["A"] == section.A
    assert preview["Iz"] == section.Iz
    assert preview["Iy"] == section.Iy


def test_material_properties_are_the_callers_choice() -> None:
    """The library carries geometry; E and G come from the material."""
    section = shape_to_elastic_section(
        get_shape("W14X90"), elastic_modulus=123.0, shear_modulus=45.0
    )

    assert section.E == 123.0
    assert section.G == 45.0


# ─────────────────────── fibre route ───────────────────────
def test_an_ishape_can_become_a_fibre_section() -> None:
    section = shape_to_fiber_section(get_shape("W14X90"), material_id=2, n_web=8, n_flange=3)

    assert len(section.patches) == 3  # top flange, web, bottom flange
    assert {patch.material_id for patch in section.patches} == {2}


def test_a_tube_cannot_become_a_flange_web_fibre_section() -> None:
    with pytest.raises(ValueError, match="flange-and-web geometry"):
        shape_to_fiber_section(get_shape("Pipe8STD"), material_id=1)


def test_the_fibre_geometry_reproduces_the_shape_close_to_the_table() -> None:
    """The patches ignore the fillets, which is exactly the difference to expect."""
    shape = get_shape("W14X90")
    patches = shape_to_fiber_section(shape, material_id=1).patches
    # A patch spans y (the depth direction) and z (the width): the strong-axis
    # inertia is about z, so it integrates y².
    area = sum((p.y_j - p.y_i) * (p.z_j - p.z_i) for p in patches)
    inertia = sum(
        (p.z_j - p.z_i) * (p.y_j - p.y_i) ** 3 / 12.0
        + (p.z_j - p.z_i) * (p.y_j - p.y_i) * ((p.y_i + p.y_j) / 2.0) ** 2
        for p in patches
    )

    assert area == pytest.approx(shape.area, rel=0.02)
    assert inertia == pytest.approx(shape.ix, rel=0.02)
    assert inertia < shape.ix  # fillets, ignored here, add a little


def test_the_shape_model_is_frozen() -> None:
    """Rows are shared: nothing may mutate a cached shape."""
    shape: AISCShape = get_shape("W14X90")
    with pytest.raises(ValidationError):
        shape.area = 1.0  # type: ignore[misc]
