"""Unit tests for Phase 9 — Fiber sections + section properties."""

from __future__ import annotations

import math

import numpy as np
import pytest

from opensees_studio.core import (
    AggregatorDOF,
    CircularPatch,
    ElasticSection,
    FiberSection,
    Fibre,
    Project,
    RectangularPatch,
    SectionAggregator,
    StraightLayer,
)
from opensees_studio.services import load_project, save_project
from opensees_studio.services.section_properties import (
    compute_section_props,
    expand_fibres,
)


# ── RectangularPatch ─────────────────────────────────────────────────
def test_rectangular_patch_expands_to_correct_count() -> None:
    sec = FiberSection(
        id=1,
        patches=[RectangularPatch(
            material_id=1, n_fib_y=5, n_fib_z=4,
            y_i=-0.1, z_i=-0.1, y_j=0.1, z_j=0.1,
        )],
    )
    fibres = expand_fibres(sec)
    assert fibres.shape == (20, 3)
    # Total area = 0.2 × 0.2 = 0.04 m²
    assert np.sum(fibres[:, 2]) == pytest.approx(0.04, rel=1e-9)


def test_rectangular_patch_centroid_at_origin() -> None:
    sec = FiberSection(
        id=1,
        patches=[RectangularPatch(
            material_id=1, n_fib_y=8, n_fib_z=8,
            y_i=-0.15, z_i=-0.15, y_j=0.15, z_j=0.15,
        )],
    )
    props = compute_section_props(sec)
    assert props.centroid_y == pytest.approx(0.0, abs=1e-12)
    assert props.centroid_z == pytest.approx(0.0, abs=1e-12)


# ── CircularPatch ────────────────────────────────────────────────────
def test_circular_patch_area_approaches_pi_r_squared() -> None:
    r = 0.15
    sec = FiberSection(
        id=1,
        patches=[CircularPatch(
            material_id=1, n_fib_circ=32, n_fib_rad=8,
            r_inner=0.0, r_outer=r,
        )],
    )
    props = compute_section_props(sec)
    expected = math.pi * r ** 2
    # With 32×8 = 256 fibres, area should be close (within ~1%).
    assert props.area == pytest.approx(expected, rel=0.01)
    assert props.centroid_y == pytest.approx(0.0, abs=1e-6)
    assert props.centroid_z == pytest.approx(0.0, abs=1e-6)


# ── StraightLayer ───────────────────────────────────────────────────
def test_straight_layer_expands_correctly() -> None:
    sec = FiberSection(
        id=1,
        layers=[StraightLayer(
            material_id=2, n_bars=4, bar_area=0.0005,
            y_start=-0.1, z_start=-0.12,
            y_end=0.1, z_end=-0.12,
        )],
    )
    fibres = expand_fibres(sec)
    assert fibres.shape == (4, 3)
    assert np.sum(fibres[:, 2]) == pytest.approx(0.002)
    # All z coordinates should be -0.12 (horizontal layer).
    np.testing.assert_array_almost_equal(fibres[:, 1], -0.12)


# ── SectionAggregator ───────────────────────────────────────────────
def test_section_aggregator_schema() -> None:
    agg = SectionAggregator(
        id=5, name="Fiber+Torsion",
        section_id=1,
        pairings=[AggregatorDOF(material_id=3, dof="T")],
    )
    assert agg.type == "SectionAggregator"
    assert agg.pairings[0].dof == "T"


# ── Mixed section → Iy / Iz ─────────────────────────────────────────
def test_Iz_of_rect_matches_analytical() -> None:
    """Iz = b·h³/12 for a rectangle centred at origin."""
    b, h = 0.3, 0.5   # y-range: -0.15..0.15, z-range: -0.25..0.25
    sec = FiberSection(
        id=1,
        patches=[RectangularPatch(
            material_id=1, n_fib_y=20, n_fib_z=20,
            y_i=-b / 2, z_i=-h / 2, y_j=b / 2, z_j=h / 2,
        )],
    )
    props = compute_section_props(sec)
    # Iz = about z-axis = b·h³/12? No — our convention:
    #   Iz = Σ A_i · (y_i - ȳ)²  (second moment about the z-axis).
    # For rect: Iz = h·b³/12.
    Iz_exact = h * b ** 3 / 12.0
    Iy_exact = b * h ** 3 / 12.0
    assert props.Iz == pytest.approx(Iz_exact, rel=0.01)
    assert props.Iy == pytest.approx(Iy_exact, rel=0.01)


# ── Round-trip persistence ───────────────────────────────────────────
def test_fiber_section_with_patches_round_trips(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core import Node, ElasticBeamColumn
    p = Project(
        nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(1, 0, 0))],
        sections=[
            FiberSection(
                id=1, name="RC-Beam",
                patches=[RectangularPatch(
                    material_id=1, n_fib_y=4, n_fib_z=4,
                    y_i=-0.15, z_i=-0.25, y_j=0.15, z_j=0.25,
                )],
                layers=[StraightLayer(
                    material_id=2, n_bars=3, bar_area=0.0005,
                    y_start=-0.12, z_start=-0.22,
                    y_end=0.12, z_end=-0.22,
                )],
            ),
            SectionAggregator(
                id=2, name="Agg", section_id=1,
                pairings=[AggregatorDOF(material_id=3, dof="T")],
            ),
        ],
        elements=[ElasticBeamColumn(
            id=1, nodes=(1, 2), section_id=1,
        )],
    )
    path = tmp_path / "fib.osmodel"
    save_project(p, path)
    r = load_project(path)
    fs = r.sections[0]
    assert isinstance(fs, FiberSection)
    assert len(fs.patches) == 1
    assert fs.patches[0].kind == "rect"
    assert len(fs.layers) == 1
    assert fs.layers[0].n_bars == 3
    agg = r.sections[1]
    assert isinstance(agg, SectionAggregator)
    assert agg.pairings[0].dof == "T"
