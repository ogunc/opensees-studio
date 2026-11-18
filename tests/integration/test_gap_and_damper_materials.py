"""The gap and damper materials of the Material Library follow their laws.

``ElasticPPGap`` is driven strain by strain: no stress until the gap closes, then
``E (strain - gap)`` up to ``Fy``, perfectly plastic (or hardening by ``eta``)
beyond, and the plastic strain widens the gap. ``Viscous`` and
``ViscousDamper`` (alpha = 1) damp a single-degree-of-freedom oscillator built
the way the application builds one — a ``ZeroLength`` element with a spring and
the dashpot in a ``Parallel`` material, a step load, a transient case — and its
first overshoot is the closed form of a linearly damped oscillator,
``1 + exp(-zeta pi / sqrt(1 - zeta^2))`` times the static displacement.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest

from opensees_studio.core import (
    ConstantTimeSeries,
    ElasticUniaxial,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    TransientCase,
    ZeroLengthElement,
)
from opensees_studio.core.materials.library import (
    ElasticPPGap,
    ParallelMaterial,
    Viscous,
    ViscousDamper,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

ops = pytest.importorskip("openseespy.opensees")


def _gap_path(material: ElasticPPGap, strains: list[float]) -> list[float]:
    project = Project(
        ndm=2, ndf=3, nodes=[Node(id=1, coords=(0.0, 0.0, 0.0))], materials=[material]
    )
    OpenSeesRunner(project).build()
    ops.testUniaxialMaterial(material.id)
    out = []
    for strain in strains:
        ops.setStrain(strain)
        out.append(float(ops.getStress()))
    return out


PATH = [0.0, 0.001, 0.003, 0.01, 0.012, 0.02, 0.015, 0.005, 0.0, -0.005, 0.02]


def test_tension_gap_closes_yields_and_widens() -> None:
    gap = ElasticPPGap(id=1, E=1000.0, Fy=10.0, gap=0.002)
    stresses = _gap_path(gap, PATH)
    # Open, then E (strain - gap), yield at Fy (strain 0.012), plastic to 0.02.
    assert stresses[:6] == pytest.approx([0.0, 0.0, 1.0, 8.0, 10.0, 10.0])
    # 0.008 of plastic strain: the gap is now 0.010, so 0.015 gives 5 and 0.005 nothing.
    assert stresses[6:10] == pytest.approx([5.0, 0.0, 0.0, 0.0])
    assert stresses[10] == pytest.approx(10.0)


def test_compression_gap_mirrors_it() -> None:
    gap = ElasticPPGap(id=1, E=1000.0, Fy=-10.0, gap=-0.002)
    stresses = _gap_path(gap, [-e for e in PATH])
    assert stresses[:8] == pytest.approx([0.0, 0.0, -1.0, -8.0, -10.0, -10.0, -5.0, 0.0])


def test_hardening_ratio() -> None:
    gap = ElasticPPGap(id=1, E=1000.0, Fy=10.0, gap=0.002, eta=0.1)
    stresses = _gap_path(gap, PATH)
    # Beyond yield the tangent is eta E: 10 + 100 (0.02 - 0.012).
    assert stresses[5] == pytest.approx(10.8)


# ──────────────────────────── dampers in a transient ────────────────────────────
K, MASS, FORCE = 100.0, 1.0, 10.0
DT, STEPS = 0.001, 1200


def _first_peak(dashpot: Viscous | ViscousDamper) -> float:
    """First overshoot of the step response, over the static displacement."""
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(
                id=2,
                coords=(0.0, 0.0, 0.0),
                restraint=(False, True, True, True, True, True),
                mass=(MASS, 0.0, 0.0, 0.0, 0.0, 0.0),
            ),
        ],
        materials=[
            ElasticUniaxial(id=1, E=K),
            dashpot,
            ParallelMaterial(id=3, material_ids=[1, dashpot.id]),
        ],
        elements=[ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(3,), dofs=(1,))],
        time_series=[ConstantTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(FORCE, 0, 0, 0, 0, 0))],
            )
        ],
        analyses=[
            TransientCase(id=1, name="step", pattern_ids=[1], dt=DT, n_steps=STEPS, tolerance=1e-10)
        ],
    )
    result = OpenSeesRunner(project).run(
        project.analyses[0], results_dir=Path(tempfile.mkdtemp(prefix="damper_"))
    )
    u = result.node_disp_history(2)[:, 0]
    assert len(u) == STEPS
    peaks = [u[i] for i in range(1, len(u) - 1) if u[i] > u[i - 1] and u[i] >= u[i + 1]]
    return float(peaks[0]) / (FORCE / K)


def _overshoot(c: float) -> float:
    zeta = c / (2.0 * math.sqrt(K * MASS))
    return 1.0 + math.exp(-zeta * math.pi / math.sqrt(1.0 - zeta**2))


@pytest.mark.parametrize("c", [2.0, 5.0])
def test_viscous_damps_like_a_linear_dashpot(c: float) -> None:
    assert _first_peak(Viscous(id=2, C=c, alpha=1.0)) == pytest.approx(_overshoot(c), rel=1e-3)


def test_viscous_damper_with_a_stiff_spring_is_the_dashpot() -> None:
    """A Maxwell spring far stiffer than the frame leaves the dashpot alone."""
    damper = ViscousDamper(id=2, K_el=1e6, Cd=2.0, alpha=1.0)
    assert _first_peak(damper) == pytest.approx(_overshoot(2.0), rel=1e-3)


def test_a_softer_maxwell_spring_damps_less() -> None:
    soft = _first_peak(ViscousDamper(id=2, K_el=50.0, Cd=2.0, alpha=1.0))
    assert soft > _overshoot(2.0) + 0.01
