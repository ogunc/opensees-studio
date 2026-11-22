"""Steel deck slab properties and the layered shell that reproduces them."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core import ElasticOrthotropic, PlateFiberMaterial, UnitSystem
from opensees_studio.core.steel_deck import (
    DECK_PROFILES,
    DeckInput,
    build_deck_model,
    deck_layers,
    deck_outline,
    deck_properties,
    equivalent_thickness,
    layered_stiffness,
    profile_in_units,
)

EC, ES, NU = 25e9, 203e9, 0.2


def _deck(**change: object) -> DeckInput:
    values: dict[str, object] = {
        "rib_height": 0.0508,
        "pitch": 0.3048,
        "rib_bottom": 0.1143,
        "rib_top": 0.1778,
        "sheet_thickness": 0.00091,
        "topping": 0.065,
        "Ec": EC,
        "nu": NU,
        "rho_c": 2400.0,
        "Es": ES,
        "rho_s": 7850.0,
    }
    values.update(change)
    return DeckInput(**values)  # type: ignore[arg-type]


def test_a_flat_slab_with_no_ribs_worth_counting_is_the_topping() -> None:
    """Tiny ribs and sheet: both directions tend to the plain slab."""
    deck = _deck(rib_height=1e-4, rib_bottom=1e-4, rib_top=1e-4, sheet_thickness=1e-9, topping=0.2)
    props = deck_properties(deck)
    assert props.EA_strong == pytest.approx(EC * 0.2, rel=1e-3)
    assert props.EI_strong == pytest.approx(EC * 0.2**3 / 12, rel=2e-3)
    assert props.EI_weak == pytest.approx(EC * 0.2**3 / 12)


def test_the_strong_direction_is_the_transformed_composite_section() -> None:
    deck = _deck()
    props = deck_properties(deck)
    # Hand check: concrete per pitch, topping + trapezoidal rib.
    hr, p, wb, wt, tc = 0.0508, 0.3048, 0.1143, 0.1778, 0.065
    concrete = (tc * p + 0.5 * (wb + wt) * hr) / p
    assert props.concrete_area == pytest.approx(concrete)
    assert props.EA_strong > EC * concrete  # the sheet adds n As
    assert props.EI_strong > props.EI_weak
    assert props.EI_weak == pytest.approx(EC * tc**3 / 12)
    assert props.EA_weak == pytest.approx(EC * tc)
    assert 0.0 < props.centroid < hr + tc
    assert props.stiffness_ratio == pytest.approx(props.EI_strong / props.EI_weak)
    assert props.bending_thickness_weak == pytest.approx(tc)
    assert props.mass_per_area == pytest.approx(2400 * concrete + 7850 * props.steel_area)


def test_the_sheet_follows_the_profile() -> None:
    props = deck_properties(_deck())
    web = math.hypot(0.0508, 0.5 * (0.1778 - 0.1143))
    developed = 0.1143 + (0.3048 - 0.1778) + 2 * web
    assert props.steel_area == pytest.approx(0.00091 * developed / 0.3048)


@pytest.mark.parametrize("profile", DECK_PROFILES, ids=lambda p: p.name)
@pytest.mark.parametrize("topping", [0.05, 0.065, 0.10, 0.20])
def test_the_layers_reproduce_every_target(profile: object, topping: float) -> None:
    geometry = profile_in_units(profile, UnitSystem.SI_M_N)  # type: ignore[arg-type]
    deck = _deck(**geometry, topping=topping)
    props = deck_properties(deck)
    layers = deck_layers(props)
    got = layered_stiffness(layers)
    assert got["EAx"] == pytest.approx(props.EA_strong)
    assert got["EIx"] == pytest.approx(props.EI_strong)
    assert got["EAy"] == pytest.approx(props.EA_weak)
    assert got["EIy"] == pytest.approx(props.EI_weak)
    assert got["GA"] == pytest.approx(props.GA_inplane)
    assert got["GI"] == pytest.approx(props.GI_twist)
    assert got["mass"] == pytest.approx(props.mass_per_area)
    assert sum(layer.thickness for layer in layers) == pytest.approx(props.depth)
    assert all(min(layer.Ex, layer.Ey, layer.Gxy) > 0 for layer in layers)


def test_ribs_along_local_2_swap_the_moduli() -> None:
    props = deck_properties(_deck())
    along_x, along_y = deck_layers(props, "x"), deck_layers(props, "y")
    for a, b in zip(along_x, along_y, strict=True):
        assert (a.Ex, a.Ey, a.Gzx, a.Gyz) == pytest.approx((b.Ey, b.Ex, b.Gyz, b.Gzx))
    got = layered_stiffness(along_y)
    assert got["EIy"] == pytest.approx(props.EI_strong)


def test_a_section_that_needs_it_gets_a_deeper_equivalent_shell() -> None:
    props = deck_properties(_deck())
    stiff_faces = props.__class__(
        **{**props.__dict__, "EI_strong": props.EA_strong * props.depth**2}
    )
    assert equivalent_thickness(stiff_faces) > props.depth
    got = layered_stiffness(deck_layers(stiff_faces))
    assert got["EIx"] == pytest.approx(stiff_faces.EI_strong)


def test_the_model_wraps_each_orthotropic_material_in_a_plate_fiber() -> None:
    model = build_deck_model(
        _deck(), name="Deck", first_material_id=10, section_id=4, units=UnitSystem.SI_M_N
    )
    kinds = [type(m) for m in model.materials]
    assert kinds == [ElasticOrthotropic, PlateFiberMaterial] * 2
    assert [m.id for m in model.materials] == [10, 11, 12, 13]
    assert [layer.material_id for layer in model.section.layers] == [11, 13, 11]
    assert model.section.id == 4
    assert model.section.unit_weight * model.section.h == pytest.approx(
        model.properties.mass_per_area * 9.80665
    )


def test_bad_geometry_is_refused() -> None:
    with pytest.raises(ValueError, match="rib widths"):
        deck_properties(_deck(rib_top=0.4))
    with pytest.raises(ValueError, match="positive"):
        deck_properties(_deck(topping=0.0))


def test_the_outline_closes_over_the_ribs() -> None:
    points = deck_outline(_deck(), ribs=2)
    assert len(points) == 1 + 4 * 2 + 3
    assert max(y for y, _ in points) == pytest.approx(0.0508 + 0.065)
    assert min(y for y, _ in points) == 0.0


def test_an_unstable_orthotropic_material_is_refused() -> None:
    ElasticOrthotropic(id=1, Ex=10.0, Ey=1.0, vxy=3.0, vyz=0.0, vzx=0.0)
    with pytest.raises(ValueError, match="positive definite"):
        ElasticOrthotropic(id=1, Ex=1.0, Ey=10.0, vxy=0.5, vyz=0.0, vzx=0.0)
