"""Unit tests for Project — the root aggregate."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from opensees_studio.core import (
    AggregatorDOF,
    ElasticBeamColumn,
    ElasticSection,
    FiberSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    RectangularPatch,
    SectionAggregator,
    Steel01,
    StraightLayer,
    TrussElement,
    UnitSystem,
)


# ────────────────────────── construction ──────────────────────────
def test_empty_project_is_valid() -> None:
    p = Project()
    assert p.schema_version == 1
    assert p.ndm == 3 and p.ndf == 6
    assert p.nodes == []
    assert p.meta.units == UnitSystem.SI_M_N


def test_invalid_ndm_ndf_pair_rejected() -> None:
    with pytest.raises(ValidationError):
        Project(ndm=2, ndf=6)
    with pytest.raises(ValidationError):
        Project(ndm=3, ndf=2)


def test_meta_round_trip() -> None:
    p = Project(meta=ProjectMeta(name="Bridge", author="Ozan", units=UnitSystem.SI_MM_N))
    assert p.meta.name == "Bridge"
    assert p.meta.units == UnitSystem.SI_MM_N


# ────────────────────────── id allocation ──────────────────────────
def test_next_id_starts_at_one_when_empty() -> None:
    p = Project()
    assert p.next_node_id() == 1
    assert p.next_element_id() == 1


def test_next_id_increments_above_max() -> None:
    p = Project(
        nodes=[
            Node(id=1, coords=(0, 0, 0)),
            Node(id=5, coords=(1, 0, 0)),
            Node(id=3, coords=(0, 1, 0)),
        ]
    )
    assert p.next_node_id() == 6


def test_duplicate_node_ids_rejected() -> None:
    with pytest.raises(ValidationError):
        Project(nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=1, coords=(1, 0, 0))])


# ────────────────────────── lookups ──────────────────────────
def test_node_lookup() -> None:
    n = Node(id=7, coords=(1, 2, 3))
    p = Project(nodes=[n])
    assert p.node(7) is n


def test_lookup_missing_raises_key_error() -> None:
    p = Project()
    with pytest.raises(KeyError, match="Node"):
        p.node(99)


# ────────────────────────── reference validation ──────────────────────────
def test_validate_references_passes_on_consistent_model() -> None:
    p = Project(
        nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(1, 0, 0))],
        materials=[Steel01(id=1, Fy=420e6, E0=200e9, b=0.01)],
        elements=[TrussElement(id=1, nodes=(1, 2), area=0.01, material_id=1)],
    )
    p.validate_references()  # no exception expected


def test_validate_references_catches_missing_node() -> None:
    p = Project(
        nodes=[Node(id=1, coords=(0, 0, 0))],
        materials=[Steel01(id=1, Fy=420e6, E0=200e9, b=0.01)],
        elements=[TrussElement(id=1, nodes=(1, 99), area=0.01, material_id=1)],
    )
    with pytest.raises(ValueError, match="missing node 99"):
        p.validate_references()


def test_validate_references_catches_missing_material() -> None:
    p = Project(
        nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(1, 0, 0))],
        elements=[TrussElement(id=1, nodes=(1, 2), area=0.01, material_id=99)],
    )
    with pytest.raises(ValueError, match="missing material 99"):
        p.validate_references()


def test_validate_references_catches_missing_section_in_frame() -> None:
    p = Project(
        nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(1, 0, 0))],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=42)],
    )
    with pytest.raises(ValueError, match="missing section 42"):
        p.validate_references()


def test_validate_references_catches_missing_time_series_in_pattern() -> None:
    p = Project(
        nodes=[Node(id=1, coords=(0, 0, 0))],
        load_patterns=[
            PlainLoadPattern(
                id=1, time_series_id=99,
                nodal_loads=[NodalLoad(node_id=1, forces=(0, 0, -10, 0, 0, 0))],
            )
        ],
    )
    with pytest.raises(ValueError, match="missing time series 99"):
        p.validate_references()


def test_validate_references_catches_missing_material_in_fiber_patch() -> None:
    p = Project(
        materials=[Steel01(id=1, Fy=420e6, E0=200e9, b=0.01)],
        sections=[
            FiberSection(
                id=1,
                patches=[
                    RectangularPatch(
                        material_id=99, n_fib_y=2, n_fib_z=2,
                        y_i=-0.1, z_i=-0.1, y_j=0.1, z_j=0.1,
                    )
                ],
            )
        ],
    )
    with pytest.raises(ValueError, match="has a patch with missing material 99"):
        p.validate_references()


def test_validate_references_catches_missing_material_in_fiber_layer() -> None:
    p = Project(
        materials=[Steel01(id=1, Fy=420e6, E0=200e9, b=0.01)],
        sections=[
            FiberSection(
                id=1,
                layers=[
                    StraightLayer(
                        material_id=99, n_bars=3, bar_area=1e-4,
                        y_start=-0.1, z_start=-0.1, y_end=0.1, z_end=-0.1,
                    )
                ],
            )
        ],
    )
    with pytest.raises(ValueError, match="has a layer with missing material 99"):
        p.validate_references()


def test_validate_references_catches_missing_material_in_aggregator_pairing() -> None:
    # Base section exists, so only the dangling pairing material should be flagged.
    p = Project(
        sections=[
            ElasticSection(id=1, E=200e9, A=0.01, Iz=8.33e-6),
            SectionAggregator(
                id=2, section_id=1,
                pairings=[AggregatorDOF(material_id=99, dof="T")],
            ),
        ],
    )
    with pytest.raises(ValueError, match="aggregator pairing with missing material 99"):
        p.validate_references()


def test_validate_references_catches_missing_base_section_in_aggregator() -> None:
    # Pairing material exists, so only the dangling base section should be flagged.
    p = Project(
        materials=[Steel01(id=1, Fy=420e6, E0=200e9, b=0.01)],
        sections=[
            SectionAggregator(
                id=2, section_id=42,
                pairings=[AggregatorDOF(material_id=1, dof="T")],
            ),
        ],
    )
    with pytest.raises(ValueError, match="missing base section 42"):
        p.validate_references()


def test_validate_references_passes_on_valid_fiber_and_aggregator() -> None:
    p = Project(
        materials=[
            Steel01(id=1, Fy=420e6, E0=200e9, b=0.01),
            Steel01(id=2, Fy=420e6, E0=200e9, b=0.01),
        ],
        sections=[
            FiberSection(
                id=1,
                patches=[
                    RectangularPatch(
                        material_id=1, n_fib_y=2, n_fib_z=2,
                        y_i=-0.1, z_i=-0.1, y_j=0.1, z_j=0.1,
                    )
                ],
                layers=[
                    StraightLayer(
                        material_id=2, n_bars=3, bar_area=1e-4,
                        y_start=-0.1, z_start=-0.1, y_end=0.1, z_end=-0.1,
                    )
                ],
            ),
            SectionAggregator(
                id=2, section_id=1,
                pairings=[AggregatorDOF(material_id=1, dof="T")],
            ),
        ],
    )
    p.validate_references()  # no exception expected


# ────────────────────────── small smoke build ──────────────────────────
def test_full_truss_project_builds_and_validates() -> None:
    p = Project(
        ndm=2, ndf=2,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True, True, False, False, False, False)),
            Node(id=2, coords=(4, 0, 0), restraint=(False, True, False, False, False, False)),
            Node(id=3, coords=(2, 3, 0)),
        ],
        materials=[Steel01(id=1, Fy=420e6, E0=200e9, b=0.01)],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=8.33e-6)],
        elements=[
            TrussElement(id=1, nodes=(1, 3), area=1e-3, material_id=1),
            TrussElement(id=2, nodes=(2, 3), area=1e-3, material_id=1),
            TrussElement(id=3, nodes=(1, 2), area=1e-3, material_id=1),
        ],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1, time_series_id=1,
                nodal_loads=[NodalLoad(node_id=3, forces=(0, -1000, 0, 0, 0, 0))],
            )
        ],
    )
    p.validate_references()
    assert p.next_node_id() == 4
    assert p.next_element_id() == 4
