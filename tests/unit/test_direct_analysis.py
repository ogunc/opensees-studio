"""AISC design basis and the Direct Analysis Method cases, without a solver.

The steel grades, the new design settings and static case options (absent from a
file until used), the cases generated for the ASCE 7 LRFD combinations, the
factored gravity and notional loads of a case, the model a case runs on, and
Δ2/Δ1 from given displacements.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    ElasticUniaxial,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    ResponseSpectrumCase,
    StaticCase,
    Steel01,
    TrussElement,
    UniformElementLoad,
    UnitSystem,
)
from opensees_studio.core.analysis import DirectAnalysisTag
from opensees_studio.core.design.direct_analysis import (
    STIFFNESS_REDUCTION,
    analysis_model,
    case_gravity,
    case_notional_loads,
    direct_analysis_cases,
    drift_ratios,
    notional_everywhere_required,
    pattern_forces,
)
from opensees_studio.core.design.settings import DesignSettings, SteelMemberDesign
from opensees_studio.core.design.steel_grades import (
    DEFAULT_GRADES,
    STEEL_GRADES,
    grade_stresses,
)
from opensees_studio.core.loads import TrapezoidalElementLoad
from opensees_studio.services import load_project, save_project

KIP_IN = UnitSystem.US_IN_KIP
FIX_2D = (True, False, True, False, True, False)
P_DEAD, P_LIVE, H_WIND = 200.0, 100.0, 20.0


def _portal(ndm: int = 2) -> Project:
    """One-bay portal, 240 in by 144 in: dead and live at the top joints, wind at node 3."""
    fix = FIX_2D if ndm == 2 else (True,) * 6
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=fix),
        Node(id=2, coords=(240.0, 0.0, 0.0), restraint=fix),
        Node(id=3, coords=(0.0, 0.0, 144.0)),
        Node(id=4, coords=(240.0, 0.0, 144.0)),
    ]
    extra = {"Iy": 362.0, "G": 11200.0, "J": 4.06} if ndm == 3 else {}
    column = ElasticSection(id=1, name="W14X90", E=29000.0, A=26.5, Iz=999.0, **extra)
    beam = ElasticSection(id=2, name="W24X68", E=29000.0, A=20.1, Iz=1830.0, **extra)

    def down(p: float) -> list[NodalLoad]:
        return [NodalLoad(node_id=n, forces=(0.0, 0.0, -p, 0.0, 0.0, 0.0)) for n in (3, 4)]

    return Project(
        meta=ProjectMeta(units=KIP_IN),
        ndm=ndm,
        ndf=3 if ndm == 2 else 6,
        nodes=nodes,
        sections=[column, beam],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 3), section_id=1),
            ElasticBeamColumn(id=2, nodes=(2, 4), section_id=1),
            ElasticBeamColumn(id=3, nodes=(3, 4), section_id=2),
        ],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(id=1, name="DEAD", time_series_id=1, nodal_loads=down(P_DEAD)),
            PlainLoadPattern(id=2, name="LIVE", time_series_id=1, nodal_loads=down(P_LIVE)),
            PlainLoadPattern(
                id=3,
                name="WIND",
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=3, forces=(H_WIND, 0.0, 0.0, 0.0, 0.0, 0.0))],
            ),
        ],
        analyses=[
            StaticCase(id=1, name="DEAD", pattern_ids=[1]),
            StaticCase(id=2, name="LIVE", pattern_ids=[2]),
            StaticCase(id=3, name="WIND", pattern_ids=[3]),
        ],
    )


ROLES = {"D": [1], "L": [2], "W": [3]}


# ─────────────────────────── steel grades ───────────────────────────
def test_a36_and_a572_gr50_are_offered_with_their_astm_stresses() -> None:
    assert grade_stresses("A36", "W", KIP_IN) == (36.0, 58.0)
    assert grade_stresses("A572-50", "W", KIP_IN) == (50.0, 65.0)
    assert STEEL_GRADES["A36"].ry == 1.5
    assert STEEL_GRADES["A572-50"].ry == 1.1


def test_a500_round_sections_take_their_own_yield_stress() -> None:
    assert grade_stresses("A500-C", "HSS", KIP_IN) == (50.0, 62.0)
    assert grade_stresses("A500-C", "HSS_R", KIP_IN) == (46.0, 62.0)
    assert grade_stresses("A53-B", "PIPE", KIP_IN) == (35.0, 60.0)


def test_grades_convert_to_the_project_units() -> None:
    fy, fu = grade_stresses("A36", "L", UnitSystem.SI_M_N)
    assert fy == pytest.approx(248.2e6, rel=1e-3)
    assert fu == pytest.approx(399.9e6, rel=1e-3)


def test_manual_defaults_cover_every_checked_family_with_a_known_grade() -> None:
    assert DEFAULT_GRADES["W"] == "A992"
    assert DEFAULT_GRADES["L"] == DEFAULT_GRADES["C"] == "A36"
    assert DEFAULT_GRADES["HSS"] == "A500-C"
    assert set(DEFAULT_GRADES.values()) <= set(STEEL_GRADES)


# ─────────────────────────── saved settings ───────────────────────────
def test_new_design_basis_fields_save_only_when_used(tmp_path: Path) -> None:
    project = Project()
    project.design = DesignSettings()
    path = save_project(project, tmp_path / "plain.osmodel")
    assert json.loads(path.read_text(encoding="utf-8"))["design"] == {"code": "AISC 360-16"}

    project.design = DesignSettings(
        stability_method="direct",
        seismic_system="EBF",
        seismic_system_y="SMF",
        sds=0.9,
        steel_grades={"W": "A572-50", "L": "A36"},
        members=[SteelMemberDesign(element_id=2, grade="A36")],
    )
    path = save_project(project, tmp_path / "basis.osmodel")
    saved = json.loads(path.read_text(encoding="utf-8"))["design"]
    assert saved["stability_method"] == "direct"
    assert saved["steel_grades"] == {"W": "A572-50", "L": "A36"}
    assert saved["members"] == [{"element_id": 2, "grade": "A36"}]
    assert load_project(path).design == project.design


def test_omega0_is_the_larger_of_the_two_directions() -> None:
    assert DesignSettings().omega0() is None
    assert DesignSettings(seismic_system="SCBF").omega0() == 2.0
    assert DesignSettings(seismic_system="SCBF", seismic_system_y="SMF").omega0() == 3.0


def test_static_case_options_save_only_when_used() -> None:
    plain = StaticCase(id=1, pattern_ids=[1]).model_dump(mode="json")
    for key in ("pattern_factors", "p_delta", "stiffness_factor", "notional_ratio"):
        assert key not in plain
    tagged = StaticCase(
        id=2,
        pattern_ids=[1, 2],
        pattern_factors=[1.2, 1.6],
        p_delta=True,
        stiffness_factor=0.8,
        notional_ratio=0.003,
        notional_direction="-X",
        direct_analysis=DirectAnalysisTag(combination="1.2D+1.6L"),
    )
    dumped = tagged.model_dump(mode="json")
    assert dumped["direct_analysis"] == {"combination": "1.2D+1.6L"}
    assert StaticCase.model_validate(dumped) == tagged


def test_one_factor_per_pattern_is_required() -> None:
    with pytest.raises(ValueError, match="one per pattern"):
        StaticCase(id=1, pattern_ids=[1, 2], pattern_factors=[1.2])


# ─────────────────────────── generated cases ───────────────────────────
def test_every_lrfd_combination_becomes_one_second_order_case() -> None:
    project = _portal()
    out = direct_analysis_cases(project, DesignSettings(), ROLES, first_id=10)
    names = [c.name for c in out.cases]
    assert names == [
        "DAM 1.4D N+X",
        "DAM 1.4D N-X",
        "DAM 1.2D+1.6L N+X",
        "DAM 1.2D+1.6L N-X",
        "DAM 1.2D+W+L",
        "DAM 1st-order 1.2D+W+L",
        "DAM 1.2D-W+L",
        "DAM 1st-order 1.2D-W+L",
        "DAM 0.9D+W",
        "DAM 1st-order 0.9D+W",
        "DAM 0.9D-W",
        "DAM 1st-order 0.9D-W",
    ]
    assert [c.id for c in out.cases] == list(range(10, 22))
    gravity = out.cases[2]
    assert gravity.pattern_ids == [1, 2] and gravity.pattern_factors == [1.2, 1.6]
    assert gravity.p_delta and gravity.stiffness_factor == STIFFNESS_REDUCTION
    assert gravity.algorithm == "Newton" and gravity.n_steps == 10
    # Gravity-only: 0.002 (C2-1) + 0.001 (C2.3(c)); lateral: 0.001 while Δ2/Δ1 <= 1.7.
    assert gravity.notional_ratio == pytest.approx(0.003)
    lateral = out.cases[6]
    assert lateral.pattern_factors == [1.2, -1.0, 1.0]
    assert lateral.notional_ratio == pytest.approx(0.001)
    assert lateral.notional_direction == "-X"
    twin = out.cases[7]
    assert twin.direct_analysis.order == "first"
    assert not twin.p_delta and twin.algorithm == "Linear"
    assert twin.stiffness_factor == STIFFNESS_REDUCTION
    assert len(out.strength_cases) == 8


def test_notional_loads_everywhere_when_asked() -> None:
    out = direct_analysis_cases(
        _portal(), DesignSettings(), ROLES, first_id=1, notional_everywhere=True
    )
    lateral = next(c for c in out.cases if c.direct_analysis.lateral)
    assert lateral.notional_ratio == pytest.approx(0.003)


def test_a_3d_model_gets_notional_loads_in_both_horizontal_directions() -> None:
    out = direct_analysis_cases(_portal(ndm=3), DesignSettings(), ROLES, first_id=1)
    directions = [c.notional_direction for c in out.cases if c.name.startswith("DAM 1.4D")]
    assert directions == ["+X", "-X", "+Y", "-Y"]


def test_a_seismic_system_adds_the_overstrength_combinations() -> None:
    project = _portal()
    project.analyses[2] = project.analyses[2].model_copy(update={"name": "EQX"})
    settings = DesignSettings(seismic_system="SMF", sds=1.0)
    out = direct_analysis_cases(project, settings, {"D": [1], "L": [2], "E": [3]}, first_id=1)
    omega = [c for c in out.cases if c.direct_analysis.overstrength]
    assert omega
    first = next(c for c in omega if c.direct_analysis.order == "second")
    assert first.pattern_factors[first.pattern_ids.index(3)] == pytest.approx(3.0)
    assert first.pattern_factors[first.pattern_ids.index(1)] == pytest.approx(1.4)


def test_asd_and_a_missing_dead_load_are_refused() -> None:
    with pytest.raises(ValueError, match="LRFD"):
        direct_analysis_cases(_portal(), DesignSettings(method="ASD"), ROLES, first_id=1)
    with pytest.raises(ValueError, match="dead load"):
        direct_analysis_cases(_portal(), DesignSettings(), {"L": [2]}, first_id=1)


def test_a_response_spectrum_case_is_left_out_with_a_note() -> None:
    project = _portal()
    project.analyses.append(
        ResponseSpectrumCase.model_construct(id=9, name="RSX", type="ResponseSpectrum")
    )
    out = direct_analysis_cases(project, DesignSettings(), {"D": [1], "E": [9]}, first_id=20)
    assert all("E" not in c.direct_analysis.combination for c in out.cases)
    assert any("response spectrum" in note for note in out.notes)


# ─────────────────────────── loads of a case ───────────────────────────
def test_case_gravity_is_the_factored_downward_load() -> None:
    project = _portal()
    case = StaticCase(id=1, pattern_ids=[1, 2, 3], pattern_factors=[1.2, 1.6, 1.0])
    weights = case_gravity(project, case)
    assert weights == {3: pytest.approx(400.0), 4: pytest.approx(400.0)}


def test_notional_loads_are_ratio_times_the_factored_storey_gravity() -> None:
    project = _portal()
    case = StaticCase(
        id=1,
        pattern_ids=[1, 2],
        pattern_factors=[1.2, 1.6],
        notional_ratio=0.003,
        notional_direction="-X",
    )
    loads, storeys = case_notional_loads(project, case)
    assert [s.gravity for s in storeys] == [pytest.approx(800.0)]
    assert storeys[0].force == pytest.approx(2.4)
    assert sorted(load.forces[0] for load in loads) == [pytest.approx(-1.2)] * 2


def test_a_2d_model_refuses_notional_loads_along_y() -> None:
    case = StaticCase(id=1, pattern_ids=[1], notional_ratio=0.002, notional_direction="+Y")
    with pytest.raises(ValueError, match="X only"):
        case_notional_loads(_portal(), case)


def test_member_loads_count_with_the_lever_rule() -> None:
    project = _portal()
    uniform = PlainLoadPattern(
        id=7,
        time_series_id=1,
        element_loads=[UniformElementLoad(element_id=3, wy=-0.5)],
    )
    trapezoid = PlainLoadPattern(
        id=8,
        time_series_id=1,
        distributed_loads=[
            TrapezoidalElementLoad(element_id=3, wy_start=-0.5, wy_end=-0.5),
            TrapezoidalElementLoad(element_id=3, x_start=0.0, x_end=0.5, wy_start=-1.0, wy_end=0.0),
        ],
    )
    forces = pattern_forces(project, uniform)
    assert forces[3][2] == pytest.approx(-60.0) and forces[4][2] == pytest.approx(-60.0)
    forces = pattern_forces(project, trapezoid)
    # Uniform part 60 + 60; the triangle (60 in all) has its centroid at L/6.
    assert forces[3][2] == pytest.approx(-60.0 - 50.0)
    assert forces[4][2] == pytest.approx(-60.0 - 10.0)


# ─────────────────────────── the model a case runs on ───────────────────────────
def test_analysis_model_switches_to_p_delta_and_scales_elastic_stiffness() -> None:
    project = _portal()
    project.materials = [ElasticUniaxial(id=5, E=29000.0), Steel01(id=6, Fy=50, E0=29000, b=0.01)]
    project.elements += [
        TrussElement(id=4, nodes=(1, 4), area=5.0, material_id=5),
        TrussElement(id=5, nodes=(2, 3), area=5.0, material_id=6),
    ]
    model, notes = analysis_model(project, p_delta=True, stiffness_factor=0.8)
    assert {el.geom_transf for el in model.elements[:3]} == {"PDelta"}
    assert [s.E for s in model.sections] == [pytest.approx(23200.0)] * 2
    brace = next(el for el in model.elements if el.id == 4)
    copy = next(m for m in model.materials if m.id == brace.material_id)
    assert copy.id != 5
    assert pytest.approx(23200.0) == copy.E
    assert any("Not reduced: member(s) 5" in n for n in notes)
    # The project itself is untouched.
    assert project.elements[0].geom_transf == "Linear"
    assert project.sections[0].E == 29000.0
    assert project.elements[3].material_id == 5


# ─────────────────────────── Δ2/Δ1 ───────────────────────────
def test_drift_ratios_compare_storey_drifts_along_the_case_direction() -> None:
    project = _portal()
    case = StaticCase(
        id=1,
        pattern_ids=[3],
        notional_direction="+X",
        direct_analysis=DirectAnalysisTag(combination="0.9D+W", lateral=True),
    )

    def disp(u: float) -> dict[int, np.ndarray]:
        return {1: np.zeros(3), 2: np.zeros(3), 3: np.array([u, 0, 0]), 4: np.array([u, 0, 0])}

    rows = drift_ratios(project, case, disp(0.10), disp(0.18))
    assert len(rows) == 1
    assert rows[0].ratio == pytest.approx(1.8)
    assert notional_everywhere_required(rows)
    rows = drift_ratios(project, case, disp(0.10), disp(0.12))
    assert not notional_everywhere_required(rows)
