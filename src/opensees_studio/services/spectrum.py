"""Response-spectrum modal combination service.

Pure-Python computations on top of OpenSees' modal output:
- Mass participation factors per mode (Γ_i for a chosen direction)
- Spectral acceleration look-up (linear interp in period)
- SRSS / CQC combination of modal peak responses (the rules and the
  Der Kiureghian correlation live in ``core.modal_combination``)

Inputs come from a :class:`ModalResults` (mode shapes, eigenvalues)
and a :class:`ResponseSpectrum` (period vs Sa pairs). Outputs are
peak nodal displacements and per-mode metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from opensees_studio.core import Project, ResponseSpectrum
from opensees_studio.core.modal import dof_indices
from opensees_studio.core.modal_combination import combine_cqc, combine_srss, cqc_correlation
from opensees_studio.services.results import ModalResults


@dataclass
class ModeContribution:
    """Per-mode metadata for a response-spectrum analysis."""

    mode_number: int  # 1-indexed
    period: float  # s
    frequency: float  # Hz
    angular_frequency: float  # rad/s
    participation_factor: float  # Γ_i for the chosen direction
    effective_mass: float  # M_eff,i = Γ_i² · M_i
    mass_ratio: float  # M_eff,i / Σ m
    sa_at_period: float  # Sa(T_i) from spectrum
    modal_peak_disp: dict[int, np.ndarray] = field(default_factory=dict)
    """node_id → peak modal displacement vector (3D translations)."""


def mass_participation(
    project: Project,
    modal: ModalResults,
    direction: int,
) -> list[ModeContribution]:
    """Compute Γ_i, M_eff,i and frequency for every mode.

    The formula:
        Γ_i = (φ_i^T · M · 1_d) / (φ_i^T · M · φ_i)
        M_eff,i = Γ_i² · (φ_i^T · M · φ_i)

    where ``1_d`` is the influence vector picking out direction d
    (DOF index `direction-1`, 1 at every node).

    With lumped (diagonal) mass the numerator is ``sum_n m_n,d phi_n,d`` and
    the modal mass ``phi_i^T M phi_i`` is ``sum_n sum_k m_n,k phi_n,k^2`` over
    every DOF that carries mass, not only direction d: a mode moving mostly
    in another direction must get a small factor, not an inflated one.
    """
    dof_idx = dof_indices(project.ndm, project.ndf)
    node_mass: dict[int, np.ndarray] = {}
    total_mass = 0.0
    for n in project.nodes:
        node_mass[n.id] = np.array([n.mass[i] for i in dof_idx], dtype=float)
        total_mass += float(n.mass[dof_idx[direction - 1]]) if direction <= len(dof_idx) else 0.0

    out: list[ModeContribution] = []
    for mode_number in sorted(modal.mode_shapes.keys()):
        shape = modal.mode_shapes[mode_number]
        numerator = 0.0
        denominator = 0.0
        for nid, vec in shape.items():
            m_vec = node_mass.get(nid)
            if m_vec is None:
                continue
            vec = np.asarray(vec, dtype=float)
            n_take = min(vec.size, m_vec.size)
            m_d = float(m_vec[direction - 1]) if direction <= n_take else 0.0
            v_d = float(vec[direction - 1]) if direction <= n_take else 0.0
            numerator += m_d * v_d
            denominator += float(np.dot(m_vec[:n_take] * vec[:n_take], vec[:n_take]))

        if denominator == 0.0:
            gamma = 0.0
            m_eff = 0.0
        else:
            gamma = numerator / denominator
            m_eff = gamma**2 * denominator

        omega = float(np.sqrt(abs(modal.eigenvalues[mode_number - 1])))
        period = (2.0 * np.pi / omega) if omega > 0.0 else float("inf")
        ratio = (m_eff / total_mass) if total_mass > 0.0 else 0.0
        out.append(
            ModeContribution(
                mode_number=mode_number,
                period=period,
                frequency=omega / (2.0 * np.pi) if omega > 0.0 else 0.0,
                angular_frequency=omega,
                participation_factor=gamma,
                effective_mass=m_eff,
                mass_ratio=ratio,
                sa_at_period=0.0,  # filled in by combine_spectrum
            )
        )
    return out


def interp_sa(spectrum: ResponseSpectrum, period: float) -> float:
    """Linear interpolation of Sa(T) from the spectrum table.

    Periods outside the table are clamped to the nearest endpoint
    value (a defensible default — extrapolating a code spectrum is
    rarely meaningful and can be misleading).
    """
    p = np.asarray(spectrum.periods)
    a = np.asarray(spectrum.accelerations)
    if period <= p[0]:
        return float(a[0])
    if period >= p[-1]:
        return float(a[-1])
    return float(np.interp(period, p, a))


def combine_modal_response(
    modes: list[ModeContribution],
    spectrum: ResponseSpectrum,
    modal: ModalResults,
    direction: int,
    *,
    method: str = "SRSS",
    damping: float | None = None,
) -> tuple[dict[int, np.ndarray], list[ModeContribution]]:
    """Compute the combined nodal displacement using SRSS or CQC.

    Returns:
        (combined_disp, modes_with_sa)
        - combined_disp: node_id → 3-vector of peak combined displacements
        - modes_with_sa: same `modes` list with `sa_at_period` and
          `modal_peak_disp` populated
    """
    # 1. Compute modal peak displacement for each mode:
    #    u_i,n = Γ_i · φ_i,n · Sa(T_i) / ω_i²
    for m in modes:
        if m.angular_frequency <= 0.0:
            m.sa_at_period = 0.0
            continue
        m.sa_at_period = interp_sa(spectrum, m.period)
        scale = m.participation_factor * m.sa_at_period / (m.angular_frequency**2)
        shape = modal.mode_shapes[m.mode_number]
        for nid, vec in shape.items():
            n_take = min(3, vec.size)
            u = np.zeros(3, dtype=float)
            u[:n_take] = vec[:n_take] * scale
            m.modal_peak_disp[nid] = u

    # 2. Combine across modes, per node and per DOF, through core.modal_combination.
    node_ids = sorted({nid for m in modes for nid in m.modal_peak_disp})
    peaks = np.zeros((len(modes), len(node_ids), 3))
    for i, m in enumerate(modes):
        for k, nid in enumerate(node_ids):
            u = m.modal_peak_disp.get(nid)
            if u is not None:
                peaks[i, k] = u

    rule = method.upper()
    if rule == "SRSS":
        stacked = combine_srss(peaks)
    elif rule == "CQC":
        zeta = damping if damping is not None else spectrum.damping_ratio
        rho = cqc_correlation([m.angular_frequency for m in modes], zeta)
        stacked = combine_cqc(peaks, rho)
    else:
        raise ValueError(f"Unsupported combination method: {method!r}")
    combined: dict[int, np.ndarray] = {nid: stacked[k].copy() for k, nid in enumerate(node_ids)}

    return combined, modes
