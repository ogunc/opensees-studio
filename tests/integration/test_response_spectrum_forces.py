"""Response spectrum cases give reactions and element forces, not only displacements.

A one-column cantilever with two lumped masses (a two-mass shear-like chain) has
closed forms for the modal base reaction: the base shear of mode ``i`` is its
effective mass times Sa, ``V_i = Meff_i Sa_i``, and the base moment is
``sum_n m_n phi_n Gamma Sa h_n``. SRSS (and CQC) of those equal the combined
reaction the runner stores. The tip-mass single-DOF column gives the exact
numbers ``V = m Sa`` and ``M = m Sa H``.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    CombinationTerm,
    ElasticBeamColumn,
    ElasticSection,
    LoadCombination,
    ModalCase,
    Node,
    Project,
    ProjectMeta,
    ResponseSpectrum,
    ResponseSpectrumCase,
    UnitSystem,
)
from opensees_studio.services.combination import combine_results
from opensees_studio.services.opensees_runner import OpenSeesRunner

H = 3.0
EI_E, EI_I = 200e9, 1.0e-4
SA = 2.0


def _column(masses: list[float]) -> Project:
    """A vertical cantilever, ``len(masses)`` nodes of height ``H`` apart, X lumped mass."""
    nodes = [Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6)]
    elements = []
    for i, m in enumerate(masses, start=1):
        nodes.append(Node(id=i + 1, coords=(0.0, 0.0, i * H), mass=(m, 0.0, 0.0, 0.0, 0.0, 0.0)))
        elements.append(ElasticBeamColumn(id=i, nodes=(i, i + 1), section_id=1))
    return Project(
        meta=ProjectMeta(name="rs column", units=UnitSystem.SI_M_N),
        ndm=2,
        ndf=3,
        nodes=nodes,
        elements=elements,
        sections=[ElasticSection(id=1, name="col", E=EI_E, A=1.0, Iz=EI_I)],
        spectra=[
            ResponseSpectrum(
                id=1,
                name="flat",
                periods=[0.01, 100.0],
                accelerations=[SA, SA],
                damping_ratio=0.05,
            )
        ],
        analyses=[
            ModalCase(id=1, name="Modal", n_modes=len(masses)),
            ResponseSpectrumCase(
                id=2,
                name="RSX",
                modal_case_id=1,
                spectrum_id=1,
                direction=1,
                combination="SRSS",
            ),
        ],
    )


def test_single_mass_cantilever_has_the_exact_base_shear_and_moment() -> None:
    mass = 1500.0
    project = _column([mass])
    result = OpenSeesRunner(project).run(project.analyses[1])

    # Gamma = 1, so the peak is the whole mass times Sa.
    shear = mass * SA
    reaction = result.node_reaction[1]
    np.testing.assert_allclose(abs(reaction[0]), shear, rtol=1e-6)
    np.testing.assert_allclose(abs(reaction[2]), shear * H, rtol=1e-6)
    # The column carries the same shear all the way; localForce is [N, V, M] per end.
    forces = result.element_forces[1]
    np.testing.assert_allclose(forces[[1, 4]], shear, rtol=1e-6)
    np.testing.assert_allclose(forces[2], shear * H, rtol=1e-6)
    np.testing.assert_allclose(forces[5], 0.0, atol=1e-6 * shear)
    assert result.element_stresses == {}

    # The displacement is the one the modal analysis gave: u = Sa / w^2 = Sa m H^3 / (3EI).
    expected_u = SA * mass * H**3 / (3 * EI_E * EI_I)
    np.testing.assert_allclose(result.combined_disp[2][0], expected_u, rtol=1e-6)


def test_two_mass_srss_base_reaction_is_the_srss_of_modal_effective_mass_forces() -> None:
    project = _column([1500.0, 900.0])
    result = OpenSeesRunner(project).run(project.analyses[1])
    modes = result.modes
    assert len(modes) == 2

    shear = np.sqrt(sum((m.effective_mass * m.sa_at_period) ** 2 for m in modes))
    np.testing.assert_allclose(result.node_reaction[1][0], shear, rtol=1e-6)

    # Moment: modal peak M_i = Sa Gamma_i sum_n m_n phi_n h_n, SRSS across modes.

    modal = OpenSeesRunner(project)
    modal.build()
    shapes = modal._run_modal(project.analyses[0]).mode_shapes
    masses = {2: 1500.0, 3: 900.0}
    heights = {2: H, 3: 2 * H}
    moments = []
    for m in modes:
        phi = shapes[m.mode_number]
        moments.append(
            SA * m.participation_factor * sum(masses[n] * phi[n][0] * heights[n] for n in masses)
        )
    np.testing.assert_allclose(
        result.node_reaction[1][2], np.sqrt(np.sum(np.square(moments))), rtol=1e-6
    )
    # Reactions and displacements come from the same modal peaks.
    assert set(result.node_reaction) == {1, 2, 3}
    assert set(result.element_forces) == {1, 2}


def test_a_combination_with_a_spectrum_case_now_has_forces_and_reactions() -> None:
    project = _column([1500.0, 900.0])
    project.combinations.append(
        LoadCombination(id=1, name="E", terms=[CombinationTerm(ref_id=2, factor=1.5)])
    )
    result = OpenSeesRunner(project).run(project.analyses[1])
    combo = combine_results(project, 1, {2: result})
    assert combo.missing_fields == []
    assert not combo.single_valued
    # ±peak bounds: the upper bound is +1.5 x the peak, the lower is its negative.
    peak = result.node_reaction[1]
    np.testing.assert_allclose(combo.max.node_reaction[1][-1], 1.5 * peak)
    np.testing.assert_allclose(combo.min.node_reaction[1][-1], -1.5 * peak)
    assert set(combo.max.element_forces) == {1, 2}
