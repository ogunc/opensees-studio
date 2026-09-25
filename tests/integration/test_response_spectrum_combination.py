"""Response spectrum combination on space_frame_3d: SRSS versus CQC, warnings, damping, basis.

space_frame_3d is doubly symmetric: modes 1 and 2 (X and Y sway) share one
eigenvalue, as do modes 5 and 6. The basis the eigen solver returns inside
such a pair is arbitrary, and SRSS depends on it while CQC (rho = 1 inside
the pair) does not.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import ModalCase, ResponseSpectrumCase
from opensees_studio.services import load_project
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.results import ModalResults
from opensees_studio.services.spectrum import (
    combine_modal_response,
    mass_participation,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _space_frame():  # type: ignore[no-untyped-def]
    project = load_project(EXAMPLES / "space_frame_3d.osmodel")
    rs = next(c for c in project.analyses if isinstance(c, ResponseSpectrumCase))
    return project, rs


def _max_rel_diff(a: dict[int, np.ndarray], b: dict[int, np.ndarray]) -> float:
    scale = max(float(np.max(np.abs(v))) for v in a.values())
    return max(float(np.max(np.abs(a[n] - b[n]))) for n in a) / scale


def test_saved_case_keeps_srss_and_new_cases_default_to_cqc() -> None:
    _project, rs = _space_frame()
    assert rs.combination == "SRSS"  # no silent migration of a saved case
    fresh = ResponseSpectrumCase(id=9, modal_case_id=2, spectrum_id=1, direction=1)
    assert fresh.combination == "CQC"
    assert fresh.damping_ratio is None


def test_srss_warns_about_closely_spaced_modes_and_cqc_does_not() -> None:
    project, rs = _space_frame()
    srss = OpenSeesRunner(project).run(rs)
    cqc = OpenSeesRunner(project).run(rs.model_copy(update={"combination": "CQC"}))

    assert len(srss.warnings) == 1
    text = srss.warnings[0]
    assert text.startswith("SRSS with closely spaced modes")
    assert "modes 1 and 2 (ratio 1.000)" in text
    assert "modes 5 and 6 (ratio 1.000)" in text
    assert "modes 1 and 3 (ratio 0.914)" in text
    assert "depends on the eigen basis inside such a pair; use CQC." in text
    assert srss.damping_ratio is None
    assert cqc.warnings == []
    assert cqc.damping_ratio == 0.05  # the spectrum's damping
    assert cqc.solver == srss.solver == "fullGenLapack"

    # Both rules report the same modes; the combined displacements differ.
    roof = 12
    assert srss.combined_disp[roof][0] > 0.0 and cqc.combined_disp[roof][0] > 0.0
    assert not np.allclose(srss.combined_disp[roof], cqc.combined_disp[roof], rtol=1e-3)
    # X excitation: with CQC the X displacement dominates. SRSS gets the warning
    # above instead of a magnitude check: inside a degenerate pair its result
    # depends on the eigen basis the solver returns (the Windows LAPACK gives
    # roof U1 0.0137 m with U2 0.0032 m, the Linux build a near-zero U2).
    assert cqc.combined_disp[roof][0] > 5.0 * cqc.combined_disp[roof][1]
    # Cumulative mass participation of the six modes: all of the X mass, never more
    # (the direction-only normalisation summed to 2.0 here).
    total = sum(m.mass_ratio for m in cqc.modes)
    assert 0.999 < total <= 1.0 + 1e-9


def test_closely_spaced_ratio_is_configurable() -> None:
    project, rs = _space_frame()
    strict = OpenSeesRunner(project).run(rs.model_copy(update={"closely_spaced_ratio": 0.99}))
    assert "modes 1 and 3" not in strict.warnings[0]
    assert "modes 1 and 2 (ratio 1.000)" in strict.warnings[0]


def test_cqc_damping_override_zero_means_the_spectrum_damping() -> None:
    project, rs = _space_frame()
    stored = ResponseSpectrumCase.model_validate(
        {**rs.model_dump(mode="json", by_alias=True), "combination": "CQC", "damping_ratio": 0}
    )
    assert stored.damping_ratio is None
    result = OpenSeesRunner(project).run(stored)
    assert result.damping_ratio == 0.05
    assert result.warnings == []
    explicit = OpenSeesRunner(project).run(stored.model_copy(update={"damping_ratio": 0.02}))
    assert explicit.damping_ratio == 0.02
    assert not np.allclose(explicit.combined_disp[12], result.combined_disp[12])


def test_cqc_never_runs_with_zero_damping() -> None:
    project, rs = _space_frame()
    project.spectra[0].damping_ratio = 0.0
    result = OpenSeesRunner(project).run(rs.model_copy(update={"combination": "CQC"}))
    assert result.damping_ratio == 0.05
    assert len(result.warnings) == 1 and "Using 0.05" in result.warnings[0]


def _rotate_pair(
    modal: ModalResults,
    first: int,
    second: int,
    degrees: float,
    node_mass: dict[int, np.ndarray],
) -> ModalResults:
    """Rotate a mass-orthogonal pair; both are scaled to unit modal mass first so
    the rotated pair stays mass-orthogonal (an arbitrary solver basis)."""
    c, s = np.cos(np.radians(degrees)), np.sin(np.radians(degrees))
    shapes = {m: {n: v.copy() for n, v in sh.items()} for m, sh in modal.mode_shapes.items()}

    def unit(mode: int) -> dict[int, np.ndarray]:
        norm = np.sqrt(
            sum(float((v * node_mass[n]) @ v) for n, v in modal.mode_shapes[mode].items())
        )
        return {n: v / norm for n, v in modal.mode_shapes[mode].items()}

    ua, ub = unit(first), unit(second)
    for node in shapes[first]:
        a, b = ua[node], ub[node]
        shapes[first][node] = c * a + s * b
        shapes[second][node] = -s * a + c * b
    return ModalResults(
        case_id=modal.case_id,
        case_name=modal.case_name,
        eigenvalues=modal.eigenvalues.copy(),
        mode_shapes=shapes,
        solver=modal.solver,
        n_free_dof=modal.n_free_dof,
    )


def test_cqc_is_invariant_under_rotation_of_the_real_degenerate_pairs_and_srss_is_not() -> None:
    project, rs = _space_frame()
    modal_case = next(c for c in project.analyses if isinstance(c, ModalCase))
    modal = OpenSeesRunner(project).run(modal_case)
    spectrum = project.spectra[0]

    def combine(results: ModalResults, rule: str) -> dict[int, np.ndarray]:
        modes = mass_participation(project, results, rs.direction)
        combined, _ = combine_modal_response(
            modes, spectrum, results, rs.direction, method=rule, damping=0.05
        )
        return combined

    node_mass = {n.id: np.asarray(n.mass, dtype=float) for n in project.nodes}
    cqc_ref, srss_ref = combine(modal, "CQC"), combine(modal, "SRSS")
    cqc_spread = srss_spread = 0.0
    for degrees in (15.0, 30.0, 45.0, 60.0, 90.0, 137.0):
        rotated = _rotate_pair(
            _rotate_pair(modal, 1, 2, degrees, node_mass), 5, 6, 2.0 * degrees, node_mass
        )
        cqc_spread = max(cqc_spread, _max_rel_diff(combine(rotated, "CQC"), cqc_ref))
        srss_spread = max(srss_spread, _max_rel_diff(combine(rotated, "SRSS"), srss_ref))
    assert cqc_spread < 1e-10, f"CQC moved by {cqc_spread:.3e} (relative) across rotations"
    assert srss_spread > 1e-2, f"SRSS only moved by {srss_spread:.3e} (relative)"


def test_cqc_agrees_between_the_dense_and_the_arpack_basis_and_srss_does_not() -> None:
    """Two real eigen bases of the same model (dense and ARPACK return different
    bases inside the repeated pairs): CQC gives the same combined displacements,
    SRSS does not.
    """
    project, rs = _space_frame()
    position = next(i for i, c in enumerate(project.analyses) if isinstance(c, ModalCase))
    modal_case = project.analyses[position]
    by_solver: dict[str, dict[str, dict[int, np.ndarray]]] = {}
    for solver in ("fullGenLapack", "genBandArpack"):
        project.analyses[position] = modal_case.model_copy(update={"solver": solver})
        by_solver[solver] = {
            rule: OpenSeesRunner(project)
            .run(rs.model_copy(update={"combination": rule}))
            .combined_disp
            for rule in ("CQC", "SRSS")
        }
    dense, arpack = by_solver["fullGenLapack"], by_solver["genBandArpack"]
    assert _max_rel_diff(dense["CQC"], arpack["CQC"]) < 1e-9
    assert _max_rel_diff(dense["SRSS"], arpack["SRSS"]) > 1e-3
