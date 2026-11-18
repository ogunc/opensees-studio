"""Design-code combination generators: factors, signs, orthogonal rule, groups."""

from __future__ import annotations

import pytest

from opensees_studio.core.code_combinations import (
    CODES,
    EN_IMPOSED_PSI,
    default_options,
    envelope_groups,
    generate_for_code,
    unused_roles,
)
from opensees_studio.core.combinations import lateral_variants, variant_name

D, L, W, E, S, LR = 1, 2, 3, 4, 5, 6


def _by_name(code: str, roles, **kw):  # type: ignore[no-untyped-def]
    out = generate_for_code(code, roles, **kw)
    return {c.name: {t.ref_id: t.factor for t in c.terms} for c in out}


def test_every_code_has_default_options_and_needs_a_dead_case() -> None:
    assert set(CODES) == {"asce7_lrfd", "asce7_asd", "en1990", "tbdy"}
    for code in CODES:
        assert generate_for_code(code, {"L": [L], "W": [W]}) == []
        assert set(default_options(code)) == {o.key for o in CODES[code].options}
    with pytest.raises(ValueError, match="Unknown combination code"):
        generate_for_code("nope", {"D": [D]})


def test_asd_basic_combinations() -> None:
    got = _by_name("asce7_asd", {"D": [D], "L": [L], "S": [S], "W": [W], "E": [E]})
    assert got["D"] == {D: 1.0}
    assert got["D+L"] == {D: 1.0, L: 1.0}
    assert got["D+S"] == {D: 1.0, S: 1.0}
    assert got["D+0.75L+0.75S"] == {D: 1.0, L: 0.75, S: 0.75}
    assert got["D+0.6W"] == {D: 1.0, W: 0.6}
    assert got["D-0.6W"] == {D: 1.0, W: -0.6}
    assert got["D+0.7E"] == {D: 1.0, E: 0.7}
    assert got["D+0.75L+0.45W+0.75S"] == {D: 1.0, L: 0.75, W: 0.45, S: 0.75}
    assert got["D+0.75L+0.525E+0.75S"] == {D: 1.0, L: 0.75, E: 0.525, S: 0.75}
    assert got["0.6D+0.6W"] == {D: 0.6, W: 0.6}
    assert got["0.6D-0.7E"] == {D: 0.6, E: -0.7}


def test_asd_without_lateral_or_roof_loads_makes_only_what_it_can() -> None:
    assert set(_by_name("asce7_asd", {"D": [D]})) == {"D"}
    assert set(_by_name("asce7_asd", {"D": [D], "L": [L]})) == {"D", "D+L"}


def test_en1990_ultimate_equation_610_numbers() -> None:
    roles = {"D": [D], "L": [L], "W": [W]}
    got = _by_name("en1990", roles)
    assert got["ULS 1.35G"] == {D: 1.35}
    assert got["ULS 1.35G+1.5Q"] == {D: 1.35, L: 1.5}
    # Imposed load leading, wind accompanying with psi0 = 0.6: 1.5 x 0.6 = 0.9.
    assert got["ULS 1.35G+1.5Q+0.9W"] == {D: 1.35, L: 1.5, W: pytest.approx(0.9)}
    assert got["ULS 1.35G+1.5Q-0.9W"][W] == pytest.approx(-0.9)
    # Wind leading, imposed accompanying with psi0 = 0.7 (category A): 1.5 x 0.7 = 1.05.
    assert got["ULS 1.35G+1.05Q+1.5W"] == {D: 1.35, L: pytest.approx(1.05), W: 1.5}
    assert got["ULS 1.35G+1.5W"] == {D: 1.35, W: 1.5}
    assert "ULS 1.0G+1.5Q" not in got  # favourable permanent action is opt-in


def test_en1990_imposed_category_and_favourable_permanent() -> None:
    roles = {"D": [D], "L": [L], "W": [W]}
    got = _by_name("en1990", roles, options={"imposed_category": "E", "favourable_permanent": True})
    psi0 = EN_IMPOSED_PSI["E"][0]
    assert psi0 == 1.0
    assert got["ULS 1.35G+1.5Q+0.9W"][L] == 1.5
    assert got["ULS 1.35G+1.5Q+1.5W"][L] == pytest.approx(1.5 * psi0)
    # gamma_G = 1.0 reads "G" in the name.
    assert got["ULS G+1.5Q+1.5W"] == {D: 1.0, L: 1.5, W: 1.5}
    assert got["ULS G+1.5W"] == {D: 1.0, W: 1.5}


def test_en1990_roof_category_has_zero_psi() -> None:
    got = _by_name("en1990", {"D": [D], "L": [L], "Lr": [LR]}, options={"imposed_category": "H"})
    # Category H imposed load accompanies at psi0 = 0, so only leading combinations remain.
    assert got["ULS 1.35G+1.5Q"] == {D: 1.35, L: 1.5}
    assert not any("Q+" in name and name.startswith("ULS 1.35G+1.5Q+") for name in got)


def test_en1990_serviceability_combinations() -> None:
    roles = {"D": [D], "L": [L], "W": [W]}
    out = generate_for_code("en1990", roles)
    groups = envelope_groups(out)
    assert list(groups) == ["ULS", "SLS characteristic", "SLS frequent", "SLS quasi-permanent"]
    got = {c.name: {t.ref_id: t.factor for t in c.terms} for c in out}
    # Characteristic: G + Q1 + sum psi0 Qi.
    assert got["SLS char G+Q+0.6W"] == {D: 1.0, L: 1.0, W: pytest.approx(0.6)}
    assert got["SLS char G+0.7Q+W"] == {D: 1.0, L: pytest.approx(0.7), W: 1.0}
    # Frequent: G + psi1 Q1 + sum psi2 Qi (wind psi2 = 0 leaves the imposed psi1).
    assert got["SLS freq G+0.5Q"] == {D: 1.0, L: 0.5}
    assert got["SLS freq G+0.2W"] == {D: 1.0, W: 0.2}
    assert got["SLS freq G+0.3Q+0.2W"] == {D: 1.0, L: 0.3, W: 0.2}
    # Quasi-permanent: G + sum psi2 Q.
    assert got["SLS quasi G+0.3Q"] == {D: 1.0, L: 0.3}


def test_en1990_seismic_uses_psi2() -> None:
    got = _by_name("en1990", {"D": [D], "L": [L], "E": [E]})
    assert got["ULS G+E+0.3Q"] == {D: 1.0, E: 1.0, L: 0.3}
    assert got["ULS G-E+0.3Q"] == {D: 1.0, E: -1.0, L: 0.3}


def test_en1990_snow_altitude_changes_psi() -> None:
    low = _by_name("en1990", {"D": [D], "S": [S]})
    high = _by_name("en1990", {"D": [D], "S": [S]}, options={"snow_above_1000m": True})
    assert low["SLS quasi G"] == {D: 1.0}
    assert high["SLS quasi G+0.2S"] == {D: 1.0, S: 0.2}


def test_tbdy_combinations_and_live_participation() -> None:
    roles = {"D": [D], "L": [L], "E": [E], "W": [W], "S": [S]}
    got = _by_name("tbdy", roles, options={"live_participation": 0.3})
    assert got["1.4G+1.6Q"] == {D: 1.4, L: 1.6}
    assert got["G+0.3Q+E"] == {D: 1.0, L: 0.3, E: 1.0}
    assert got["G+0.3Q-E"][E] == -1.0
    assert got["0.9G+E"] == {D: 0.9, E: 1.0}
    assert got["0.9G-E"] == {D: 0.9, E: -1.0}
    assert got["G+1.3Q+1.3W"] == {D: 1.0, L: 1.3, W: 1.3}
    assert got["0.9G-1.3W"] == {D: 0.9, W: -1.3}
    assert not any("S" in name for name in got)  # snow is not used
    assert unused_roles("tbdy", roles) == ["S"]
    assert unused_roles("en1990", roles) == []
    with pytest.raises(ValueError, match="participation"):
        generate_for_code("tbdy", roles, options={"live_participation": -1.0})


def test_tbdy_default_is_full_live_load() -> None:
    got = _by_name("tbdy", {"D": [D], "L": [L], "E": [E]})
    assert got["G+Q+E"] == {D: 1.0, L: 1.0, E: 1.0}


def test_orthogonal_rule_pairs_each_direction_at_100_and_30_percent() -> None:
    variants = lateral_variants([10, 11], orthogonal=True)
    assert len(variants) == 8
    assert ((1.0, 10), (0.3, 11)) in variants
    assert ((1.0, 10), (-0.3, 11)) in variants
    assert ((-0.3, 10), (-1.0, 11)) in variants or ((-1.0, 11), (-0.3, 10)) in variants
    plain = lateral_variants([10, 11])
    assert plain == [((1.0, 10),), ((-1.0, 10),), ((1.0, 11),), ((-1.0, 11),)]


def test_orthogonal_rule_with_spectrum_cases_needs_no_sign_pairs() -> None:
    # A response spectrum result is already +-peak: one combination per primary.
    variants = lateral_variants([10, 11], [10, 11], orthogonal=True)
    assert variants == [((1.0, 10), (0.3, 11)), ((1.0, 11), (0.3, 10))]
    # One static, one spectrum: only the static case takes both signs.
    mixed = lateral_variants([10, 11], [11], orthogonal=True)
    assert len(mixed) == 4


def test_orthogonal_option_applies_to_every_code_with_earthquake() -> None:
    roles = {"D": [D], "E": [E, 7]}
    for code in ("asce7_lrfd", "asce7_asd", "en1990", "tbdy"):
        names = [
            c.name
            for c in generate_for_code(code, roles, options={"orthogonal": True})
            if "E" in c.name
        ]
        assert any("0.3E" in n or "0.21E" in n or "0.27E" in n for n in names), code
    off = [c.name for c in generate_for_code("tbdy", roles)]
    assert not any("0.3E" in n for n in off)


def test_variant_name_signs_and_factors() -> None:
    assert variant_name(1.0, ((1.0, 1),), lambda c: "E") == "+E"
    assert variant_name(0.5, ((-1.0, 1),), lambda c: "W") == "-0.5W"
    assert variant_name(0.7, ((1.0, 1), (-0.3, 2)), lambda c: f"E{c}") == "+0.7E1-0.21E2"


def test_spectrum_cases_get_one_combination_not_two() -> None:
    got = _by_name("tbdy", {"D": [D], "E": [E]}, peak_cases=[E])
    assert "0.9G+E" in got and "0.9G-E" not in got


def test_case_names_label_alternatives_when_several_cases_share_a_role() -> None:
    got = _by_name(
        "asce7_asd",
        {"D": [D], "W": [3, 8]},
        case_names={3: "WX", 8: "WY"},
    )
    assert "D+0.6W:WX" in got and "D-0.6W:WY" in got


def test_missing_load_cases_proposes_one_case_per_unused_role() -> None:
    from opensees_studio.core.code_combinations import missing_load_cases

    assert missing_load_cases("asce7_lrfd", {"D": [1]}) == [
        ("L", "LIVE"),
        ("Lr", "ROOF LIVE"),
        ("S", "SNOW"),
        ("R", "RAIN"),
        ("W", "WIND X"),
        ("W", "WIND Y"),
        ("E", "EQ X"),
        ("E", "EQ Y"),
    ]
    tbdy = missing_load_cases("tbdy", {"D": [1], "W": [2]}, ndm=2)
    assert tbdy == [("L", "LIVE"), ("E", "EQ X")]
    assert missing_load_cases("tbdy", {"D": [1], "L": [2], "W": [3], "E": [4]}) == []


def test_placeholder_names_read_back_as_their_role() -> None:
    from opensees_studio.core.code_combinations import PLACEHOLDER_CASE_NAMES
    from opensees_studio.core.combinations import guess_load_role

    for role, names in PLACEHOLDER_CASE_NAMES.items():
        for name in names:
            assert guess_load_role(name) == role, name


def test_make_load_cases_builds_empty_cases_with_fresh_ids() -> None:
    from opensees_studio.core import Project, make_load_cases

    project = Project()
    series, patterns, cases = make_load_cases(
        project, ["DEAD", "WIND X"], self_weight=frozenset({"DEAD"})
    )
    assert [c.name for c in cases] == ["DEAD", "WIND X"]
    assert [p.self_weight for p in patterns] == [1.0, 0.0]
    assert [c.pattern_ids for c in cases] == [[p.id] for p in patterns]
    assert [p.time_series_id for p in patterns] == [t.id for t in series]
    assert len({c.id for c in cases}) == 2
