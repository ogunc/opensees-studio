"""MaterialTesterViewModel: Qt-free state behind the Material Tester dialog.

Holds the material choice, the strain protocol and its parameters, runs the
headless :func:`~opensees_studio.services.material_tester.test_uniaxial_material`
service, and derives the numbers the dialog shows as text.  No Qt import:
the dialog owns an instance and reads plain attributes after ``run()``.

Three built-in protocols, all compression-first because the service's
``LoadProtocol`` requires a negative ``max_compressive``:

``monotonic``
    0 -> -amplitude.
``cyclic``
    *n_cycles* symmetric cycles 0 -> -amplitude -> +amplitude -> 0.
``increasing``
    One symmetric cycle per entry of *peaks*, in order.

Each branch between two consecutive strain targets (0 to a peak, peak to the
opposite peak, peak back to 0) is split into ``steps_per_half_cycle`` equal
increments, which maps directly to ``LoadProtocol.n_steps_per_branch``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

import numpy as np

from opensees_studio.core import Project, labels_for
from opensees_studio.services.material_tester import (
    SUPPORTED_MATERIALS,
    CyclicSegment,
    LoadProtocol,
    MaterialTestResult,
    test_uniaxial_material,
)

ProtocolKind = Literal["monotonic", "cyclic", "increasing"]

PROTOCOL_LABELS: dict[ProtocolKind, str] = {
    "monotonic": "Monotonic to amplitude",
    "cyclic": "Symmetric cyclic, fixed amplitude",
    "increasing": "Cyclic, increasing amplitude",
}

Tester = Callable[[Any, LoadProtocol], MaterialTestResult]


# ---- protocol generators ---------------------------------------------------


def monotonic_protocol(amplitude: float, steps: int) -> LoadProtocol:
    """0 -> -*amplitude* in *steps* increments."""
    return LoadProtocol(kind="monotonic", max_compressive=-abs(amplitude), n_steps_per_branch=steps)


def cyclic_protocol(amplitude: float, n_cycles: int, steps: int) -> LoadProtocol:
    """*n_cycles* symmetric cycles at a fixed *amplitude*."""
    a = abs(amplitude)
    return LoadProtocol(
        kind="cyclic",
        max_compressive=-a,
        n_steps_per_branch=steps,
        cycles=[CyclicSegment(compressive_peak=-a, tensile_peak=a, n_cycles=n_cycles)],
    )


def increasing_protocol(peaks: Sequence[float], steps: int) -> LoadProtocol:
    """One symmetric cycle per peak; *peaks* must be positive and strictly increasing."""
    values = [float(p) for p in peaks]
    if not values:
        raise ValueError("Enter at least one peak strain.")
    if any(p <= 0.0 for p in values):
        raise ValueError("Peak strains must be positive.")
    if any(b <= a for a, b in pairwise(values)):
        raise ValueError("Peak strains must be strictly increasing.")
    return LoadProtocol(
        kind="cyclic",
        max_compressive=-values[-1],
        n_steps_per_branch=steps,
        cycles=[CyclicSegment(compressive_peak=-p, tensile_peak=p, n_cycles=1) for p in values],
    )


def strain_targets(protocol: LoadProtocol) -> list[float]:
    """Strain waypoints of *protocol*, starting at 0.0."""
    pts = [0.0]
    if protocol.kind == "monotonic":
        pts.append(protocol.max_compressive)
        if protocol.max_tensile > 0.0:
            pts.append(protocol.max_tensile)
    else:
        for seg in protocol.cycles or []:
            for _ in range(seg.n_cycles):
                pts.extend([seg.compressive_peak, seg.tensile_peak, 0.0])
    return pts


def strain_history(protocol: LoadProtocol) -> np.ndarray:
    """The strain values the service records for *protocol*, one per analysis step."""
    n = protocol.n_steps_per_branch
    out: list[float] = []
    targets = strain_targets(protocol)
    for start, end in pairwise(targets):
        if end == start:
            continue
        out.extend(start + (end - start) * (k + 1) / n for k in range(n))
    return np.asarray(out, dtype=float)


# ---- derived values --------------------------------------------------------


@dataclass(frozen=True)
class DerivedValues:
    """Scalar results shown under the plot."""

    peak_stress: float
    strain_at_peak: float
    secant_stiffness: float | None
    energy_per_cycle: list[float]


def cycle_energies(strain: np.ndarray, stress: np.ndarray, points_per_cycle: int) -> list[float]:
    """Area enclosed by each cycle, integral of stress d(strain), trapezoidal.

    The history is assumed to start from the unstressed origin (0, 0), which
    the service does not record, so it is prepended here.  A positive value
    is energy dissipated per unit volume.
    """
    eps = np.concatenate(([0.0], strain))
    sig = np.concatenate(([0.0], stress))
    energies: list[float] = []
    n_cycles = len(strain) // points_per_cycle
    for k in range(n_cycles):
        lo, hi = k * points_per_cycle, (k + 1) * points_per_cycle + 1
        e, s = eps[lo:hi], sig[lo:hi]
        energies.append(float(np.sum(0.5 * (s[1:] + s[:-1]) * np.diff(e))))
    return energies


def derive_values(
    strain: np.ndarray, stress: np.ndarray, points_per_cycle: int | None
) -> DerivedValues:
    """Peak stress (largest magnitude), secant stiffness there, energy per cycle."""
    i = int(np.argmax(np.abs(stress)))
    eps_pk, sig_pk = float(strain[i]), float(stress[i])
    secant = sig_pk / eps_pk if eps_pk != 0.0 else None
    energies = cycle_energies(strain, stress, points_per_cycle) if points_per_cycle else []
    return DerivedValues(sig_pk, eps_pk, secant, energies)


# ---- view model ------------------------------------------------------------


class MaterialTesterViewModel:
    """State and actions of the Material Tester dialog, without Qt."""

    def __init__(self, project: Project | None = None, *, tester: Tester | None = None) -> None:
        self._project = project
        self._tester: Tester = tester or test_uniaxial_material
        self.material_id: int | None = None
        self.protocol_kind: ProtocolKind = "cyclic"
        self.amplitude: float = 0.01
        self.n_cycles: int = 2
        self.peaks: list[float] = [0.0025, 0.005, 0.01, 0.02]
        self.steps_per_half_cycle: int = 50
        self._reset_output()
        self.set_project(project)

    def _reset_output(self) -> None:
        self.result: MaterialTestResult | None = None
        self.strain: np.ndarray = np.empty(0)
        self.stress: np.ndarray = np.empty(0)
        self.derived: DerivedValues | None = None
        self.error: str | None = None

    # ---- project / materials -------------------------------------------
    def set_project(self, project: Project | None) -> None:
        self._project = project
        mats = self.materials()
        if self.material_id not in {m.id for m in mats}:
            self.material_id = mats[0].id if mats else None

    def materials(self) -> list[Any]:
        """The project's materials the service can test (see ``SUPPORTED_MATERIALS``)."""
        if self._project is None:
            return []
        return [m for m in self._project.materials if isinstance(m, SUPPORTED_MATERIALS)]

    def material(self) -> Any | None:
        return next((m for m in self.materials() if m.id == self.material_id), None)

    @staticmethod
    def material_label(mat: Any) -> str:
        name = getattr(mat, "name", None)
        base = f"{mat.id}: {mat.type}"
        return f"{base} ({name})" if name else base

    # ---- units -----------------------------------------------------------
    def stress_unit(self) -> str:
        return labels_for(self._project.meta.units).stress if self._project else ""

    # ---- protocol --------------------------------------------------------
    def build_protocol(self) -> LoadProtocol:
        steps = self.steps_per_half_cycle
        if self.protocol_kind == "monotonic":
            return monotonic_protocol(self._checked_amplitude(), steps)
        if self.protocol_kind == "cyclic":
            return cyclic_protocol(self._checked_amplitude(), self.n_cycles, steps)
        return increasing_protocol(self.peaks, steps)

    def _checked_amplitude(self) -> float:
        if self.amplitude <= 0.0:
            raise ValueError("Strain amplitude must be positive.")
        return self.amplitude

    def points_per_cycle(self) -> int | None:
        """Recorded points per full cycle, ``None`` for the monotonic protocol."""
        return None if self.protocol_kind == "monotonic" else 3 * self.steps_per_half_cycle

    def protocol_description(self) -> str:
        label = PROTOCOL_LABELS[self.protocol_kind]
        steps = f"{self.steps_per_half_cycle} steps per half-cycle"
        if self.protocol_kind == "monotonic":
            return f"{label}, amplitude {self.amplitude:g}, {steps}"
        if self.protocol_kind == "cyclic":
            return f"{label}, amplitude {self.amplitude:g}, {self.n_cycles} cycles, {steps}"
        peaks = " ".join(f"{p:g}" for p in self.peaks)
        return f"{label}, peaks {peaks}, {steps}"

    # ---- run -------------------------------------------------------------
    def run(self) -> bool:
        """Run the test; on failure set ``error`` and leave the arrays empty."""
        self._reset_output()
        mat = self.material()
        if mat is None:
            self.error = "No uniaxial material selected."
            return False
        try:
            protocol = self.build_protocol()
            result = self._tester(mat, protocol)
        except Exception as exc:  # the view shows the message, never a traceback
            self.error = f"{type(exc).__name__}: {exc}"
            return False
        self.result = result
        self.strain = np.asarray(result.strain, dtype=float)
        self.stress = np.asarray(result.stress, dtype=float)
        if self.strain.size:
            self.derived = derive_values(self.strain, self.stress, self.points_per_cycle())
        return True

    # ---- presentation ----------------------------------------------------
    def summary_text(self) -> str:
        if self.error:
            return self.error
        d = self.derived
        if d is None:
            return ""
        unit = self.stress_unit()
        lines = [
            f"Points: {self.strain.size}",
            f"Peak stress: {d.peak_stress:.6g} {unit} at strain {d.strain_at_peak:.6g}",
        ]
        if d.secant_stiffness is not None:
            lines.append(f"Secant stiffness at peak: {d.secant_stiffness:.6g} {unit}")
        for k, e in enumerate(d.energy_per_cycle, start=1):
            lines.append(f"Energy dissipated, cycle {k}: {e:.6g} {unit} (per unit volume)")
        return "\n".join(lines)

    def export_csv(self, path: str | Path) -> Path:
        """Write strain, stress columns; ``#`` header lines name material and protocol."""
        if self.result is None:
            raise RuntimeError("Run a test before exporting.")
        mat = self.material()
        out = Path(path)
        unit = self.stress_unit() or "-"
        lines = [
            f"# material: {self.material_label(mat) if mat else self.result.material_name}",
            f"# protocol: {self.protocol_description()}",
            f"strain,stress [{unit}]",
        ]
        lines += [f"{e:.10g},{s:.10g}" for e, s in zip(self.strain, self.stress, strict=True)]
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out
