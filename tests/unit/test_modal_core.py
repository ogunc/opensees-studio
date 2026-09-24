"""core.modal: eigen solver routing, free DOF count, sign normalization, solver validation."""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from opensees_studio.core import ElasticBeamColumn, ElasticSection, ModalCase, Node, Project
from opensees_studio.core.modal import (
    DEGENERATE_EIGENVALUE_REL_TOL,
    DENSE_EIGEN_MAX_FREE_DOF,
    DENSE_EIGEN_MAX_FREE_DOF_ENV,
    SIGN_TIE_REL_TOL,
    SYMM_BAND_REFUSAL,
    degenerate_groups,
    dense_eigen_max_free_dof,
    free_dof_count,
    normalize_mode_sign,
    orthogonalize_degenerate_modes,
    resolve_modal_solver,
    sign_factor,
)


# ─────────────────────── routing ───────────────────────
def test_auto_routes_dense_at_or_below_threshold_and_arpack_above(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv(DENSE_EIGEN_MAX_FREE_DOF_ENV, raising=False)
    assert dense_eigen_max_free_dof() == DENSE_EIGEN_MAX_FREE_DOF == 500
    assert resolve_modal_solver("auto", 500, 6)[0] == "fullGenLapack"
    assert resolve_modal_solver("auto", 48, 6)[0] == "fullGenLapack"
    assert resolve_modal_solver("auto", 501, 6)[0] == "genBandArpack"
    assert resolve_modal_solver("auto", 3402, 6)[0] == "genBandArpack"


def test_environment_override_moves_the_threshold(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(DENSE_EIGEN_MAX_FREE_DOF_ENV, "100")
    assert dense_eigen_max_free_dof() == 100
    assert resolve_modal_solver("auto", 100, 6)[0] == "fullGenLapack"
    solver, reason = resolve_modal_solver("auto", 101, 6)
    assert solver == "genBandArpack"
    assert "above 100" in reason
    monkeypatch.setenv(DENSE_EIGEN_MAX_FREE_DOF_ENV, "0")
    assert resolve_modal_solver("auto", 48, 6)[0] == "genBandArpack"


@pytest.mark.parametrize("raw", ["abc", "-5", "1.5"])
def test_environment_override_rejects_bad_values(monkeypatch, raw: str) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(DENSE_EIGEN_MAX_FREE_DOF_ENV, raw)
    with pytest.raises(ValueError, match=DENSE_EIGEN_MAX_FREE_DOF_ENV):
        dense_eigen_max_free_dof()


def test_explicit_solver_is_honoured(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv(DENSE_EIGEN_MAX_FREE_DOF_ENV, raising=False)
    assert resolve_modal_solver("genBandArpack", 48, 6)[0] == "genBandArpack"
    assert resolve_modal_solver("fullGenLapack", 3402, 6)[0] == "fullGenLapack"


def test_arpack_falls_back_to_dense_for_tiny_models() -> None:
    solver, reason = resolve_modal_solver("genBandArpack", 6, 3)
    assert solver == "fullGenLapack"
    assert "2 * n_modes" in reason
    assert resolve_modal_solver("genBandArpack", 7, 3)[0] == "genBandArpack"


def test_symm_band_lapack_is_refused_with_the_massless_dof_message() -> None:
    with pytest.raises(ValueError, match="positive definite mass"):
        resolve_modal_solver("symmBandLapack", 48, 6)
    assert "lumped" in SYMM_BAND_REFUSAL


def test_unknown_solver_name_is_rejected_by_the_router() -> None:
    with pytest.raises(ValueError, match="Unknown eigen solver"):
        resolve_modal_solver("genSparseArpack", 48, 6)


# ─────────────────────── schema ───────────────────────
def test_modal_case_defaults_to_auto_and_keeps_offered_names() -> None:
    assert ModalCase(id=1).solver == "auto"
    assert ModalCase(id=1, solver="fullGenLapack").solver == "fullGenLapack"
    assert ModalCase(id=1, solver="genBandArpack").solver == "genBandArpack"
    # Loads (the runner refuses it).
    assert ModalCase(id=1, solver="symmBandLapack").solver == "symmBandLapack"


def test_modal_case_maps_unoffered_solver_names_to_auto_with_a_warning() -> None:
    with pytest.warns(UserWarning, match="genSparseArpack"):
        case = ModalCase(id=1, solver="genSparseArpack")
    assert case.solver == "auto"
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ModalCase(id=1, solver="auto")  # offered names never warn


# ─────────────────────── free DOF ───────────────────────
def _frame_2d() -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, True, False, False, False, True)),
            Node(id=2, coords=(0.0, 3.0, 0.0), restraint=(False, True, False, False, False, False)),
            Node(id=3, coords=(4.0, 3.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=8.333e-6)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
        ],
    )


def test_free_dof_count_uses_the_ndf_subset_of_the_restraint() -> None:
    # 3 nodes x 3 DOF = 9, minus 3 (node 1) minus 1 (node 2 Uy) = 5.
    assert free_dof_count(_frame_2d()) == 5


# ─────────────────────── sign normalization ───────────────────────
def test_sign_factor_makes_the_largest_component_positive() -> None:
    assert sign_factor(np.array([0.2, -0.9, 0.5])) == -1.0
    assert sign_factor(np.array([0.2, 0.9, -0.5])) == 1.0
    assert sign_factor(np.zeros(3)) == 1.0
    assert sign_factor(np.array([])) == 1.0


def test_sign_factor_tie_within_tolerance_goes_to_the_lowest_index() -> None:
    # Index 1 is the strict maximum and negative; index 0 is within 1e-12
    # (relative) of it and positive. Without the tolerance the mode would
    # flip depending on roundoff; with it the lowest index decides.
    tied = np.array([1.0 - 1e-12, -1.0])
    assert sign_factor(tied) == 1.0
    assert sign_factor(tied, rel_tol=0.0) == -1.0
    # Beyond the tolerance the strict maximum decides again.
    assert sign_factor(np.array([1.0 - 1e-6, -1.0])) == -1.0
    assert SIGN_TIE_REL_TOL == 1e-9


def test_normalize_mode_sign_orders_components_by_node_id_then_dof() -> None:
    shape = {
        7: np.array([0.1, -1.0, 0.0]),  # node 7 holds the (negative) maximum
        2: np.array([0.3, 0.2, 0.0]),
    }
    out = normalize_mode_sign(shape)
    assert np.array_equal(out[7], np.array([-0.1, 1.0, 0.0]))
    assert np.array_equal(out[2], np.array([-0.3, -0.2, 0.0]))
    assert np.array_equal(shape[7], np.array([0.1, -1.0, 0.0]))  # input untouched
    # A mirror tie between node 2 and node 7: node 2 (lower id) wins.
    mirrored = {2: np.array([0.0, 1.0 - 1e-12]), 7: np.array([0.0, -1.0])}
    assert normalize_mode_sign(mirrored)[2][1] > 0.0
    assert normalize_mode_sign({}) == {}


# ─────────────────────── degenerate groups ───────────────────────
def test_degenerate_groups_join_consecutive_equal_eigenvalues() -> None:
    assert DEGENERATE_EIGENVALUE_REL_TOL == 1e-6
    values = [759.13148, 759.13148 * (1 + 1e-13), 909.129, 5363.81, 13863.91, 13863.91]
    assert degenerate_groups(values) == [[0, 1], [2], [3], [4, 5]]
    assert degenerate_groups([1.0, 1.0 + 1e-5, 2.0]) == [[0], [1], [2]]
    assert degenerate_groups([0.0, 0.0, 3.0]) == [[0, 1], [2]]
    assert degenerate_groups([]) == []


def _oblique_pair() -> tuple[dict[int, dict[int, np.ndarray]], dict[int, np.ndarray]]:
    """Two modes spanning the same eigenspace but with a mass cosine of about 0.6."""
    node_mass = {1: np.array([2.0, 1.0]), 2: np.array([1.0, 3.0])}
    a = {1: np.array([1.0, 0.0]), 2: np.array([0.0, 1.0])}
    b = {1: np.array([1.0, 0.5]), 2: np.array([0.0, 2.0])}  # b = a + something
    c = {1: np.array([0.0, 1.0]), 2: np.array([-1.0, 0.0])}
    return {1: a, 2: b, 3: c}, node_mass


def _mass_cos(
    u: dict[int, np.ndarray], v: dict[int, np.ndarray], m: dict[int, np.ndarray]
) -> float:
    ids = sorted(u)
    uu = np.concatenate([u[i] for i in ids])
    vv = np.concatenate([v[i] for i in ids])
    mm = np.concatenate([m[i] for i in ids])
    return float((uu * mm) @ vv / np.sqrt(((uu * mm) @ uu) * ((vv * mm) @ vv)))


def test_orthogonalize_degenerate_modes_makes_the_group_mass_orthogonal_only() -> None:
    shapes, mass = _oblique_pair()
    assert abs(_mass_cos(shapes[1], shapes[2], mass)) > 0.5
    out = orthogonalize_degenerate_modes([10.0, 10.0, 40.0], shapes, mass)
    assert abs(_mass_cos(out[1], out[2], mass)) < 1e-15
    # First vector of the group and the mode outside it are untouched.
    for nid in (1, 2):
        assert np.array_equal(out[1][nid], shapes[1][nid])
        assert np.array_equal(out[3][nid], shapes[3][nid])
    # The input is not modified and distinct eigenvalues leave everything alone.
    assert np.array_equal(shapes[2][2], np.array([0.0, 2.0]))
    same = orthogonalize_degenerate_modes([10.0, 20.0, 40.0], shapes, mass)
    assert all(np.array_equal(same[m][n], shapes[m][n]) for m in shapes for n in shapes[m])


def test_orthogonalize_degenerate_modes_spans_the_same_space_and_skips_massless() -> None:
    shapes, mass = _oblique_pair()
    out = orthogonalize_degenerate_modes([10.0, 10.0, 40.0], shapes, mass)
    # out[2] is a combination of the original pair: it lies in their span.
    ids = sorted(shapes[1])
    a = np.concatenate([shapes[1][i] for i in ids])
    b = np.concatenate([shapes[2][i] for i in ids])
    o = np.concatenate([out[2][i] for i in ids])
    coefficients, _residual, _rank, _sv = np.linalg.lstsq(np.column_stack([a, b]), o, rcond=None)
    assert np.allclose(np.column_stack([a, b]) @ coefficients, o)
    # Massless DOF everywhere: nothing can be projected, vectors stay.
    zero_mass = {1: np.zeros(2), 2: np.zeros(2)}
    untouched = orthogonalize_degenerate_modes([10.0, 10.0, 40.0], shapes, zero_mass)
    assert all(np.array_equal(untouched[m][n], shapes[m][n]) for m in shapes for n in shapes[m])
