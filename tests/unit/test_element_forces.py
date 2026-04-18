"""Unit tests for element_forces service."""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    Node,
    Project,
)
from opensees_studio.services.element_forces import (
    DiagramData,
    ForceComponent,
    auto_scale,
    extract_diagram_data,
)
from opensees_studio.services.results import StaticResults


# ──────────────────────────────────────────────────────────────────────
# Fixtures: a tiny 3D project with 2 elements + canned force results.
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def project_3d() -> Project:
    return Project(
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(3.0, 0.0, 0.0)),
            Node(id=3, coords=(6.0, 0.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5)],
        elements=[
            ElasticBeamColumn(id=10, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=20, nodes=(2, 3), section_id=1),
        ],
    )


@pytest.fixture
def static_3d_results() -> StaticResults:
    """One step of analysis. Element 10 carries [N=100, …]; element 20
    carries [N=-50, …] (compression). 12 components, single time step."""
    forces_10 = np.array([[100.0, 5.0, 7.0, 1.0, 8.0, 9.0,
                           -100.0, -5.0, -7.0, -1.0, -8.0, -9.0]])
    forces_20 = np.array([[-50.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                           50.0, 0.0, 0.0, 0.0, 0.0, 0.0]])
    return StaticResults(
        case_id=1, case_name="tst", n_steps=1,
        element_forces={10: forces_10, 20: forces_20},
    )


# ──────────────────────────────────────────────────────────────────────
# extract_diagram_data
# ──────────────────────────────────────────────────────────────────────

def test_extract_axial_yields_correct_per_end_values(
    project_3d: Project, static_3d_results: StaticResults,
) -> None:
    data = extract_diagram_data(project_3d, static_3d_results, ForceComponent.N)
    assert data.component is ForceComponent.N
    # Both elements participate; preserve project order (10 first, then 20).
    assert list(data.element_ids) == [10, 20]
    # Sign-flipped j-end so diagrams show continuous internal forces:
    # raw end-i = [100, -50], raw end-j = [-100, 50]
    # flipped end-j = [100, -50]  → internal force same along each element.
    np.testing.assert_array_equal(data.values_i, [100.0, -50.0])
    np.testing.assert_array_equal(data.values_j, [100.0, -50.0])
    assert data.abs_max == 100.0


def test_extract_skips_elements_without_force_data(
    project_3d: Project,
) -> None:
    results = StaticResults(case_id=1, case_name="x", n_steps=1, element_forces={})
    data = extract_diagram_data(project_3d, results, ForceComponent.N)
    assert data.element_ids.size == 0
    assert data.abs_max == 0.0


def test_extract_handles_2d_force_vectors(project_3d: Project) -> None:
    """2D OpenSees beams return 6 components: [N, Vy, Mz] × 2 ends.
    Asking for V3 / M2 in this case should yield no rows for that element."""
    forces_10 = np.array([[100.0, 5.0, 9.0, -100.0, -5.0, -9.0]])
    results = StaticResults(case_id=1, case_name="2d", n_steps=1,
                            element_forces={10: forces_10})
    n_data = extract_diagram_data(project_3d, results, ForceComponent.N)
    np.testing.assert_array_equal(n_data.values_i, [100.0])
    v3_data = extract_diagram_data(project_3d, results, ForceComponent.V3)
    assert v3_data.element_ids.size == 0      # V3 not available in 2D output


def test_extract_uses_specified_step(project_3d: Project) -> None:
    """Multi-step pushover: pick the first step explicitly."""
    f = np.zeros((3, 12))
    f[0, 0] = 10.0       # step 0 axial @ node i
    f[1, 0] = 20.0
    f[2, 0] = 30.0
    results = StaticResults(case_id=1, case_name="push", n_steps=3,
                            element_forces={10: f})
    data = extract_diagram_data(project_3d, results, ForceComponent.N, step=0)
    np.testing.assert_array_equal(data.values_i, [10.0])
    data = extract_diagram_data(project_3d, results, ForceComponent.N, step=2)
    np.testing.assert_array_equal(data.values_i, [30.0])


# ──────────────────────────────────────────────────────────────────────
# auto_scale
# ──────────────────────────────────────────────────────────────────────

def test_auto_scale_scales_to_target_fraction(
    project_3d: Project, static_3d_results: StaticResults,
) -> None:
    data = extract_diagram_data(project_3d, static_3d_results, ForceComponent.N)
    # Bounding-box diagonal of the 3-node line is 6.0 along X.
    # target_fraction defaults to 0.08 → max diagram height = 0.48.
    # abs_max=100 → expected scale ≈ 0.0048.
    scale = auto_scale(project_3d, data)
    assert scale == pytest.approx((6.0 * 0.08) / 100.0, rel=1e-9)


def test_auto_scale_zero_force_returns_unity(project_3d: Project) -> None:
    empty = DiagramData(
        component=ForceComponent.N,
        element_ids=np.empty(0, dtype=int),
        values_i=np.empty(0), values_j=np.empty(0), abs_max=0.0,
    )
    assert auto_scale(project_3d, empty) == 1.0


# ──────────────────────────────────────────────────────────────────────
# Truss-specific force extraction (separate localForce layout)
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def truss_project_2d() -> Project:
    from opensees_studio.core import ElasticUniaxial, TrussElement
    return Project(
        ndm=2, ndf=2,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(3.0, 0.0, 0.0)),
        ],
        materials=[ElasticUniaxial(id=1, E=200e9)],
        elements=[
            TrussElement(id=1, nodes=(1, 2), area=1e-3, material_id=1),
        ],
    )


def test_truss_axial_uses_correct_index_map(truss_project_2d: Project) -> None:
    """2D truss localForce is [N_i, 0, N_j, 0] — N_j is at index 2, not 3.

    Before the fix, extract_diagram_data assumed the frame layout where
    index 3 means N_j. Truss's index 3 is the zero shear-y at end j, so
    every diagram value_j came back as 0 and the force diagram drew
    nothing meaningful for trusses.
    """
    # 2D truss with tension N = +1500 N → local force vector [-N, 0, +N, 0]
    # (equilibrium signs: end-i points out, end-j points in).
    forces = np.array([[-1500.0, 0.0, 1500.0, 0.0]])
    results = StaticResults(
        case_id=1, case_name="tst", n_steps=1,
        element_forces={1: forces},
    )
    data = extract_diagram_data(truss_project_2d, results, ForceComponent.N)
    assert data.element_ids.tolist() == [1]
    assert data.values_i[0] == pytest.approx(-1500.0)
    # values_j is sign-flipped (equilibrium convention) so the diagram
    # draws a single-sign line along the bar.
    assert data.values_j[0] == pytest.approx(-1500.0)


def test_truss_has_no_shear_or_moment_components(truss_project_2d: Project) -> None:
    """Requesting V2 / V3 / M3 on a truss returns an empty diagram."""
    forces = np.array([[100.0, 0.0, -100.0, 0.0]])
    results = StaticResults(
        case_id=1, case_name="tst", n_steps=1,
        element_forces={1: forces},
    )
    for comp in (ForceComponent.V2, ForceComponent.V3, ForceComponent.M3):
        data = extract_diagram_data(truss_project_2d, results, comp)
        assert data.element_ids.size == 0, f"{comp.value} should yield no data"
