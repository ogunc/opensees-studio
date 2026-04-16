"""Unit tests for Phase 8b additions:

- HystereticMaterial schema + round-trip
- BeamWithHingesElement schema (2D + 3D) + round-trip
- PushoverCase schema + round-trip
"""

from __future__ import annotations

import pytest

from opensees_studio.core import (
    BeamWithHingesElement,
    ElasticBeamColumn,
    ElasticSection,
    HystereticMaterial,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    PushoverCase,
    UnitSystem,
)
from opensees_studio.services import load_project, save_project


# ── HystereticMaterial ───────────────────────────────────────────────
def test_hysteretic_material_schema() -> None:
    mat = HystereticMaterial(
        id=1, name="HingeMat",
        s1p=100.0, e1p=0.001, s2p=200.0, e2p=0.01, s3p=210.0, e3p=0.05,
        s1n=-100.0, e1n=-0.001, s2n=-200.0, e2n=-0.01, s3n=-210.0, e3n=-0.05,
    )
    assert mat.type == "Hysteretic"
    assert mat.s1p == 100.0
    assert mat.px == 1.0   # default pinching factor
    assert mat.beta == 0.0 # no degradation


def test_hysteretic_positive_envelope_must_be_positive() -> None:
    with pytest.raises(ValueError):
        HystereticMaterial(
            id=1, s1p=-1.0, e1p=0.001, s2p=200.0, e2p=0.01,
            s3p=210.0, e3p=0.05,
            s1n=-100.0, e1n=-0.001, s2n=-200.0, e2n=-0.01,
            s3n=-210.0, e3n=-0.05,
        )


# ── BeamWithHingesElement ────────────────────────────────────────────
def test_beam_with_hinges_3d_schema() -> None:
    el = BeamWithHingesElement(
        id=1, nodes=(1, 2),
        section_i_id=10, section_j_id=10,
        lp_i=0.1, lp_j=0.1,
        E=2e11, A=0.01, Iz=1e-5, Iy=1e-5, G=8e10, J=1e-6,
    )
    assert el.type == "BeamWithHinges"
    assert el.lp_i == 0.1
    assert el.geom_transf == "Linear"


def test_beam_with_hinges_2d_schema_has_optional_3d_fields() -> None:
    el = BeamWithHingesElement(
        id=1, nodes=(1, 2),
        section_i_id=10, section_j_id=10,
        lp_i=0.1, lp_j=0.1,
        E=2e11, A=0.01, Iz=1e-5,
    )
    assert el.Iy is None
    assert el.G is None
    assert el.J is None


# ── PushoverCase ─────────────────────────────────────────────────────
def test_pushover_case_schema() -> None:
    c = PushoverCase(
        id=1, pattern_ids=[1],
        control_node=2, control_dof=1,
        target_disp=0.1, step_size=0.001,
    )
    assert c.type == "Pushover"
    assert c.control_node == 2
    assert c.step_size == 0.001
    assert c.base_nodes == []   # defaults to empty → all supports


def test_pushover_case_round_trip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = Project(
        meta=ProjectMeta(name="PO test", units=UnitSystem.SI_M_N),
        ndm=3, ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(id=2, coords=(0, 0, 3.0),
                 mass=(1e3, 1e3, 1e3, 0, 0, 0)),
        ],
        materials=[
            HystereticMaterial(
                id=1, name="Hinge",
                s1p=100e3, e1p=0.001,
                s2p=150e3, e2p=0.01,
                s3p=160e3, e3p=0.05,
                s1n=-100e3, e1n=-0.001,
                s2n=-150e3, e2n=-0.01,
                s3n=-160e3, e3n=-0.05,
            ),
        ],
        sections=[
            ElasticSection(id=1, E=2e11, A=0.01, Iz=1e-5, Iy=1e-5,
                           G=8e10, J=1e-6),
        ],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
        ],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[PlainLoadPattern(
            id=1, time_series_id=1,
            nodal_loads=[NodalLoad(node_id=2, forces=(1.0, 0, 0, 0, 0, 0))],
        )],
        analyses=[PushoverCase(
            id=1, name="Push X",
            pattern_ids=[1],
            control_node=2, control_dof=1,
            target_disp=0.05, step_size=0.001,
            base_nodes=[1],
        )],
    )
    path = tmp_path / "po.osmodel"
    save_project(p, path)
    restored = load_project(path)

    case = restored.analyses[0]
    assert case.type == "Pushover"
    assert case.control_node == 2
    assert case.target_disp == 0.05
    assert case.base_nodes == [1]

    mat = restored.materials[0]
    assert isinstance(mat, HystereticMaterial)
    assert mat.s2p == 150e3


def test_beam_with_hinges_round_trip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = Project(
        meta=ProjectMeta(name="BWH", units=UnitSystem.SI_M_N),
        ndm=3, ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(id=2, coords=(0, 0, 3.0)),
        ],
        sections=[
            ElasticSection(id=10, E=2e11, A=0.01, Iz=1e-5, Iy=1e-5,
                           G=8e10, J=1e-6),
        ],
        elements=[
            BeamWithHingesElement(
                id=1, nodes=(1, 2),
                section_i_id=10, section_j_id=10,
                lp_i=0.3, lp_j=0.3,
                E=2e11, A=0.01, Iz=1e-5, Iy=1e-5, G=8e10, J=1e-6,
            ),
        ],
    )
    path = tmp_path / "bwh.osmodel"
    save_project(p, path)
    restored = load_project(path)

    el = restored.elements[0]
    assert isinstance(el, BeamWithHingesElement)
    assert el.lp_i == 0.3
    assert el.section_i_id == 10
