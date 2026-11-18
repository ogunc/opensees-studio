"""The Concrete Section Wizard's numbers: bars, Mander's confinement, materials, layout."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core.materials import Concrete02, Steel02
from opensees_studio.core.sections.concrete import (
    ConcreteSectionSpec,
    bar_positions,
    bar_size,
    build_concrete_section,
    concrete_modulus,
    mander,
    tie_ratio,
)
from opensees_studio.core.units import UnitSystem

SI = UnitSystem.SI_M_N


def test_bar_sizes_in_project_units() -> None:
    d, a = bar_size("φ20", SI)
    assert d == pytest.approx(0.020)
    assert a == pytest.approx(math.pi * 0.020**2 / 4)
    d, a = bar_size("#8", UnitSystem.US_IN_KIP)
    assert (d, a) == (1.0, 0.79)
    d, a = bar_size("#8", SI)
    assert d == pytest.approx(0.0254)
    with pytest.raises(KeyError):
        bar_size("φ19", SI)


def test_concrete_modulus_aci() -> None:
    assert concrete_modulus(30e6, SI) == pytest.approx(4700 * math.sqrt(30) * 1e6)
    ksi = concrete_modulus(4.0, UnitSystem.US_IN_KIP)
    assert ksi == pytest.approx(4700 * math.sqrt(4 * 6.894757) / 6.894757, rel=1e-6)


def test_mander_rectangular_hoops_by_hand() -> None:
    spec = ConcreteSectionSpec(h=0.5, b=0.3, clear_cover=0.04, tie="φ10", tie_spacing=0.10)
    a = math.pi * 0.010**2 / 4
    bc, dc = 0.3 - 0.08 - 0.010, 0.5 - 0.08 - 0.010
    rho = 2 * a / (0.10 * dc) + 2 * a / (0.10 * bc)
    assert tie_ratio(spec) == pytest.approx(rho)
    fl = 0.5 * 0.75 * rho * 420e6
    fcc = 30e6 * (-1.254 + 2.254 * math.sqrt(1 + 7.94 * fl / 30e6) - 2 * fl / 30e6)
    conf = mander(spec, 0.002)
    assert conf.fcc == pytest.approx(fcc)
    assert conf.eps_cc == pytest.approx(0.002 * (1 + 5 * (fcc / 30e6 - 1)))
    assert conf.eps_cu == pytest.approx(0.004 + 1.4 * rho * 420e6 * 0.09 / fcc)


def test_spiral_ratio_of_a_circle() -> None:
    spec = ConcreteSectionSpec(shape="circ", h=0.6, clear_cover=0.04, tie="φ12", tie_spacing=0.08)
    a = math.pi * 0.012**2 / 4
    ds = 0.6 - 0.08 - 0.012
    assert tie_ratio(spec) == pytest.approx(4 * a / (ds * 0.08))


def test_materials_and_sections() -> None:
    spec = ConcreteSectionSpec()
    built = build_concrete_section(spec, material_id=5, section_id=3, elastic=True)
    cover, core, steel = built.materials
    assert isinstance(cover, Concrete02) and isinstance(core, Concrete02)
    assert isinstance(steel, Steel02)
    assert [cover.id, core.id, steel.id] == [5, 6, 7]
    assert cover.fpc == -30e6 and cover.fpcu == 0.0
    assert core.fpc < cover.fpc  # confined: stronger (more negative)
    # The initial tangent 2 fpc / epsc0 of the cover equals Ec.
    assert 2 * cover.fpc / cover.epsc0 == pytest.approx(built.Ec)
    assert steel.Fy == 420e6 and steel.E0 == 200e9
    assert built.fiber is not None and built.fiber.id == 3
    assert built.elastic is not None and built.elastic.id == 4
    assert built.elastic.Iz == pytest.approx(0.70 * 0.3 * 0.5**3 / 12)
    assert built.fiber.GJ is not None and built.fiber.GJ > 0
    # Cover strips + core + 8 bars.
    assert len(built.fiber.patches) == 5
    assert sum(layer.n_bars for layer in built.fiber.layers) == 8


def test_unconfined_core_is_the_cover_concrete() -> None:
    built = build_concrete_section(ConcreteSectionSpec(confined=False), material_id=1, section_id=1)
    cover, core, _ = built.materials
    assert core.model_dump(exclude={"id", "name"}) == cover.model_dump(exclude={"id", "name"})
    assert built.confinement is None


def test_tee_and_ell_flanges() -> None:
    tee = ConcreteSectionSpec(shape="tee", h=0.6, b=0.3, bf=1.2, hf=0.15)
    built = build_concrete_section(tee, material_id=1, section_id=1)
    props = built.properties
    assert props is not None
    assert pytest.approx(0.3 * 0.6 + 0.9 * 0.15) == props.A
    assert props.z_c == pytest.approx(0.0, abs=1e-12)
    assert props.y_c > 0  # the flange lifts the centroid
    assert len(built.fiber.patches) == 7  # type: ignore[union-attr]
    ell = ConcreteSectionSpec(shape="ell", h=0.6, b=0.3, bf=1.2, hf=0.15)
    built = build_concrete_section(ell, material_id=1, section_id=1)
    assert built.properties.z_c > 0  # type: ignore[union-attr]
    assert len(built.fiber.patches) == 6  # type: ignore[union-attr]


def test_bar_positions_follow_the_cover() -> None:
    spec = ConcreteSectionSpec(h=0.5, b=0.3, clear_cover=0.04, bar="φ20", tie="φ10")
    c = 0.04 + 0.010 + 0.010
    assert spec.cover_to_bars == pytest.approx(c)
    positions = bar_positions(spec)
    assert len(positions) == spec.bar_count == 8
    assert max(y for y, _ in positions) == pytest.approx(0.25 - c)
    assert max(z for _, z in positions) == pytest.approx(0.15 - c)


def test_invalid_specs_are_refused() -> None:
    assert ConcreteSectionSpec(h=0.1, b=0.1, clear_cover=0.05).validate()
    assert ConcreteSectionSpec(shape="tee", bf=0.2, b=0.3).validate()
    assert ConcreteSectionSpec(shape="circ", n_bars=2).validate()
    assert ConcreteSectionSpec(bar="φ19").validate()
    with pytest.raises(ValueError):
        build_concrete_section(ConcreteSectionSpec(n_top=1), material_id=1, section_id=1)


def test_low_steel_ratio_is_noted_for_a_column() -> None:
    spec = ConcreteSectionSpec(h=1.0, b=1.0, n_top=2, n_bottom=2, n_side=0, bar="φ12")
    built = build_concrete_section(spec, material_id=1, section_id=1)
    assert any("outside ACI" in note for note in built.notes)


def test_concrete_cm_arguments_and_gap_close() -> None:
    from opensees_studio.core.materials import ConcreteCM

    cm = ConcreteCM(id=4, fpcc=-30e6, epcc=-0.002, Ec=30e9)
    assert cm.opensees_args() == [-30e6, -0.002, 30e9, 7.0, 1.035, 2e6, 8e-5, 1.2, 10000.0]
    assert cm.model_copy(update={"gap_close": 1}).opensees_args()[-2:] == ["-GapClose", 1]


def test_chang_mander_parameters_of_unconfined_concrete() -> None:
    from opensees_studio.core.sections.concrete import chang_mander_r, chang_mander_strain

    assert chang_mander_strain(30e6, SI) == pytest.approx(30**0.25 / 1150)
    assert chang_mander_r(30e6, SI) == pytest.approx(30 / 5.2 - 1.9)
    assert chang_mander_r(5e6, SI) == pytest.approx(1.1)  # floored: r must exceed 1


def test_concrete_cm_wizard_core_follows_mander() -> None:
    from opensees_studio.core.materials import ConcreteCM

    built = build_concrete_section(
        ConcreteSectionSpec(concrete_model="ConcreteCM"), material_id=1, section_id=1
    )
    cover, core, steel = built.materials
    assert isinstance(cover, ConcreteCM) and isinstance(core, ConcreteCM)
    assert isinstance(steel, Steel02)
    conf = built.confinement
    assert conf is not None
    assert core.fpcc == pytest.approx(-conf.fcc) and core.epcc == pytest.approx(-conf.eps_cc)
    # Mander's r = Ec / (Ec - Esec): Tsai's envelope with it is Mander's curve.
    assert core.rc == pytest.approx(core.Ec / (core.Ec - conf.fcc / conf.eps_cc))
    assert core.xcrn == pytest.approx(conf.eps_cu / conf.eps_cc)
    assert cover.ft == core.ft > 0


def test_concrete_cm_unconfined_core_is_the_cover() -> None:
    built = build_concrete_section(
        ConcreteSectionSpec(concrete_model="ConcreteCM", confined=False),
        material_id=1,
        section_id=1,
    )
    cover, core, _steel = built.materials
    assert core.model_dump(exclude={"id", "name"}) == cover.model_dump(exclude={"id", "name"})
