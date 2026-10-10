# ruff: noqa: RUF002, RUF003 - the docstrings are the model equations, where σ and ε are the conventional symbols.
"""The library's numbers reach the solver, and the response is the closed form.

Two exact checks, both displacement-controlled axial bars whose fibres all see
the same strain — so there is no discretisation error to hide behind:

- **Concrete01** (``concrete_4000_unconfined``): the Kent-Scott-Park ascending
  branch is ``σ = f'c (2x - x²)`` with ``x = ε/ε0``, so a stress of half the
  specified strength gives ``x = 1 - √(1 - σ/f'c)`` and ``Δ = x ε0 L``. Note
  what the check does *not* need: a modulus. The library's concrete row carries
  none, and the model has none — the parabola is the material.
- **Steel02** (``steel_a992``): the Menegotto-Pinto virgin curve is
  ``σ* = b ε* + (1-b) ε* / (1 + ε*^R)^(1/R)`` with ``ε* = ε/εy`` and
  ``σ* = σ/Fy``; the test inverts it by bisection for a stress 10 % above
  yield, so ``Fy``, ``E0``, ``b`` and ``R0`` are all exercised.
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (
    FiberSection,
    ForceBeamColumn,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    RectangularPatch,
    StaticCase,
    UnitSystem,
)
from opensees_studio.core.material_catalog import load_materials, to_material
from opensees_studio.services.opensees_runner import OpenSeesRunner

L = 1.0  # bar length [m]
SI = UnitSystem.SI_M_N


def _axial_bar(material, material_id: int, *, side: float, load: float) -> Project:
    """A bar along X, fixed at one end and free to move only axially at the other."""
    area = side * side
    return Project(
        meta=ProjectMeta(name="library material", units=SI),
        ndm=2,
        ndf=3,
        nodes=[
            Node(
                id=1,
                name="Base",
                coords=(0.0, 0.0, 0.0),
                restraint=(True, True, True, False, False, False),
            ),
            Node(
                id=2,
                name="Tip",
                coords=(L, 0.0, 0.0),
                restraint=(False, True, True, False, False, False),
            ),
        ],
        materials=[material],
        sections=[
            FiberSection(
                id=1,
                name="Axial fibers",
                patches=[
                    RectangularPatch(
                        material_id=material_id,
                        n_fib_y=2,
                        n_fib_z=2,
                        y_i=-side / 2,
                        z_i=-side / 2,
                        y_j=side / 2,
                        z_j=side / 2,
                    ),
                ],
            ),
        ],
        elements=[
            ForceBeamColumn(
                id=1,
                name="Bar",
                nodes=(1, 2),
                section_id=1,
                integration_points=3,
                geom_transf="Linear",
            ),
        ],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="Axial",
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(load * area, 0.0, 0.0, 0.0, 0.0, 0.0))],
            ),
        ],
        analyses=[
            StaticCase(
                id=1,
                name="Axial",
                pattern_ids=[1],
                n_steps=1,
                load_factor_increment=1.0,
                system="BandGeneral",
                constraints="Plain",
                integrator="LoadControl",
                algorithm="Newton",
                test="NormDispIncr",
                tolerance=1e-12,
                max_iter=20,
            ),
        ],
    )


def test_library_concrete_follows_the_kent_scott_park_parabola() -> None:
    """σ = ½f'c lands on the parabola, 17 % past where a linear E0 would."""
    entry = load_materials()["concrete_4000_unconfined"]
    material = to_material(entry, 1, SI)

    fpc = -material.fpc  # tensile magnitude, Pa
    eps0 = -material.epsc0
    stress = 0.5 * fpc
    # Compression: Concrete01 has no tension stiffness at all.
    project = _axial_bar(material, 1, side=0.3, load=-stress)

    results = OpenSeesRunner(project).run(project.analyses[0])
    displacement = results.disp(2, 1)

    x = 1.0 - math.sqrt(1.0 - stress / fpc)
    expected = -x * eps0 * L
    assert displacement == pytest.approx(expected, rel=2e-3), (
        f"got {displacement:.6e} m, parabola says {expected:.6e} m"
    )
    # The initial tangent is 2f'c/ε0; the parabola is measurably softer by here.
    e0 = 2.0 * fpc / eps0
    linear = -stress * L / e0
    assert displacement < linear * 1.15  # more negative: softer than E0
    assert displacement > linear * 1.20


def test_library_steel_follows_the_menegotto_pinto_curve() -> None:
    """10 % above yield, on the hardening branch, with R0 = 18 as the library sets it."""
    entry = load_materials()["steel_a992"]
    material = to_material(entry, 1, SI)

    fy = material.Fy
    b = material.b
    r0 = material.R0
    ey = fy / material.E0
    sigma_star = 1.10  # σ/Fy, so the hardening branch carries the answer
    project = _axial_bar(material, 1, side=0.1, load=sigma_star * fy)

    results = OpenSeesRunner(project).run(project.analyses[0])
    displacement = results.disp(2, 1)

    def mp(strain_star: float) -> float:
        return b * strain_star + (1.0 - b) * strain_star / (1.0 + strain_star**r0) ** (1.0 / r0)

    # Invert σ*(ε*) by bisection: it is monotonic and the bracket is generous.
    low, high = 1.0, 100.0
    for _ in range(200):
        mid = 0.5 * (low + high)
        if mp(mid) < sigma_star:
            low = mid
        else:
            high = mid
    expected = 0.5 * (low + high) * ey * L

    assert displacement == pytest.approx(expected, rel=2e-3), (
        f"got {displacement:.6e} m, Menegotto-Pinto says {expected:.6e} m"
    )
    # Well past the elastic line: ε ≈ 6 εy, not 1.1 εy.
    assert displacement > 4.0 * sigma_star * ey * L
