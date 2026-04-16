"""Response-spectrum modal combination service.

Pure-Python computations on top of OpenSees' modal output:
- Mass participation factors per mode (Γ_i for a chosen direction)
- Spectral acceleration look-up (linear interp in period)
- SRSS / CQC combination of modal peak responses

Inputs come from a :class:`ModalResults` (mode shapes, eigenvalues)
and a :class:`ResponseSpectrum` (period vs Sa pairs). Outputs are
peak nodal displacements and per-mode metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from opensees_studio.core import Project, ResponseSpectrum
from opensees_studio.services.results import ModalResults


@dataclass
class ModeContribution:
    """Per-mode metadata for a response-spectrum analysis."""

    mode_number: int                    # 1-indexed
    period: float                        # s
    frequency: float                     # Hz
    angular_frequency: float             # rad/s
    participation_factor: float          # Γ_i for the chosen direction
    effective_mass: float                # M_eff,i = Γ_i² · M_i
    mass_ratio: float                    # M_eff,i / Σ m
    sa_at_period: float                  # Sa(T_i) from spectrum
    modal_peak_disp: dict[int, np.ndarray] = field(default_factory=dict)
    """node_id → peak modal displacement vector (3D translations)."""


def mass_participation(
    project: Project, modal: ModalResults, direction: int,
) -> list[ModeContribution]:
    """Compute Γ_i, M_eff,i and frequency for every mode.

    The formula:
        Γ_i = (φ_i^T · M · 1_d) / (φ_i^T · M · φ_i)
        M_eff,i = Γ_i² · (φ_i^T · M · φ_i)

    where ``1_d`` is the influence vector picking out direction d
    (DOF index `direction-1`, 1 at every node).

    For lumped mass on each node (which is what we support), the
    matrix products reduce to simple sums over the active translational
    DOF.
    """
    # Build the lumped mass vector per node (only the diagonal we need).
    node_mass: dict[int, float] = {}
    total_mass = 0.0
    for n in project.nodes:
        m = float(n.mass[direction - 1])
        node_mass[n.id] = m
        total_mass += m

    out: list[ModeContribution] = []
    for mode_number in sorted(modal.mode_shapes.keys()):
        shape = modal.mode_shapes[mode_number]
        # Numerator: Σ m_n · φ_n,d   (influence vector picks DOF direction)
        numerator = 0.0
        denominator = 0.0
        for nid, vec in shape.items():
            m_n = node_mass.get(nid, 0.0)
            v_d = float(vec[direction - 1]) if vec.size >= direction else 0.0
            numerator += m_n * v_d
            # M-norm of the mode shape: φ_n^T M φ_n = Σ m_n · φ_n,d²
            # (since lumped mass is diagonal)
            denominator += m_n * v_d * v_d

        if denominator == 0.0:
            gamma = 0.0
            m_eff = 0.0
        else:
            gamma = numerator / denominator
            m_eff = gamma ** 2 * denominator

        omega = float(np.sqrt(abs(modal.eigenvalues[mode_number - 1])))
        period = (2.0 * np.pi / omega) if omega > 0.0 else float("inf")
        ratio = (m_eff / total_mass) if total_mass > 0.0 else 0.0
        out.append(ModeContribution(
            mode_number=mode_number,
            period=period,
            frequency=omega / (2.0 * np.pi) if omega > 0.0 else 0.0,
            angular_frequency=omega,
            participation_factor=gamma,
            effective_mass=m_eff,
            mass_ratio=ratio,
            sa_at_period=0.0,           # filled in by combine_spectrum
        ))
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
        scale = (m.participation_factor * m.sa_at_period
                 / (m.angular_frequency ** 2))
        shape = modal.mode_shapes[m.mode_number]
        for nid, vec in shape.items():
            n_take = min(3, vec.size)
            u = np.zeros(3, dtype=float)
            u[:n_take] = vec[:n_take] * scale
            m.modal_peak_disp[nid] = u

    # 2. Combine across modes — per node, per-DOF.
    node_ids = sorted({nid for m in modes for nid in m.modal_peak_disp})
    combined: dict[int, np.ndarray] = {nid: np.zeros(3) for nid in node_ids}

    if method.upper() == "SRSS":
        for nid in node_ids:
            sq_sum = np.zeros(3)
            for m in modes:
                u = m.modal_peak_disp.get(nid)
                if u is not None:
                    sq_sum += u ** 2
            combined[nid] = np.sqrt(sq_sum)
    elif method.upper() == "CQC":
        zeta = damping if damping is not None else spectrum.damping_ratio
        n_modes = len(modes)
        rho = np.zeros((n_modes, n_modes))
        for i in range(n_modes):
            for j in range(n_modes):
                wi = modes[i].angular_frequency
                wj = modes[j].angular_frequency
                if wi <= 0.0 or wj <= 0.0:
                    continue
                r = wj / wi
                num = 8.0 * zeta ** 2 * (1.0 + r) * r ** 1.5
                denom = (1.0 - r ** 2) ** 2 + 4.0 * zeta ** 2 * r * (1.0 + r) ** 2
                rho[i, j] = num / denom if denom > 0.0 else 0.0
        for nid in node_ids:
            sq_sum = np.zeros(3)
            for i in range(n_modes):
                ui = modes[i].modal_peak_disp.get(nid)
                if ui is None:
                    continue
                for j in range(n_modes):
                    uj = modes[j].modal_peak_disp.get(nid)
                    if uj is None:
                        continue
                    sq_sum += rho[i, j] * ui * uj
            combined[nid] = np.sqrt(np.maximum(sq_sum, 0.0))
    else:
        raise ValueError(f"Unsupported combination method: {method!r}")

    return combined, modes
