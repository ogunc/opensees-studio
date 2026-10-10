"""The typical-material library: every number tied to a clause or a conversion.

Three independent checks, none of which re-uses the code that produced the
file:

- the file on disk is exactly what ``tools/build_typical_materials.py``
  generates from its published inputs (a hand edit fails here);
- every derived value satisfies the equation its ``standard`` column names —
  ACI's two moduli, the masonry factor, the psi/ksi/lb-ft³ conversions;
- the project's unit system is applied with the exact factors, and the
  resulting mass density is *coherent*: volume × density × g gives the weight
  in the project's own force unit.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

from opensees_studio.core.material_catalog import (
    FAMILY_LABELS,
    SOURCE_UNITS,
    MaterialCatalogError,
    converted_parameters,
    families,
    field_summary,
    load_materials,
    materials_of,
    preview_rows,
    search,
    to_material,
    unit_note,
)
from opensees_studio.core.units import (
    UnitSystem,
    density_scale,
    force_scale,
    gravity,
    mass_density_label,
    stress_scale,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.build_typical_materials import (
    KSI_TO_MPA,
    LB_PER_FT3_TO_KG_PER_M3,
    PSI_TO_MPA,
    render,
)

DATA = Path(__file__).resolve().parents[2] / "src" / "opensees_studio" / "data"


# ─────────────────────── the file and its shape ───────────────────────
def test_the_csv_is_what_the_generator_writes() -> None:
    on_disk = (DATA / "typical_materials.csv").read_text(encoding="utf-8")
    assert on_disk == render()


def test_the_library_covers_the_three_families_the_user_asked_for() -> None:
    entries = load_materials()
    assert len(entries) == 23
    assert families() == ["concrete", "rebar", "structural_steel", "masonry"]
    for family in families():
        assert materials_of(family), family
        assert family in FAMILY_LABELS
    assert len(materials_of("concrete")) == 7
    assert len(materials_of("masonry")) == 5


def test_every_row_names_a_source_and_a_known_model() -> None:
    known = ("ACI 318", "AISC 360", "TMS 402", "ASCE 41", "ASCE 7")
    for entry in load_materials().values():
        assert entry.standard, entry.key
        assert any(source in entry.standard for source in known), entry.key
        assert entry.is_complete, entry.key
        assert entry.notes, entry.key


def test_keys_are_unique_and_stable() -> None:
    entries = load_materials()
    assert len(entries) == len({entry.key for entry in entries.values()})
    assert "concrete_4000_unconfined" in entries
    assert "steel_a992" in entries
    assert "rebar_grade_420" in entries


# ───────────────── ACI 318: the concrete rows ─────────────────
def test_normal_weight_concrete_uses_aci_equation_19_2_2_1b() -> None:
    for entry in materials_of("concrete"):
        if "lightweight" in entry.key:
            continue
        fpc = entry.fpc_mpa
        expected = 4700.0 * math.sqrt(fpc)
        assert entry.ec_mpa == pytest.approx(expected, rel=1e-4), entry.key


def test_light_weight_concrete_uses_aci_equation_19_2_2_1a() -> None:
    entry = load_materials()["concrete_4000_lightweight_unconfined"]
    expected = entry.rho_kg_m3**1.5 * 0.043 * math.sqrt(entry.fpc_mpa)
    assert entry.ec_mpa == pytest.approx(expected, rel=1e-4)


def test_the_two_aci_modulus_equations_agree_at_normal_weight() -> None:
    """ACI's simplified 4700√f'c is Eq. (19.2.2.1a) at wc ≈ 2320 kg/m³.

    Measured: the general equation gives 4806√f'c at 2320 kg/m³ against the
    simplified 4700√f'c — 2.2 %, which is why ACI offers the rounded one.
    """
    wc = 2320.0
    general = wc**1.5 * 0.043
    assert general / 4700.0 == pytest.approx(1.0225, abs=5e-4)
    assert 4700.0 <= general <= 4700.0 * 1.03


def test_concrete_strains_and_crushing_strength_follow_the_conventions() -> None:
    for entry in materials_of("concrete"):
        assert entry.epsc0 == -0.002, entry.key
        assert entry.eps_u == -0.003, entry.key  # ACI 318-25 §22.2.2.1
        assert entry.fpcu_mpa == pytest.approx(0.2 * entry.fpc_mpa, rel=1e-4), entry.key


def test_no_concrete_below_acis_minimum_strength() -> None:
    """ACI 318-25 §19.2.1.1: structural concrete is at least 17 MPa."""
    for entry in materials_of("concrete"):
        assert entry.fpc_mpa >= 17.0, entry.key


# ───────────────── steel ─────────────────
def test_reinforcing_grades_are_the_grades_aci_permits() -> None:
    grades = {entry.fy_mpa for entry in materials_of("rebar")}
    assert grades == {280.0, 420.0, 550.0, 690.0}
    for entry in materials_of("rebar"):
        assert entry.e_mpa == pytest.approx(29000.0 * KSI_TO_MPA, rel=1e-4)
        assert entry.b == pytest.approx(0.01)


def test_structural_steel_fy_and_fu_follow_the_published_ksi() -> None:
    expected = {
        "steel_a992": (50.0, 65.0),
        "steel_a36": (36.0, 58.0),
        "steel_a572_50": (50.0, 65.0),
        "steel_a500_b": (46.0, 58.0),
    }
    entries = load_materials()
    for key, (fy_ksi, fu_ksi) in expected.items():
        entry = entries[key]
        assert entry.fy_ksi == fy_ksi
        assert entry.fy_mpa == pytest.approx(entry.fy_ksi * KSI_TO_MPA, rel=1e-4)
        assert entry.fu_ksi == fu_ksi
        assert entry.fu_mpa == pytest.approx(entry.fu_ksi * KSI_TO_MPA, rel=1e-4)
        assert entry.fu_mpa > entry.fy_mpa
    # The elastic entry carries no yield at all: it is for linear analysis.
    elastic = entries["steel_elastic"]
    assert elastic.model == "ElasticUniaxial"
    assert elastic.fy_mpa is None


# ───────────────── masonry ─────────────────
def test_masonry_modulus_is_the_tms_factor() -> None:
    """TMS 402: Em = 700 f'm for clay masonry, 900 f'm for concrete masonry."""
    factors = set()
    for entry in materials_of("masonry"):
        factors.add(entry.em_factor)
        assert entry.em_mpa == pytest.approx(entry.em_factor * entry.fm_mpa, rel=1e-4), entry.key
        if entry.key.startswith("masonry_clay"):
            assert entry.em_factor == 700.0
        else:
            assert entry.em_factor == 900.0
    assert factors == {700.0, 900.0}


def test_masonry_strengths_are_the_usual_specified_ones() -> None:
    strengths = sorted({entry.fm_psi for entry in materials_of("masonry")})
    assert strengths == [1500.0, 2000.0]
    for entry in materials_of("masonry"):
        assert entry.model == "ElasticIsotropic"
        assert entry.nu == pytest.approx(0.2)


# ───────────────── published units and the exact conversions ─────────────────
@pytest.mark.parametrize(
    ("column_a", "column_b", "factor"),
    [
        ("fpc_mpa", "fpc_psi", PSI_TO_MPA),
        ("fy_mpa", "fy_ksi", KSI_TO_MPA),
        ("fu_mpa", "fu_ksi", KSI_TO_MPA),
        ("e_mpa", "e_ksi", KSI_TO_MPA),
        ("fm_mpa", "fm_psi", PSI_TO_MPA),
        ("rho_kg_m3", "rho_pcf", LB_PER_FT3_TO_KG_PER_M3),
    ],
)
def test_published_pairs_convert_exactly(column_a: str, column_b: str, factor: float) -> None:
    """Whenever a row carries both units, the pair is one exact conversion.

    The file stores six significant figures, so the check is at 1e-4 relative —
    far tighter than any rounded table, far looser than the text rounding.
    """
    seen = 0
    for entry in load_materials().values():
        first, second = getattr(entry, column_a), getattr(entry, column_b)
        if first is None or second is None:
            continue
        seen += 1
        assert first == pytest.approx(second * factor, rel=1e-4), entry.key
    assert seen > 0, f"no row carries both {column_a} and {column_b}"


def test_the_published_densities_are_asce_7_tabulated_ones() -> None:
    """ASCE 7-16 Table C3.1-2, converted: 150 lb/ft³ is 2402.77 kg/m³."""
    entries = load_materials()
    assert entries["concrete_4000_unconfined"].rho_pcf == 150.0
    assert entries["concrete_4000_unconfined"].rho_kg_m3 == pytest.approx(2402.77, abs=0.01)
    assert entries["masonry_clay_1500"].rho_pcf == 130.0  # hard brick
    assert entries["masonry_cmu_lightweight_1500"].rho_pcf == 105.0
    assert entries["masonry_cmu_grouted_2000"].rho_pcf == 140.0  # masonry grout


# ───────────────── conversion into a project's units ─────────────────
def test_conversion_to_an_si_project_keeps_the_mpa_numbers() -> None:
    """An mm-N project measures stress in MPa, which is what the table publishes."""
    entry = load_materials()["concrete_4000_unconfined"]
    mm = converted_parameters(entry, UnitSystem.SI_MM_N)
    assert mm["fpc"] == pytest.approx(-27.579, rel=1e-4)
    assert mm["epsc0"] == -0.002
    assert stress_scale(SOURCE_UNITS, UnitSystem.SI_MM_N) * 1e6 == pytest.approx(1.0)
    # A metre-N project measures it in Pa, 1e6 times larger.
    m = converted_parameters(entry, UnitSystem.SI_M_N)
    assert m["fpc"] == pytest.approx(mm["fpc"] * 1e6, rel=1e-9)


def test_conversion_to_a_us_project_gives_the_published_ksi() -> None:
    """4000 psi of concrete is 4 ksi; A992 is 50 ksi — the round trip closes."""
    entries = load_materials()
    concrete = converted_parameters(entries["concrete_4000_unconfined"], UnitSystem.US_IN_KIP)
    assert concrete["fpc"] == pytest.approx(-4.0, rel=1e-4)
    assert concrete["fpcu"] == pytest.approx(-0.8, rel=1e-4)

    steel = converted_parameters(entries["steel_a992"], UnitSystem.US_IN_KIP)
    assert steel["Fy"] == pytest.approx(50.0, rel=1e-4)
    assert steel["E0"] == pytest.approx(29000.0, rel=1e-4)
    assert steel["b"] == pytest.approx(0.02)


def test_a_converted_density_is_coherent_with_the_force_unit() -> None:
    """Volume × density × g must give the weight in the project's force unit.

    This is what makes the mass unit *coherent*: a 1 in³ cube of the library's
    concrete weighs 0.0868 lbf, whether that is computed in SI and converted or
    computed straight from the kip-based density.
    """
    entry = load_materials()["concrete_4000_unconfined"]
    masonry = load_materials()["masonry_clay_1500"]
    for units, volume in (
        (UnitSystem.SI_M_N, 1.0),  # 1 m³
        (UnitSystem.US_IN_KIP, 1.0),  # 1 in³
    ):
        rho = entry.rho_kg_m3 * density_scale(SOURCE_UNITS, units)
        # The same conversion is what a material that carries a density gets.
        assert converted_parameters(masonry, units)["rho"] == pytest.approx(
            masonry.rho_kg_m3 * density_scale(SOURCE_UNITS, units), rel=1e-9
        )
        weight = rho * volume * gravity(units)  # mass × g, in the force unit
        # The same weight, from the published SI density.
        length_scale = 1.0 if units is UnitSystem.SI_M_N else 1 / 0.0254
        si_volume = volume / length_scale**3
        si_weight_n = entry.rho_kg_m3 * si_volume * 9.80665
        expected = si_weight_n * force_scale(UnitSystem.SI_M_N, units)
        assert weight == pytest.approx(expected, rel=1e-4)


def test_the_density_factor_is_the_one_the_label_names() -> None:
    assert density_scale(SOURCE_UNITS, UnitSystem.SI_MM_N) == pytest.approx(1e-12)
    assert mass_density_label(UnitSystem.SI_M_N) == "kg/m³"
    assert mass_density_label(UnitSystem.US_IN_KIP) == "kip·s²/in⁴"
    entry = load_materials()["masonry_clay_1500"]
    rho = converted_parameters(entry, UnitSystem.SI_MM_N)["rho"]
    assert rho == pytest.approx(2082.4 * 1e-12, rel=1e-4)


def test_to_material_builds_the_class_the_row_names() -> None:
    entries = load_materials()
    concrete = to_material(entries["concrete_4000_unconfined"], 5, UnitSystem.SI_M_N)
    assert concrete.id == 5
    assert concrete.type == "Concrete01"
    assert concrete.fpc == pytest.approx(-27.579e6, rel=1e-4)
    assert concrete.fpc < 0 and concrete.fpcu < 0 and concrete.epsc0 < 0 and concrete.epsU < 0

    steel = to_material(entries["steel_a992"], 6, UnitSystem.SI_M_N)
    assert steel.type == "Steel02"
    assert steel.Fy == pytest.approx(50.0 * KSI_TO_MPA * 1e6, rel=1e-4)
    assert steel.R0 == 18.0 and steel.cR1 == 0.925 and steel.cR2 == 0.15

    masonry = to_material(entries["masonry_clay_1500"], 7, UnitSystem.SI_M_N)
    assert masonry.type == "ElasticIsotropic"
    expected_e = 700.0 * 1500.0 * PSI_TO_MPA * 1e6  # Em = 700 f'm, with f'm = 1500 psi
    assert pytest.approx(expected_e, rel=1e-4) == masonry.E
    assert masonry.rho == pytest.approx(2082.4, rel=1e-4)

    elastic = to_material(entries["steel_elastic"], 8, UnitSystem.SI_MM_N)
    assert elastic.type == "Elastic"


def test_a_name_override_keeps_the_library_name_as_the_default() -> None:
    entry = load_materials()["steel_a992"]
    assert to_material(entry, 1, UnitSystem.SI_M_N).name == entry.name
    assert to_material(entry, 1, UnitSystem.SI_M_N, name="Column steel").name == "Column steel"


def test_an_incomplete_row_is_refused_rather_than_built() -> None:
    good = load_materials()["steel_a992"]
    broken = good.model_copy(update={"fy_mpa": None})
    assert not broken.is_complete
    with pytest.raises(MaterialCatalogError, match="incomplete"):
        converted_parameters(broken, UnitSystem.SI_M_N)
    with pytest.raises(MaterialCatalogError, match="unknown material model"):
        converted_parameters(good.model_copy(update={"model": "Nope"}), UnitSystem.SI_M_N)


# ───────────────── the picker's view of a row ─────────────────
def test_preview_rows_show_the_published_value_beside_the_inserted_one() -> None:
    entry = load_materials()["rebar_grade_420"]
    rows = dict(
        (parameter, (published, converted))
        for parameter, published, converted in preview_rows(entry, UnitSystem.US_IN_KIP)
    )
    assert rows["Fy"][0] == "420 MPa"
    assert rows["Fy"][1].endswith("ksi")
    assert float(rows["Fy"][1].split()[0]) == pytest.approx(60.9, abs=0.1)  # 420 MPa = 60.9 ksi
    assert "MPa" in unit_note(entry)


def test_preview_rows_skip_what_a_material_does_not_have() -> None:
    """A plain elastic steel has no Fy, and the table must not invent one."""
    entry = load_materials()["steel_elastic"]
    labels = [parameter for parameter, _p, _c in preview_rows(entry, UnitSystem.SI_M_N)]
    assert labels == ["E"]


def test_search_and_family_filters() -> None:
    assert {entry.key for entry in search("A992")} == {"steel_a992"}
    assert {entry.key for entry in search("masonry")} == {
        entry.key for entry in materials_of("masonry")
    }
    assert search("f'c")
    assert search("") == list(load_materials().values())
    assert {entry.key for entry in search("4000 psi")} >= {"concrete_4000_unconfined"}
    assert search("nothing like this") == []


def test_the_summary_line_names_the_governing_property() -> None:
    entries = load_materials()
    assert "f'c" in field_summary(entries["concrete_4000_unconfined"])
    assert "Fy" in field_summary(entries["steel_a992"])
    assert "f'm" in field_summary(entries["masonry_clay_1500"])
