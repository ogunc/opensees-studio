"""core.sections.cold_formed: AISI profiles by the linear method, checked by hand."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core import Project, UnitSystem
from opensees_studio.core.cold_formed_sections import (
    cold_formed_section,
    default_cold_formed_material,
    in_units,
)
from opensees_studio.core.default_materials import default_materials
from opensees_studio.core.section_outline import hint_regions
from opensees_studio.core.sections import ElasticSection
from opensees_studio.core.sections.cold_formed import (
    ColdFormedShape,
    designations,
    properties,
)
from opensees_studio.core.sections.geometry import section_properties

H, B, T = 10.0, 3.0, 0.1  # midline web height and flange width of a plain channel


def _channel() -> ColdFormedShape:
    # Out-to-out: depth H + T, flange B + T/2 from the web's outer face.
    return ColdFormedShape(profile="CU", d=H + T, bf=B + T / 2, t=T, r=0.0)


def test_a_sharp_plain_channel_matches_the_closed_forms() -> None:
    p = properties(_channel())
    web = T / 2  # the web's midline
    assert pytest.approx(T * (H + 2 * B)) == p.A
    assert p.Ix == pytest.approx(T * H**3 / 12 + 2 * B * T * (H / 2) ** 2)
    assert p.xc - web == pytest.approx(B**2 / (H + 2 * B))
    # Shear centre on the far side of the web: e = 3 B² / (6 B + H).
    assert p.xs - web == pytest.approx(-3 * B**2 / (6 * B + H))
    assert p.ys == pytest.approx(0.0, abs=1e-12)
    assert p.Cw == pytest.approx(T * B**3 * H**2 / 12 * (3 * B + 2 * H) / (6 * B + H))
    assert pytest.approx((H + 2 * B) * T**3 / 3) == p.J
    assert p.Ixy == pytest.approx(0.0, abs=1e-12)


def test_a_zee_has_a_product_of_inertia_and_its_shear_centre_at_the_centroid() -> None:
    z = ColdFormedShape(profile="ZS", d=8, bf=2.5, t=0.07, r=0.1875, lip=0.91, lip_angle=50)
    p = properties(z)
    assert p.Ixy > 0.0  # point-symmetric: inclined principal axes
    assert p.xs == pytest.approx(p.xc, abs=1e-9)
    assert p.ys == pytest.approx(p.yc, abs=1e-9)


def test_bends_round_the_corners_and_the_outline_agrees() -> None:
    sharp = ColdFormedShape(profile="CS", d=8, bf=2.5, t=0.07, r=0.0, lip=0.773)
    bent = sharp.model_copy(update={"r": 0.1875})
    assert properties(bent).A < properties(sharp).A  # an arc is shorter than its corner
    for shape in (bent, ColdFormedShape(profile="HU", d=3, bf=2, t=0.07, r=0.1875, b2=1.25)):
        drawn = section_properties(hint_regions(shape, 2), plastic=False)
        assert pytest.approx(properties(shape).A, rel=2e-3) == drawn.A


def test_dimensions_that_cannot_be_bent_are_refused() -> None:
    with pytest.raises(ValueError, match="lip"):
        ColdFormedShape(profile="CS", d=8, bf=2.5, t=0.07, r=0.1875, lip=0.2)
    with pytest.raises(ValueError, match="depth"):
        ColdFormedShape(profile="CU", d=0.3, bf=2.5, t=0.07, r=0.1875)


def test_the_generated_sizes_are_named_the_aisi_way() -> None:
    sizes = {s.designation: s for s in designations()}
    c = sizes["8CS2.5x070"]
    assert (c.d, c.bf, c.t, c.r) == (8.0, 2.5, 0.07, 0.1875)
    assert c.lip == 0.75  # 0.3 bf, to 1/8 in
    assert sizes["8ZS2.5x070"].lip_angle == 50.0
    assert {s.profile for s in sizes.values()} == {"CS", "CU", "ZS", "HU", "LU"}
    assert len(sizes) == len(designations())  # no two sizes share a name


def test_the_section_is_a653_with_the_profile_shear_areas_and_orientation() -> None:
    project = Project(ndm=2, ndf=3)
    project.meta.units = UnitSystem.SI_MM_N
    project.materials.extend(default_materials(1, project.meta.units))
    size = next(s for s in designations() if s.designation == "8CS2.5x070")
    shape = in_units(size, project.meta.units)
    assert shape.d == pytest.approx(203.2)  # mm

    material = default_cold_formed_material(project)
    assert material.name == "A653SSGr50"
    p = properties(shape)
    two_d = cold_formed_section(
        shape,
        section_id=4,
        ndm=2,
        name=size.designation,
        material=material,
        units=project.meta.units,
    )
    assert isinstance(two_d, ElasticSection)
    assert two_d.name == "8CS2.5x070"
    unnamed = cold_formed_section(shape, section_id=5, ndm=2, units=project.meta.units)
    assert unnamed.name == "CS 203.2x63.5x1.78"  # its dimensions, in mm
    assert (two_d.A, two_d.Iz, two_d.Iy, two_d.J) == pytest.approx((p.A, p.Ix, p.Iy, p.J))
    assert two_d.As2 == pytest.approx(shape.d * shape.t)  # the web
    assert two_d.As3 == pytest.approx(5 / 6 * 2 * shape.bf * shape.t)
    assert pytest.approx(material.E) == two_d.E
    assert two_d.material_id == material.id
    three_d = cold_formed_section(
        shape, section_id=4, ndm=3, material=material, units=project.meta.units
    )
    assert (three_d.Iz, three_d.Iy) == pytest.approx((p.Iy, p.Ix))
    assert (three_d.As2, three_d.As3) == pytest.approx((two_d.As3, two_d.As2))


def test_the_profile_survives_a_save() -> None:
    shape = ColdFormedShape(profile="ZS", d=8, bf=2.5, t=0.07, r=0.1875, lip=0.91, lip_angle=50)
    section = cold_formed_section(
        shape, section_id=1, ndm=3, elastic_modulus=2e5, shear_modulus=8e4
    )
    assert ElasticSection.model_validate(section.model_dump()) == section
    assert math.isclose(section.shape.lip_angle, 50.0)  # type: ignore[union-attr]


def test_a_lipped_c_agrees_with_the_aisi_manual() -> None:
    # 9CS2.5x059 (R = 0.1875 in) in the AISI Cold-Formed Steel Design Manual,
    # Table I-1 and I-2: A 0.881 in², Ix 10.3 in⁴, Iy 0.698 in⁴, J 0.00102 in⁴,
    # Cw 11.1 in⁶, xo -1.65 in, j 4.85 in, ro 3.90 in.
    p = properties(ColdFormedShape(profile="CS", d=9, bf=2.5, t=0.059, r=0.1875, lip=0.773))
    assert pytest.approx(0.881, rel=5e-3) == p.A
    assert p.Ix == pytest.approx(10.3, rel=5e-3)
    assert p.Iy == pytest.approx(0.698, rel=5e-3)
    assert pytest.approx(0.00102, rel=5e-3) == p.J
    assert p.Cw == pytest.approx(11.1, rel=5e-3)
    assert p.x0 == pytest.approx(-1.65, rel=5e-3)
    assert p.jy == pytest.approx(4.85, rel=5e-3)
    assert p.ro == pytest.approx(3.90, rel=5e-3)
    assert p.jx == pytest.approx(0.0, abs=1e-9)


def test_monosymmetry_of_a_sharp_plain_channel_matches_the_closed_form() -> None:
    p = properties(_channel())
    a = T / 2 - p.xc  # the web, about the centroid
    b = a + B  # the flange tips
    # ∫x³ dA + ∫x y² dA: the web (at x = a) and two flanges (y = ±H/2, x from a to b).
    web = T * H * a**3 + T * a * H**3 / 12
    flanges = 2 * T * ((b**4 - a**4) / 4 + (H / 2) ** 2 * (b**2 - a**2) / 2)
    assert p.jy == pytest.approx((web + flanges) / (2 * p.Iy) - p.x0)


def test_principal_axes_of_a_zee() -> None:
    z = properties(
        ColdFormedShape(profile="ZS", d=8, bf=2.5, t=0.07, r=0.1875, lip=0.91, lip_angle=50)
    )
    theta = z.principal_angle
    c, s = math.cos(theta), math.sin(theta)
    i1 = z.Ix * c * c + z.Iy * s * s - 2 * z.Ixy * s * c
    i12 = (z.Ix - z.Iy) * s * c + z.Ixy * (c * c - s * s)
    assert i1 == pytest.approx(z.I1)
    assert i12 == pytest.approx(0.0, abs=1e-9)
    assert pytest.approx(z.Ix + z.Iy) == z.I1 + z.I2
    assert z.I1 > z.Ix > z.Iy > z.I2
