"""Load combinations: the model, the combination math, and its result adapter."""

from __future__ import annotations

import json

import numpy as np
import pytest
from pydantic import ValidationError

from opensees_studio.core import (
    CombinationTerm,
    ElasticBeamColumn,
    ElasticSection,
    LoadCombination,
    ModalCase,
    Node,
    Project,
    ResponseSpectrumCase,
    StaticCase,
)
from opensees_studio.core.combinations import (
    ResponseBounds,
    asce7_16_lrfd,
    combination_order,
    combination_problems,
    combinations_using_case,
    combine,
    guess_load_role,
    model_fingerprint,
    required_case_ids,
    superposition_warnings,
)
from opensees_studio.core.units import UnitSystem
from opensees_studio.services.combination import (
    MissingCaseResultsError,
    case_bounds,
    combine_results,
)
from opensees_studio.services.element_forces import (
    ForceComponent,
    envelope_diagram_data,
    extract_diagram_data,
)
from opensees_studio.services.persistence import _project_json, load_project, save_project
from opensees_studio.services.result_tables import combination_tables
from opensees_studio.services.results import ResponseSpectrumResults, StaticResults


def _single(**fields: dict[int, list[float]]) -> ResponseBounds:
    return ResponseBounds.single(
        {
            name: {k: np.asarray(v, dtype=float) for k, v in values.items()}
            for name, values in fields.items()
        }
    )


def _peaks(**fields: dict[int, list[float]]) -> ResponseBounds:
    return ResponseBounds.peaks(
        {
            name: {k: np.asarray(v, dtype=float) for k, v in values.items()}
            for name, values in fields.items()
        }
    )


# ─────────────────────────── math ───────────────────────────
def test_linear_add_scales_and_sums_single_valued_results() -> None:
    a = _single(node_disp={1: [1.0, 2.0]}, node_reaction={1: [10.0, 0.0]})
    b = _single(node_disp={1: [0.5, -4.0]}, node_reaction={1: [-2.0, 3.0]})
    out = combine("LinearAdd", [(1.2, a), (1.6, b)])
    assert out.bounds.single_valued
    np.testing.assert_allclose(out.bounds.upper["node_disp"][1], [1.2 + 0.8, 2.4 - 6.4])
    np.testing.assert_allclose(out.bounds.upper["node_reaction"][1], [12.0 - 3.2, 4.8])
    np.testing.assert_array_equal(
        out.bounds.lower["node_disp"][1], out.bounds.upper["node_disp"][1]
    )
    assert out.missing_fields == []


def test_envelope_takes_component_wise_max_and_min() -> None:
    a = _single(node_disp={1: [1.0, -2.0, 0.0]})
    b = _single(node_disp={1: [-3.0, 5.0, 0.0]})
    out = combine("Envelope", [(1.0, a), (1.0, b)])
    assert not out.bounds.single_valued
    np.testing.assert_allclose(out.bounds.upper["node_disp"][1], [1.0, 5.0, 0.0])
    np.testing.assert_allclose(out.bounds.lower["node_disp"][1], [-3.0, -2.0, 0.0])


def test_envelope_of_one_single_valued_term_stays_single_valued() -> None:
    out = combine("Envelope", [(2.0, _single(node_disp={1: [1.0]}))])
    assert out.bounds.single_valued
    np.testing.assert_allclose(out.bounds.upper["node_disp"][1], [2.0])


def test_negative_factor_swaps_the_bounds_of_a_term() -> None:
    envelope = combine(
        "Envelope", [(1.0, _single(node_disp={1: [1.0]})), (1.0, _single(node_disp={1: [4.0]}))]
    )
    out = combine("LinearAdd", [(-1.0, envelope.bounds)])
    np.testing.assert_allclose(out.bounds.upper["node_disp"][1], [-1.0])
    np.testing.assert_allclose(out.bounds.lower["node_disp"][1], [-4.0])


def test_linear_add_with_a_spectrum_peak_gives_plus_minus_bounds() -> None:
    static = _single(node_disp={1: [1.0, 1.0]})
    spectrum = _peaks(node_disp={1: [0.25, -0.5]})
    out = combine("LinearAdd", [(1.0, static), (2.0, spectrum)])
    assert not out.bounds.single_valued
    np.testing.assert_allclose(out.bounds.upper["node_disp"][1], [1.5, 2.0])
    np.testing.assert_allclose(out.bounds.lower["node_disp"][1], [0.5, 0.0])


def test_absolute_add_and_srss_sum_magnitudes() -> None:
    a = _single(node_disp={1: [3.0, -1.0]})
    b = _single(node_disp={1: [-4.0, 0.0]})
    absolute = combine("AbsoluteAdd", [(1.0, a), (1.0, b)]).bounds
    srss = combine("SRSS", [(1.0, a), (1.0, b)]).bounds
    np.testing.assert_allclose(absolute.upper["node_disp"][1], [7.0, 1.0])
    np.testing.assert_allclose(absolute.lower["node_disp"][1], [-7.0, -1.0])
    np.testing.assert_allclose(srss.upper["node_disp"][1], [5.0, 1.0])
    np.testing.assert_allclose(srss.lower["node_disp"][1], [-5.0, -1.0])
    assert not srss.single_valued


def test_a_field_one_term_lacks_is_left_out_and_reported() -> None:
    static = _single(node_disp={1: [1.0, 2.0, 3.0, 0.1, 0.2, 0.3]}, element_forces={7: [1.0, 2.0]})
    spectrum = _peaks(node_disp={1: [0.5, 0.5, 0.5]})
    out = combine("SRSS", [(1.0, static), (1.0, spectrum)])
    assert set(out.bounds.upper) == {"node_disp"}
    assert out.missing_fields == ["element_forces"]
    # Vectors of different length combine over their common leading components.
    assert out.bounds.upper["node_disp"][1].shape == (3,)


def test_only_ids_every_term_has_are_combined() -> None:
    a = _single(node_reaction={1: [1.0], 2: [2.0]})
    b = _single(node_reaction={2: [5.0], 3: [1.0]})
    out = combine("LinearAdd", [(1.0, a), (1.0, b)])
    assert list(out.bounds.upper["node_reaction"]) == [2]


def test_combine_refuses_no_terms_and_unknown_types() -> None:
    with pytest.raises(ValueError, match="at least one"):
        combine("LinearAdd", [])
    with pytest.raises(ValueError, match="Unknown combination type"):
        combine("Product", [(1.0, _single(node_disp={1: [1.0]}))])


# ─────────────────────────── model ───────────────────────────
def _cases_project() -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(3, 0, 0))],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-4)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        analyses=[
            StaticCase(id=1, name="DEAD", pattern_ids=[1]),
            StaticCase(id=2, name="LIVE", pattern_ids=[2]),
            ModalCase(id=3, name="MODAL"),
            ResponseSpectrumCase(id=4, name="EQX", modal_case_id=3, spectrum_id=1, direction=1),
        ],
    )


def test_project_without_combinations_dumps_without_the_key() -> None:
    project = _cases_project()
    assert "combinations" not in json.loads(_project_json(project))
    project.combinations.append(
        LoadCombination(id=1, name="ULS", terms=[CombinationTerm(ref_id=1)])
    )
    dumped = json.loads(_project_json(project))
    assert dumped["combinations"] == [
        {
            "id": 1,
            "name": "ULS",
            "combination_type": "LinearAdd",
            "terms": [{"ref_id": 1, "factor": 1.0}],
        }
    ]


def test_combinations_round_trip_through_a_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    project = _cases_project()
    project.combinations += [
        LoadCombination(
            id=1,
            name="ULS",
            terms=[CombinationTerm(ref_id=1, factor=1.2), CombinationTerm(ref_id=2, factor=1.6)],
        ),
        LoadCombination(
            id=2,
            name="ENV",
            combination_type="Envelope",
            terms=[CombinationTerm(source="combination", ref_id=1)],
        ),
    ]
    path = save_project(project, tmp_path / "combo.osmodel")
    loaded = load_project(path)
    assert loaded.combinations == project.combinations
    assert loaded.combination(2).terms[0].source == "combination"


def test_model_rejects_duplicate_ids_and_non_finite_factors() -> None:
    with pytest.raises(ValidationError, match="Duplicate load combination ids"):
        Project(combinations=[LoadCombination(id=1), LoadCombination(id=1)])
    with pytest.raises(ValidationError, match="finite"):
        CombinationTerm(ref_id=1, factor=float("inf"))
    with pytest.raises(ValidationError):
        LoadCombination(id=1, combination_type="Product")


def test_nested_combinations_resolve_in_dependency_order() -> None:
    project = _cases_project()
    project.combinations += [
        LoadCombination(
            id=1, name="A", terms=[CombinationTerm(ref_id=2), CombinationTerm(ref_id=1)]
        ),
        LoadCombination(id=2, name="B", terms=[CombinationTerm(ref_id=1, factor=0.9)]),
        LoadCombination(
            id=3,
            name="ENV",
            combination_type="Envelope",
            terms=[
                CombinationTerm(source="combination", ref_id=1),
                CombinationTerm(source="combination", ref_id=2),
            ],
        ),
    ]
    assert combination_order(project, 3) == [1, 2, 3]
    assert required_case_ids(project, 3) == [2, 1]
    assert combination_problems(project, project.combination(3)) == []
    assert [c.id for c in combinations_using_case(project, 1)] == [1, 2]


def test_a_cycle_of_combinations_is_refused() -> None:
    project = _cases_project()
    project.combinations += [
        LoadCombination(id=1, name="A", terms=[CombinationTerm(source="combination", ref_id=2)]),
        LoadCombination(id=2, name="B", terms=[CombinationTerm(source="combination", ref_id=1)]),
    ]
    with pytest.raises(ValueError, match="include each other"):
        combination_order(project, 1)
    assert any(
        "include each other" in p for p in combination_problems(project, project.combination(1))
    )


def test_problems_name_missing_and_non_combinable_cases() -> None:
    project = _cases_project()
    combo = LoadCombination(
        id=1,
        name="BAD",
        terms=[
            CombinationTerm(ref_id=9),
            CombinationTerm(ref_id=3),
            CombinationTerm(source="combination", ref_id=5),
        ],
    )
    project.combinations.append(combo)
    problems = "\n".join(combination_problems(project, combo))
    assert "missing analysis case 9" in problems
    assert "Modal case 'MODAL'" in problems
    assert "missing combination 5" in problems
    empty = LoadCombination(id=2, name="EMPTY")
    assert combination_problems(project, empty) == ["Combination 'EMPTY' includes no case."]


def test_adding_a_possibly_nonlinear_case_warns_but_an_envelope_does_not() -> None:
    project = _cases_project()
    combo = LoadCombination(
        id=1, name="ULS", terms=[CombinationTerm(ref_id=1), CombinationTerm(ref_id=2)]
    )
    assert superposition_warnings(project, combo) == []
    project.analyses[1] = project.analyses[1].model_copy(update={"algorithm": "Newton"})
    warnings = superposition_warnings(project, combo)
    assert len(warnings) == 1
    assert "'LIVE'" in warnings[0] and "Newton" in warnings[0] and "superposition" in warnings[0]
    envelope = combo.model_copy(update={"combination_type": "Envelope"})
    assert superposition_warnings(project, envelope) == []
    project.elements[0] = project.elements[0].model_copy(update={"geom_transf": "PDelta"})
    project.analyses[1] = project.analyses[1].model_copy(update={"algorithm": "Linear"})
    assert all("PDelta" in w for w in superposition_warnings(project, combo))


def test_fingerprint_ignores_combinations_and_display_but_not_the_model() -> None:
    project = _cases_project()
    before = model_fingerprint(project)
    project.combinations.append(LoadCombination(id=1, terms=[CombinationTerm(ref_id=1)]))
    project.meta.name = "Renamed"
    project.meta.display_units = UnitSystem.US_IN_KIP
    assert model_fingerprint(project) == before
    project.nodes[1] = project.nodes[1].model_copy(update={"coords": (4.0, 0.0, 0.0)})
    assert model_fingerprint(project) != before


# ─────────────────────── ASCE 7-16 generator ───────────────────────
def _as_dict(generated):  # type: ignore[no-untyped-def]
    return {name: {t.ref_id: t.factor for t in terms} for name, terms in generated}


def test_asce_needs_dead_load() -> None:
    assert asce7_16_lrfd({"L": [2]}) == []
    assert _as_dict(asce7_16_lrfd({"D": [1]})) == {"1.4D": {1: 1.4}}


def test_asce_dead_and_live() -> None:
    assert _as_dict(asce7_16_lrfd({"D": [1], "L": [2]})) == {
        "1.4D": {1: 1.4},
        "1.2D+1.6L": {1: 1.2, 2: 1.6},
    }


def test_asce_full_set_with_wind_both_ways() -> None:
    combos = _as_dict(asce7_16_lrfd({"D": [1, 5], "L": [2], "Lr": [3], "W": [4]}))
    assert combos["1.4D"] == {1: 1.4, 5: 1.4}
    assert combos["1.2D+1.6L+0.5Lr"] == {1: 1.2, 5: 1.2, 2: 1.6, 3: 0.5}
    assert combos["1.2D+1.6Lr+L"] == {1: 1.2, 5: 1.2, 3: 1.6, 2: 1.0}
    assert combos["1.2D+1.6Lr-0.5W"] == {1: 1.2, 5: 1.2, 3: 1.6, 4: -0.5}
    assert combos["1.2D+W+L+0.5Lr"] == {1: 1.2, 5: 1.2, 4: 1.0, 2: 1.0, 3: 0.5}
    assert combos["0.9D-W"] == {1: 0.9, 5: 0.9, 4: -1.0}
    # 1.4D; one 2; three 3 (L, +0.5W, -0.5W); two 4; two 6.
    assert len(combos) == 9


def test_asce_earthquake_with_snow_and_two_directions() -> None:
    combos = _as_dict(asce7_16_lrfd({"D": [1], "S": [2], "E": [3, 4]}))
    assert combos["1.2D+E3+0.2S"] == {1: 1.2, 3: 1.0, 2: 0.2}
    assert combos["1.2D-E4+0.2S"] == {1: 1.2, 4: -1.0, 2: 0.2}
    assert combos["0.9D+E3"] == {1: 0.9, 3: 1.0}
    assert "1.2D+1.6S" in combos


# ─────────────────────── result adapter ───────────────────────
def _static(case_id: int, forces: list[float], disp: list[float]) -> StaticResults:
    return StaticResults(
        case_id=case_id,
        case_name=f"case {case_id}",
        n_steps=2,
        node_disp={1: np.zeros((2, 3)), 2: np.array([[0.0, 0.0, 0.0], disp])},
        node_reaction={1: np.array([[0.0, 0.0, 0.0], [-d for d in disp]])},
        element_forces={1: np.array([[0.0] * 6, forces])},
    )


def _combo_project(combination_type: str = "LinearAdd") -> Project:
    project = _cases_project()
    project.combinations.append(
        LoadCombination(
            id=1,
            name="C1",
            combination_type=combination_type,
            terms=[CombinationTerm(ref_id=1, factor=1.2), CombinationTerm(ref_id=2, factor=1.6)],
        )
    )
    return project


def test_linear_add_of_static_results_sums_the_final_step() -> None:
    project = _combo_project()
    a = _static(1, [1.0, 2.0, 3.0, -1.0, -2.0, 4.0], [0.1, 0.2, 0.01])
    b = _static(2, [5.0, -1.0, 0.0, -5.0, 1.0, 2.0], [0.3, -0.1, 0.0])
    out = combine_results(project, 1, {1: a, 2: b})
    assert out.single_valued and out.case_ids == [1, 2] and out.warnings == []
    for bound in (out.max, out.min):
        assert bound.n_steps == 1
        np.testing.assert_allclose(
            bound.element_forces[1][0],
            1.2 * a.element_forces[1][-1] + 1.6 * b.element_forces[1][-1],
        )
        np.testing.assert_allclose(
            bound.node_disp[2][0], 1.2 * a.node_disp[2][-1] + 1.6 * b.node_disp[2][-1]
        )


def test_envelope_diagram_is_the_envelope_of_the_case_diagrams() -> None:
    project = _combo_project("Envelope")
    a = _static(1, [1.0, 2.0, 3.0, -1.0, -2.0, 4.0], [0.1, 0.2, 0.01])
    b = _static(2, [5.0, -1.0, 0.0, -5.0, 1.0, -7.0], [0.3, -0.1, 0.0])
    out = combine_results(project, 1, {1: a, 2: b})
    assert not out.single_valued
    for comp in (ForceComponent.N, ForceComponent.V2, ForceComponent.M3):
        da = extract_diagram_data(project, a, comp)
        db = extract_diagram_data(project, b, comp)
        dmax = extract_diagram_data(project, out.max, comp)
        dmin = extract_diagram_data(project, out.min, comp)
        for end in ("values_i", "values_j"):
            va, vb = 1.2 * getattr(da, end), 1.6 * getattr(db, end)
            np.testing.assert_allclose(getattr(dmax, end), np.maximum(va, vb))
            np.testing.assert_allclose(getattr(dmin, end), np.minimum(va, vb))
    both = envelope_diagram_data(project, out.max, out.min, ForceComponent.M3)
    assert list(both.element_ids) == [1, 1]
    assert both.abs_max == pytest.approx(max(abs(1.6 * 7.0), 1.2 * 4.0, 1.2 * 3.0))


def test_spectrum_result_without_forces_leaves_them_out_and_says_to_rerun() -> None:
    project = _cases_project()
    project.combinations.append(
        LoadCombination(
            id=1, name="D+E", terms=[CombinationTerm(ref_id=1), CombinationTerm(ref_id=4)]
        )
    )
    static = _static(1, [1.0] * 6, [0.1, 0.2, 0.01])
    spectrum = ResponseSpectrumResults(
        case_id=4,
        case_name="EQX",
        direction=1,
        combination="CQC",
        combined_disp={1: np.zeros(3), 2: np.array([0.05, 0.02, 0.001])},
        warnings=["closely spaced"],
    )
    assert set(case_bounds(project, spectrum).upper) == {"node_disp"}
    out = combine_results(project, 1, {1: static, 4: spectrum})
    np.testing.assert_allclose(out.max.node_disp[2][0], [0.15, 0.22, 0.011])
    np.testing.assert_allclose(out.min.node_disp[2][0], [0.05, 0.18, 0.009])
    assert out.max.element_forces == {} and out.max.node_reaction == {}
    assert set(out.missing_fields) == {"node_reaction", "element_forces"}
    assert any("run the case again" in w for w in out.warnings)
    assert "closely spaced" in out.warnings
    tabs = combination_tables(out, project)
    assert [name for name, _ in tabs] == ["Displacements"]
    disp = tabs[0][1]
    assert disp.columns[:2] == ["Node", "Bound"]
    assert [row[:2] for row in disp.rows] == [[1, "Max"], [1, "Min"], [2, "Max"], [2, "Min"]]


def test_spectrum_case_with_forces_gives_peak_bounds_for_every_field() -> None:
    project = _cases_project()
    project.combinations.append(
        LoadCombination(
            id=1,
            name="D+E",
            terms=[CombinationTerm(ref_id=1), CombinationTerm(ref_id=4, factor=2.0)],
        )
    )
    static = _static(1, [1.0, 2.0, 3.0, -1.0, -2.0, 4.0], [0.1, 0.2, 0.01])
    spectrum = ResponseSpectrumResults(
        case_id=4,
        case_name="EQX",
        direction=1,
        combination="CQC",
        combined_disp={1: np.zeros(3), 2: np.array([0.05, 0.02, 0.001])},
        node_reaction={1: np.array([10.0, 0.0, 5.0])},
        element_forces={1: np.array([0.5, 1.5, 2.5, 0.5, 1.5, 2.5])},
    )
    bounds = case_bounds(project, spectrum)
    assert set(bounds.upper) == {"node_disp", "node_reaction", "element_forces"}
    np.testing.assert_allclose(bounds.lower["node_reaction"][1], [-10.0, 0.0, -5.0])
    out = combine_results(project, 1, {1: static, 4: spectrum})
    assert out.missing_fields == [] and not out.single_valued
    # Static reaction -disp = [-0.1, -0.2, -0.01]; the spectrum adds and subtracts 2 x peak.
    np.testing.assert_allclose(out.max.node_reaction[1][0], [19.9, -0.2, 9.99])
    np.testing.assert_allclose(out.min.node_reaction[1][0], [-20.1, -0.2, -10.01])
    np.testing.assert_allclose(
        np.abs(out.max.element_forces[1][0] - out.min.element_forces[1][0]),
        4.0 * np.array([0.5, 1.5, 2.5, 0.5, 1.5, 2.5]),
    )


def test_combining_without_a_needed_result_names_the_cases() -> None:
    project = _combo_project()
    with pytest.raises(MissingCaseResultsError) as info:
        combine_results(project, 1, {1: _static(1, [0.0] * 6, [0.0] * 3)})
    assert info.value.case_ids == [2]


def test_combining_a_broken_combination_raises_its_problems() -> None:
    project = _cases_project()
    project.combinations.append(LoadCombination(id=1, name="M", terms=[CombinationTerm(ref_id=3)]))
    with pytest.raises(ValueError, match="only Static and ResponseSpectrum"):
        combine_results(project, 1, {})


def test_envelope_tables_give_local_force_max_and_min() -> None:
    project = _combo_project("Envelope")
    a = _static(1, [1.0, 2.0, 3.0, -1.0, -2.0, 4.0], [0.1, 0.2, 0.01])
    b = _static(2, [5.0, -1.0, 0.0, -5.0, 1.0, -7.0], [0.3, -0.1, 0.0])
    out = combine_results(project, 1, {1: a, 2: b})
    tabs = dict(combination_tables(out, project))
    forces = tabs["Element forces"]
    assert forces.columns == ["Element", "Type", "Component", "Unit", "Max", "Min"]
    raw_a, raw_b = 1.2 * a.element_forces[1][-1], 1.6 * b.element_forces[1][-1]
    np.testing.assert_allclose([r[4] for r in forces.rows], np.maximum(raw_a, raw_b))
    np.testing.assert_allclose([r[5] for r in forces.rows], np.minimum(raw_a, raw_b))
    single = dict(combination_tables(combine_results(_combo_project(), 1, {1: a, 2: b}), project))
    assert single["Element forces"].columns == ["Element", "Type", "Component", "Unit", "Value"]


def test_asce_spectrum_case_gets_one_sign() -> None:
    combos = _as_dict(asce7_16_lrfd({"D": [1], "E": [7]}, peak_cases=[7]))
    assert set(combos) == {"1.4D", "1.2D+E", "0.9D+E"}


@pytest.mark.parametrize(
    ("name", "role"),
    [
        ("DEAD", "D"),
        ("dl", "D"),
        ("Live", "L"),
        ("ROOF LIVE", "Lr"),
        ("Snow", "S"),
        ("WX", "W"),
        ("Wind 0deg", "W"),
        ("EQ-X", "E"),
        ("EY", "E"),
        ("MODAL", None),
        ("", None),
    ],
)
def test_guess_load_role_from_case_names(name: str, role: str | None) -> None:
    assert guess_load_role(name) == role


def test_envelope_diagram_keeps_the_flexible_ends_of_offset_members() -> None:
    from opensees_studio.core.geometry.frame_options import FrameEndOffsets

    project = _combo_project("Envelope")
    project.elements[0] = project.elements[0].model_copy(
        update={"end_offsets": FrameEndOffsets(length_i=0.3, length_j=0.2)}
    )
    a = _static(1, [1.0, 2.0, 3.0, -1.0, -2.0, 4.0], [0.1, 0.2, 0.01])
    b = _static(2, [5.0, -1.0, 0.0, -5.0, 1.0, -7.0], [0.3, -0.1, 0.0])
    out = combine_results(project, 1, {1: a, 2: b})
    both = envelope_diagram_data(project, out.max, out.min, ForceComponent.M3)
    single = extract_diagram_data(project, a, ForceComponent.M3)
    assert set(both.ends) == {1}
    np.testing.assert_allclose(both.ends[1][0], single.ends[1][0])
    np.testing.assert_allclose(both.ends[1][1], single.ends[1][1])
