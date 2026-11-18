"""Generate the Verification Manual: closed-form cases solved by OpenSees Studio.

Every case builds a small model with the public ``core`` API, solves it with the
same :class:`OpenSeesRunner` the application uses, and compares named quantities
with a closed-form or published reference. The manual
(``docs/verification-manual.md``) is generated from those runs, never typed by
hand, so a number in it is always the number the current code produces.

Usage (from the repository root, with the ``opensees`` extra installed)::

    python tools/verification_manual.py           # print the summary table
    python tools/verification_manual.py --write   # regenerate the manual
    python tools/verification_manual.py --check   # fail on a tolerance or a stale manual

``tests/integration/test_verification_manual.py`` runs ``--check`` in CI.

Formatting keeps the file reproducible across platforms: values are printed to
six significant digits and relative errors below 1e-6 are printed as "< 1e-6",
so floating-point noise at 1e-12 never changes the manual.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
MANUAL = REPO / "docs" / "verification-manual.md"

#: Relative errors below this are printed as "< 1e-6" (and are noise).
_NOISE = 1e-6


@dataclass(frozen=True)
class Check:
    """One compared quantity."""

    quantity: str
    unit: str
    computed: float
    reference: float
    tolerance: float
    """Largest relative error accepted."""

    @property
    def error(self) -> float:
        if self.reference == 0.0:
            return abs(self.computed)
        return abs(self.computed - self.reference) / abs(self.reference)

    @property
    def passed(self) -> bool:
        return self.error <= self.tolerance


@dataclass(frozen=True)
class Case:
    """A verification case: a model, a reference and the quantities compared."""

    key: str
    title: str
    group: str
    reference: str
    """Where the closed form comes from."""
    model: str
    """What is built, in Markdown."""
    run: Callable[[], list[Check]]


@dataclass
class Outcome:
    case: Case
    checks: list[Check] = field(default_factory=list)
    error: str = ""

    @property
    def passed(self) -> bool:
        return not self.error and all(check.passed for check in self.checks)


# ──────────────────────────── shared material ────────────────────────────
E = 200e9  # Pa
G = 77e9  # Pa
NU = 0.3


def _run(project: Any, case: Any) -> Any:
    from opensees_studio.services.opensees_runner import OpenSeesRunner

    project.validate_references()
    return OpenSeesRunner(project).run(case)


def _frame_2d(
    nodes: list[tuple[float, float]],
    *,
    restraints: dict[int, tuple[bool, bool, bool]],
    area: float,
    inertia: float,
    shear_area: float | None = None,
    rho: float = 0.0,
    masses: dict[int, float] | None = None,
    element_type: str = "elastic",
    geom_transf: str = "Linear",
) -> Any:
    """A 2D frame in the X-Z plane: consecutive nodes joined by members, ids from 1."""
    from opensees_studio.core import ElasticBeamColumn, ElasticSection, Node, Project

    built = []
    for k, (x, z) in enumerate(nodes, start=1):
        fixed = restraints.get(k, (False, False, False))
        mass = (masses or {}).get(k, 0.0)
        built.append(
            Node(
                id=k,
                coords=(x, 0.0, z),
                restraint=(fixed[0], False, fixed[1], False, fixed[2], False),
                mass=(mass, 0.0, mass, 0.0, 0.0, 0.0),
            )
        )
    section = ElasticSection(
        id=1,
        name="S",
        E=E,
        A=area,
        Iz=inertia,
        **({"G": G, "As2": shear_area} if shear_area is not None else {}),
    )
    elements = [
        ElasticBeamColumn(
            id=k,
            nodes=(k, k + 1),
            section_id=1,
            rho=rho,
            consistent_mass=rho > 0,
            geom_transf=geom_transf,  # type: ignore[arg-type]
        )
        for k in range(1, len(nodes))
    ]
    del element_type
    return Project(ndm=2, ndf=3, nodes=built, sections=[section], elements=elements)


def _static(project: Any, pattern: Any, **case_options: Any) -> Any:
    from opensees_studio.core import LinearTimeSeries, StaticCase

    project.time_series.append(LinearTimeSeries(id=1, name="Ramp"))
    project.load_patterns.append(pattern)
    case = StaticCase(id=1, name="Static", pattern_ids=[pattern.id], **case_options)
    project.analyses.append(case)
    return _run(project, case)


# ──────────────────────────── statics: beams ────────────────────────────
def _cantilever_tip() -> list[Check]:
    from opensees_studio.core import NodalLoad, PlainLoadPattern

    L, P, A, I = 4.0, 10e3, 0.01, 8e-5  # noqa: E741
    project = _frame_2d(
        [(0.0, 0.0), (L, 0.0)], restraints={1: (True, True, True)}, area=A, inertia=I
    )
    load = NodalLoad(node_id=2, forces=(0.0, 0.0, -P, 0.0, 0.0, 0.0))
    r = _static(project, PlainLoadPattern(id=1, name="P", time_series_id=1, nodal_loads=[load]))
    tip = r.node_disp[2][-1]
    base = r.node_reaction[1][-1]
    return [
        Check("Tip deflection", "m", -tip[1], P * L**3 / (3 * E * I), 1e-9),
        Check("Tip rotation", "rad", abs(tip[2]), P * L**2 / (2 * E * I), 1e-9),
        Check("Base shear", "N", base[1], P, 1e-9),
        Check("Base moment", "N·m", abs(base[2]), P * L, 1e-9),
    ]


def _cantilever_udl() -> list[Check]:
    from opensees_studio.core import PlainLoadPattern, UniformElementLoad

    L, w, A, I, n = 4.0, 5e3, 0.01, 8e-5, 4  # noqa: E741
    project = _frame_2d(
        [(L * k / n, 0.0) for k in range(n + 1)],
        restraints={1: (True, True, True)},
        area=A,
        inertia=I,
    )
    loads = [UniformElementLoad(element_id=k, wy=-w) for k in range(1, n + 1)]
    r = _static(project, PlainLoadPattern(id=1, name="w", time_series_id=1, element_loads=loads))
    base = r.node_reaction[1][-1]
    return [
        Check("Tip deflection", "m", -r.node_disp[n + 1][-1][1], w * L**4 / (8 * E * I), 1e-9),
        Check("Base shear", "N", base[1], w * L, 1e-9),
        Check("Base moment", "N·m", abs(base[2]), w * L**2 / 2, 1e-9),
    ]


def _simply_supported_udl() -> list[Check]:
    from opensees_studio.core import PlainLoadPattern, UniformElementLoad

    L, w, A, I = 6.0, 8e3, 0.01, 8e-5  # noqa: E741
    project = _frame_2d(
        [(0.0, 0.0), (L / 2, 0.0), (L, 0.0)],
        restraints={1: (True, True, False), 3: (False, True, False)},
        area=A,
        inertia=I,
    )
    loads = [UniformElementLoad(element_id=k, wy=-w) for k in (1, 2)]
    r = _static(project, PlainLoadPattern(id=1, name="w", time_series_id=1, element_loads=loads))
    return [
        Check(
            "Midspan deflection", "m", -r.node_disp[2][-1][1], 5 * w * L**4 / (384 * E * I), 1e-9
        ),
        Check("Support reaction", "N", r.node_reaction[1][-1][1], w * L / 2, 1e-9),
        Check("End rotation", "rad", abs(r.node_disp[1][-1][2]), w * L**3 / (24 * E * I), 1e-9),
    ]


def _fixed_fixed_udl() -> list[Check]:
    from opensees_studio.core import PlainLoadPattern, UniformElementLoad

    L, w, A, I = 6.0, 8e3, 0.01, 8e-5  # noqa: E741
    project = _frame_2d(
        [(0.0, 0.0), (L / 2, 0.0), (L, 0.0)],
        restraints={1: (True, True, True), 3: (True, True, True)},
        area=A,
        inertia=I,
    )
    loads = [UniformElementLoad(element_id=k, wy=-w) for k in (1, 2)]
    r = _static(project, PlainLoadPattern(id=1, name="w", time_series_id=1, element_loads=loads))
    return [
        Check("Midspan deflection", "m", -r.node_disp[2][-1][1], w * L**4 / (384 * E * I), 1e-9),
        Check("End moment", "N·m", abs(r.node_reaction[1][-1][2]), w * L**2 / 12, 1e-9),
        Check("End shear", "N", r.node_reaction[3][-1][1], w * L / 2, 1e-9),
    ]


def _timoshenko_cantilever() -> list[Check]:
    from opensees_studio.core import NodalLoad, PlainLoadPattern

    # A deep, short member: shear deformation is a fifth of the deflection.
    L, P, b, h = 1.0, 100e3, 0.2, 0.5
    A, I, As = b * h, b * h**3 / 12, 5 / 6 * b * h  # noqa: E741
    project = _frame_2d(
        [(0.0, 0.0), (L, 0.0)], restraints={1: (True, True, True)}, area=A, inertia=I, shear_area=As
    )
    load = NodalLoad(node_id=2, forces=(0.0, 0.0, -P, 0.0, 0.0, 0.0))
    r = _static(project, PlainLoadPattern(id=1, name="P", time_series_id=1, nodal_loads=[load]))
    bending = P * L**3 / (3 * E * I)
    shear = P * L / (G * As)
    return [
        Check(
            "Tip deflection (bending + shear)", "m", -r.node_disp[2][-1][1], bending + shear, 1e-9
        ),
    ]


def _cantilever_3d() -> list[Check]:
    from opensees_studio.core import (
        ElasticBeamColumn,
        ElasticSection,
        NodalLoad,
        Node,
        PlainLoadPattern,
        Project,
    )

    L, A, Iz, Iy, J = 3.0, 0.01, 1.2e-4, 4.0e-5, 2.0e-6
    Fy, Fz, T = 2e3, 3e3, 1e3
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(L, 0.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, name="S", E=E, G=G, A=A, Iz=Iz, Iy=Iy, J=J)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
    )
    load = NodalLoad(node_id=2, forces=(0.0, Fy, Fz, T, 0.0, 0.0))
    r = _static(project, PlainLoadPattern(id=1, name="P", time_series_id=1, nodal_loads=[load]))
    tip = r.node_disp[2][-1]
    # A beam along X has local y = global Y and local z = global Z (vecxz = Z):
    # a load along Y bends about local z (Iz), a load along Z about local y (Iy).
    return [
        Check("Deflection along Y (Iz)", "m", tip[1], Fy * L**3 / (3 * E * Iz), 1e-9),
        Check("Deflection along Z (Iy)", "m", tip[2], Fz * L**3 / (3 * E * Iy), 1e-9),
        Check("Twist", "rad", tip[3], T * L / (G * J), 1e-9),
    ]


def _two_bar_truss() -> list[Check]:
    from opensees_studio.core import (
        ElasticUniaxial,
        NodalLoad,
        Node,
        PlainLoadPattern,
        Project,
        TrussElement,
    )

    span, rise, A, P = 4.0, 1.5, 1e-3, 50e3
    length = math.hypot(span / 2, rise)
    sin = rise / length
    project = Project(
        ndm=2,
        ndf=2,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, False, True, False, False, False)),
            Node(id=2, coords=(span, 0.0, 0.0), restraint=(True, False, True, False, False, False)),
            Node(id=3, coords=(span / 2, 0.0, rise)),
        ],
        materials=[ElasticUniaxial(id=1, name="Steel", E=E)],
        elements=[
            TrussElement(id=1, nodes=(1, 3), area=A, material_id=1),
            TrussElement(id=2, nodes=(2, 3), area=A, material_id=1),
        ],
    )
    load = NodalLoad(node_id=3, forces=(0.0, 0.0, -P, 0.0, 0.0, 0.0))
    r = _static(project, PlainLoadPattern(id=1, name="P", time_series_id=1, nodal_loads=[load]))
    force = P / (2 * sin)
    return [
        Check(
            "Apex deflection", "m", -r.node_disp[3][-1][1], P * length / (2 * E * A * sin**2), 1e-9
        ),
        Check("Vertical reaction", "N", r.node_reaction[1][-1][1], P / 2, 1e-9),
        Check(
            "Horizontal reaction (bar force × cos θ)",
            "N",
            abs(r.node_reaction[1][-1][0]),
            force * (span / 2) / length,
            1e-9,
        ),
    ]


def _settlement() -> list[Check]:
    from opensees_studio.core import ImposedDisplacement, PlainLoadPattern

    L, A, I, delta = 5.0, 0.01, 8e-5, 0.01  # noqa: E741
    # The midspan joint gives the solver free DOFs (a single member between two
    # fixed ends has none).
    project = _frame_2d(
        [(0.0, 0.0), (L / 2, 0.0), (L, 0.0)],
        restraints={1: (True, True, True), 3: (True, True, True)},
        area=A,
        inertia=I,
    )
    settle = ImposedDisplacement(node_id=3, dof=2, value=-delta)
    r = _static(
        project,
        PlainLoadPattern(id=1, name="Settle", time_series_id=1, imposed_displacements=[settle]),
    )
    return [
        Check("Settled end displacement", "m", -r.node_disp[3][-1][1], delta, 1e-12),
        Check("Midspan displacement (Δ/2)", "m", -r.node_disp[2][-1][1], delta / 2, 1e-9),
        Check("End shear", "N", abs(r.node_reaction[1][-1][1]), 12 * E * I * delta / L**3, 1e-9),
        Check("End moment", "N·m", abs(r.node_reaction[1][-1][2]), 6 * E * I * delta / L**2, 1e-9),
    ]


def _p_delta() -> list[Check]:
    from opensees_studio.core import NodalLoad, PlainLoadPattern

    L, A, I, n = 5.0, 0.01, 8e-5, 10  # noqa: E741
    p_cr = math.pi**2 * E * I / (4 * L**2)
    P, H = 0.3 * p_cr, 1e3
    project = _frame_2d(
        [(0.0, L * k / n) for k in range(n + 1)],
        restraints={1: (True, True, True)},
        area=A,
        inertia=I,
        geom_transf="PDelta",
    )
    load = NodalLoad(node_id=n + 1, forces=(H, 0.0, -P, 0.0, 0.0, 0.0))
    r = _static(
        project,
        PlainLoadPattern(id=1, name="P+H", time_series_id=1, nodal_loads=[load]),
        n_steps=10,
        load_factor_increment=0.1,
        algorithm="Newton",
        tolerance=1e-12,
    )
    k = math.sqrt(P / (E * I))
    exact = H * (math.tan(k * L) - k * L) / (P * k)
    return [
        Check("Tip drift with P = 0.3 Pcr", "m", r.node_disp[n + 1][-1][0], exact, 2e-3),
        Check(
            "Amplification over first order",
            "-",
            r.node_disp[n + 1][-1][0] / (H * L**3 / (3 * E * I)),
            exact / (H * L**3 / (3 * E * I)),
            2e-3,
        ),
    ]


# ──────────────────────────── dynamics ────────────────────────────
def _sdof_project() -> tuple[Any, float, float]:
    """A massless cantilever column with a lumped mass on top: k = 3EI/L³."""
    L, A, I, m = 3.0, 0.01, 8e-5, 5000.0  # noqa: E741
    project = _frame_2d(
        [(0.0, 0.0), (0.0, L)],
        restraints={1: (True, True, True)},
        area=A,
        inertia=I,
        masses={2: m},
    )
    # Only the lateral mass: the axial mode would otherwise be mode 1's neighbour.
    project.nodes[1].mass = (m, 0.0, 0.0, 0.0, 0.0, 0.0)
    return project, m, 3 * E * I / L**3


def _sdof_period() -> list[Check]:
    from opensees_studio.core import ModalCase

    project, m, k = _sdof_project()
    case = ModalCase(id=1, name="Modal", n_modes=1)
    project.analyses.append(case)
    r = _run(project, case)
    return [Check("Period", "s", float(r.periods[0]), 2 * math.pi * math.sqrt(m / k), 1e-9)]


def _cantilever_modes() -> list[Check]:
    from opensees_studio.core import ModalCase

    L, b, h, rho, n = 4.0, 0.1, 0.2, 7850.0, 20
    A, I = b * h, b * h**3 / 12  # noqa: E741
    project = _frame_2d(
        [(L * k / n, 0.0) for k in range(n + 1)],
        restraints={1: (True, True, True)},
        area=A,
        inertia=I,
        rho=rho * A,
    )
    case = ModalCase(id=1, name="Modal", n_modes=2)
    project.analyses.append(case)
    r = _run(project, case)
    beta = (1.875104068711961, 4.694091132974175)
    exact = [(bl**2 / (2 * math.pi * L**2)) * math.sqrt(E * I / (rho * A)) for bl in beta]
    return [
        Check("Frequency, mode 1", "Hz", float(r.frequencies[0]), exact[0], 1e-4),
        Check("Frequency, mode 2", "Hz", float(r.frequencies[1]), exact[1], 1e-4),
    ]


def _step_load() -> list[Check]:
    from opensees_studio.core import ConstantTimeSeries, NodalLoad, PlainLoadPattern, TransientCase

    project, m, k = _sdof_project()
    F = 10e3
    period = 2 * math.pi * math.sqrt(m / k)
    dt = period / 400
    project.time_series.append(ConstantTimeSeries(id=1, name="Step"))
    project.load_patterns.append(
        PlainLoadPattern(
            id=1,
            name="Step",
            time_series_id=1,
            nodal_loads=[NodalLoad(node_id=2, forces=(F, 0.0, 0.0, 0.0, 0.0, 0.0))],
        )
    )
    case = TransientCase(id=1, name="Step", pattern_ids=[1], dt=dt, n_steps=600, algorithm="Linear")
    project.analyses.append(case)
    r = _run(project, case)
    history = r.node_disp_history(2)[:, 0]
    return [
        Check("Peak displacement (2 F / k)", "m", float(np.max(history)), 2 * F / k, 1e-3),
        Check("Static offset (mean of one cycle)", "m", float(np.mean(history[:400])), F / k, 1e-2),
    ]


def _spectrum_sdof() -> list[Check]:
    from opensees_studio.core import ModalCase, ResponseSpectrum, ResponseSpectrumCase

    project, m, k = _sdof_project()
    sa = 3.0
    project.spectra.append(
        ResponseSpectrum(id=1, name="Flat", periods=[0.01, 10.0], accelerations=[sa, sa])
    )
    project.analyses.append(ModalCase(id=1, name="Modal", n_modes=1))
    case = ResponseSpectrumCase(id=2, name="RSX", modal_case_id=1, spectrum_id=1, direction=1)
    project.analyses.append(case)
    r = _run(project, case)
    omega2 = k / m
    return [
        Check("Peak displacement (Sa / ω²)", "m", float(r.combined_disp[2][0]), sa / omega2, 1e-9),
        Check("Base shear (m Sa)", "N", float(abs(r.node_reaction[1][0])), m * sa, 1e-9),
    ]


# ──────────────────────────── shells and nonlinear ────────────────────────────
def _plate() -> list[Check]:
    from opensees_studio.core import (
        ElasticMembranePlateSection,
        LinearTimeSeries,
        Node,
        PlainLoadPattern,
        Project,
        ShellMITC4Element,
        StaticCase,
        SurfaceLoad,
    )

    a, h, q, n = 2.0, 0.02, 1e3, 16
    step = a / n
    nodes = []
    for j in range(n + 1):
        for i in range(n + 1):
            edge = i in (0, n) or j in (0, n)
            nodes.append(
                Node(
                    id=j * (n + 1) + i + 1,
                    coords=(i * step, j * step, 0.0),
                    restraint=(edge, edge, edge, False, False, False),
                )
            )
    elements = []
    for j in range(n):
        for i in range(n):
            first = j * (n + 1) + i + 1
            elements.append(
                ShellMITC4Element(
                    id=j * n + i + 1,
                    nodes=(first, first + 1, first + n + 2, first + n + 1),
                    section_id=1,
                )
            )
    project = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[ElasticMembranePlateSection(id=1, name="Plate", E=E, nu=NU, h=h)],
        elements=elements,
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="q",
                time_series_id=1,
                surface_loads=[
                    SurfaceLoad(element_id=e.id, value=-q, direction="Z") for e in elements
                ],
            )
        ],
    )
    case = StaticCase(id=1, name="q", pattern_ids=[1])
    project.analyses.append(case)
    r = _run(project, case)
    centre = (n // 2) * (n + 1) + n // 2 + 1
    D = E * h**3 / (12 * (1 - NU**2))
    return [
        Check(
            "Centre deflection (0.00406 q a⁴ / D)",
            "m",
            -float(r.node_disp[centre][-1][2]),
            0.00406235 * q * a**4 / D,
            1e-2,
        )
    ]


def _plastic_moment() -> list[Check]:
    from opensees_studio.core import (
        ElasticPP,
        FiberSection,
        ForceBeamColumn,
        LinearTimeSeries,
        NodalLoad,
        Node,
        PlainLoadPattern,
        Project,
        PushoverCase,
        RectangularPatch,
    )

    L, b, h, fy = 3.0, 0.3, 0.5, 250e6
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, False, True, False, True, False)),
            Node(id=2, coords=(0.0, 0.0, L)),
        ],
        materials=[ElasticPP(id=1, name="EPP", E=E, epsy_pos=fy / E)],
        sections=[
            FiberSection(
                id=1,
                name="Rect",
                patches=[
                    RectangularPatch(
                        material_id=1,
                        n_fib_y=60,
                        n_fib_z=1,
                        y_i=-h / 2,
                        z_i=-b / 2,
                        y_j=h / 2,
                        z_j=b / 2,
                    )
                ],
            )
        ],
        elements=[ForceBeamColumn(id=1, nodes=(1, 2), section_id=1, integration_points=5)],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="H",
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0))],
            )
        ],
    )
    yield_disp = (fy / E) * (2 / h) * L**2 / 3
    case = PushoverCase(
        id=1,
        name="Push",
        pattern_ids=[1],
        control_node=2,
        control_dof=1,
        # Not further: once every fibre of the base section has yielded, a perfectly
        # plastic section has no tangent stiffness and the force-based element's
        # section iterations stop converging (the moment then drifts above Mp).
        target_disp=8 * yield_disp,
        step_size=yield_disp / 10,
        base_nodes=[1],
    )
    project.analyses.append(case)
    r = _run(project, case)
    moment = abs(float(r.base_shear[-1])) * L
    return [
        Check("Base moment at 8 yield drifts (fy b h² / 4)", "N·m", moment, fy * b * h**2 / 4, 1e-3)
    ]


def _influence_lines() -> list[Check]:
    from opensees_studio.core import InfluenceLineCase
    from opensees_studio.core.analysis import Axle
    from opensees_studio.services.influence import influence_line, vehicle_envelope

    span, A, I = 8.0, 0.01, 1e-4  # noqa: E741
    project = _frame_2d(
        [(k * span / 2, 0.0) for k in range(5)],
        restraints={1: (True, True, False), 3: (False, True, False), 5: (False, True, False)},
        area=A,
        inertia=I,
    )
    case = InfluenceLineCase(id=1, name="IL", path=[1, 2, 3, 4], stations=8)
    project.analyses.append(case)
    results = _run(project, case)
    middle = influence_line(project, results, "reaction", 3, "Uz")
    at = {round(float(d), 9): k for k, d in enumerate(results.distances)}
    quarter = middle[at[span / 2]]
    first = influence_line(project, results, "reaction", 1, "Uz")
    # Two 100 kN axles 2 m apart: R_A peaks with one axle on the support and the
    # other 2 m into the first span.
    a = 2.0
    r_a = first[at[0.0]]
    found = vehicle_envelope(results, first, [Axle(load=100.0), Axle(load=100.0, offset=a)])
    exact_two = 100.0 * (1.0 + _two_span_end_reaction(a, span))
    return [
        Check(
            "Middle reaction, load at mid first span (11/16)", "-", float(quarter), 11 / 16, 1e-9
        ),
        Check("End reaction, load on that support", "-", float(r_a), 1.0, 1e-9),
        Check(
            "End reaction under two 100 kN axles 2 m apart", "kN", found.maximum, exact_two, 1e-9
        ),
    ]


def _two_span_end_reaction(x: float, span: float) -> float:
    """End reaction of a two-span continuous beam, unit load at x in the first span."""
    middle = x * (3 * span**2 - x**2) / (2 * span**3)
    # Moments about the far support C (at 2L): 2L R_A + L R_B = 2L - x.
    return 1.0 - x / (2 * span) - middle / 2


def _thermal() -> list[Check]:
    from opensees_studio.core import LinearTimeSeries, PlainLoadPattern, TemperatureLoad
    from opensees_studio.services.element_forces import ForceComponent, extract_diagram_data

    L, A, I, alpha, dt, g = 4.0, 0.01, 1e-4, 1.2e-5, 30.0, 100.0  # noqa: E741

    def solve(restraints: dict[int, tuple[bool, bool, bool]], **load: float) -> tuple[Any, Any]:
        project = _frame_2d(
            [(0.0, 0.0), (L / 2, 0.0), (L, 0.0)], restraints=restraints, area=A, inertia=I
        )
        project.time_series.append(LinearTimeSeries(id=1, name="Ramp"))
        pattern = PlainLoadPattern(
            id=1,
            name="Heat",
            time_series_id=1,
            temperature_loads=[TemperatureLoad(element_id=k, alpha=alpha, **load) for k in (1, 2)],
        )
        project.load_patterns.append(pattern)
        from opensees_studio.core import StaticCase

        case = StaticCase(id=1, name="Heat", pattern_ids=[1])
        project.analyses.append(case)
        return project, _run(project, case)

    _, free_r = solve({1: (True, True, True)}, uniform=dt, gradient_y=g)
    held, held_r = solve({1: (True, True, True), 3: (True, True, True)}, uniform=dt, gradient_y=g)
    axial = extract_diagram_data(held, held_r, ForceComponent.N).values_i[0]
    moment = extract_diagram_data(held, held_r, ForceComponent.M3).values_i[0]
    return [
        Check("Free end: elongation α ΔT L", "m", free_r.node_disp[3][-1][0], alpha * dt * L, 1e-9),
        Check(
            "Free end: deflection α g L²/2",
            "m",
            -free_r.node_disp[3][-1][1],
            alpha * g * L**2 / 2,
            1e-9,
        ),
        Check("Held: axial compression EA α ΔT", "N", float(axial), E * A * alpha * dt, 1e-9),
        Check("Held: moment EI α g", "N·m", abs(float(moment)), E * I * alpha * g, 1e-9),
    ]


# ──────────────────────────── design: AISC 360-16 ────────────────────────────
_FT = 12.0  # in


def _aisc(name: str) -> Any:
    from opensees_studio.core.units import UnitSystem
    from opensees_studio.services.steel_design import ishape_in_units

    return ishape_in_units(name, UnitSystem.US_IN_KIP)


def _a992() -> Any:
    from opensees_studio.core.design.aisc360 import Steel

    return Steel(Fy=50.0, E=29000.0, G=11200.0)


def _aisc_compression() -> list[Check]:
    from opensees_studio.core.design.aisc360 import compression

    strength = compression(_aisc("W14X132"), _a992(), "LRFD", length_x=30 * _FT, length_y=30 * _FT)
    return [Check("φc Pn, W14X132, Lc = 30 ft", "kip", strength.available, 892.0, 2e-3)]


def _aisc_flexure() -> list[Check]:
    from opensees_studio.core.design.aisc360 import flexure_major, lp_lr

    shape = _aisc("W18X50")
    lp, lr = lp_lr(shape, _a992())
    braced = flexure_major(shape, _a992(), "LRFD", unbraced=0.0)
    ltb = flexure_major(shape, _a992(), "LRFD", unbraced=11.67 * _FT, cb=1.01)
    return [
        Check("Lp", "ft", lp / _FT, 5.83, 2e-3),
        Check("Lr", "ft", lr / _FT, 16.9, 5e-3),
        Check("φb Mn, continuously braced (F.1-1A)", "kip·ft", braced.available / _FT, 379.0, 2e-3),
        Check(
            "φb Mn, Lb = 11.67 ft, Cb = 1.01 (F.1-2A)", "kip·ft", ltb.available / _FT, 306.0, 3e-3
        ),
    ]


def _aisc_shear() -> list[Check]:
    from opensees_studio.core.design.aisc360 import shear_major

    strength = shear_major(_aisc("W24X62"), _a992(), "LRFD")
    return [Check("φv Vn, W24X62", "kip", strength.available, 306.0, 2e-3)]


def _aisc_interaction() -> list[Check]:
    from opensees_studio.core.design.aisc360 import (
        compression,
        flexure_major,
        flexure_minor,
        interaction,
    )

    shape = _aisc("W14X99")
    pc = compression(shape, _a992(), "LRFD", length_x=14 * _FT, length_y=14 * _FT).available
    mcx = flexure_major(shape, _a992(), "LRFD", unbraced=14 * _FT).available
    mcy = flexure_minor(shape, _a992(), "LRFD").available
    ratio, _ = interaction(-400.0, pc, 250 * _FT, mcx, 80 * _FT, mcy)
    return [
        Check("φc Pn, Lc = 14 ft", "kip", pc, 1130.0, 3e-3),
        Check("φb Mnx, Lb = 14 ft", "kip·ft", mcx / _FT, 642.0, 2e-3),
        Check("φb Mny", "kip·ft", mcy / _FT, 311.0, 2e-3),
        Check("H1-1a ratio, Pr = 400, Mrx = 250, Mry = 80", "-", ratio, 0.928, 3e-3),
    ]


def _aisc_beam_check() -> list[Check]:
    """The whole chain: OpenSees diagrams → demands → ratio, against wL²/8 by hand."""
    from opensees_studio.core import (
        ElasticBeamColumn,
        LinearTimeSeries,
        Node,
        PlainLoadPattern,
        Project,
        ProjectMeta,
        StaticCase,
        UniformElementLoad,
        UnitSystem,
    )
    from opensees_studio.core.aisc import get_shape, shape_to_elastic_section
    from opensees_studio.core.design.aisc360 import flexure_major
    from opensees_studio.core.design.settings import DesignSettings, SteelMemberDesign
    from opensees_studio.services.steel_design import steel_frame_check

    span, w = 20 * _FT, 0.22  # in, kip/in
    units = UnitSystem.US_IN_KIP
    section = shape_to_elastic_section(
        get_shape("W18X50"), elastic_modulus=29000.0, shear_modulus=11200.0, units=units, ndm=2
    )
    project = Project(
        meta=ProjectMeta(units=units),
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, False, True, False, False, False)),
            Node(
                id=2, coords=(span, 0.0, 0.0), restraint=(False, False, True, False, False, False)
            ),
        ],
        sections=[section],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="w",
                time_series_id=1,
                element_loads=[UniformElementLoad(element_id=1, wy=-w)],
            )
        ],
    )
    case = StaticCase(id=1, name="w", pattern_ids=[1])
    project.analyses.append(case)
    results = _run(project, case)
    report = steel_frame_check(
        project, {1: results}, DesignSettings(members=[SteelMemberDesign(element_id=1)])
    )
    member = report.members[0]
    capacity = flexure_major(_aisc("W18X50"), _a992(), "LRFD", unbraced=span, cb=1.136).available
    return [
        Check(
            "Major flexure ratio (wL²/8) / φb Mn, Cb from the diagram",
            "-",
            member.ratios["Major flexure"],
            w * span**2 / 8 / capacity,
            2e-3,
        ),
        Check(
            "Major shear ratio (wL/2) / φv Vn",
            "-",
            member.ratios["Major shear"],
            w * span / 2 / (1.0 * 0.6 * 50.0 * 18.0 * 0.355),
            1e-6,
        ),
    ]


# ──────────────────────────── catalogue ────────────────────────────
CASES: list[Case] = [
    Case(
        "V-01",
        "Cantilever with a tip load",
        "Static, beams",
        "Euler-Bernoulli beam theory: δ = PL³/3EI, θ = PL²/2EI.",
        "2D cantilever, L = 4 m, one elastic beam-column; P = 10 kN down at the tip.",
        _cantilever_tip,
    ),
    Case(
        "V-02",
        "Cantilever with a uniform load",
        "Static, beams",
        "δ = wL⁴/8EI, M = wL²/2.",
        "2D cantilever, L = 4 m in 4 members, w = 5 kN/m as element loads.",
        _cantilever_udl,
    ),
    Case(
        "V-03",
        "Simply supported beam, uniform load",
        "Static, beams",
        "δ = 5wL⁴/384EI, R = wL/2, θ = wL³/24EI.",
        "2D beam, L = 6 m in 2 members, pin and roller, w = 8 kN/m.",
        _simply_supported_udl,
    ),
    Case(
        "V-04",
        "Fixed-fixed beam, uniform load",
        "Static, beams",
        "δ = wL⁴/384EI, M = wL²/12.",
        "2D beam, L = 6 m in 2 members, both ends fixed, w = 8 kN/m.",
        _fixed_fixed_udl,
    ),
    Case(
        "V-05",
        "Timoshenko cantilever",
        "Static, beams",
        "δ = PL³/3EI + PL/(G·As), As = 5/6 bh.",
        "2D cantilever 0.2 × 0.5 m, L = 1 m, section with a shear area "
        "(run as `ElasticTimoshenkoBeam`).",
        _timoshenko_cantilever,
    ),
    Case(
        "V-06",
        "3D cantilever: biaxial bending and torsion",
        "Static, beams",
        "δy = FyL³/3EIz, δz = FzL³/3EIy, φ = TL/GJ.",
        "3D cantilever along X, L = 3 m, Iz = 3 Iy; tip loads along Y and Z and a torque.",
        _cantilever_3d,
    ),
    Case(
        "V-07",
        "Two-bar truss",
        "Static, trusses",
        "Statics: N = P/(2 sin θ); virtual work: δ = PL/(2EA sin²θ).",
        "2D truss (ndf = 2), span 4 m, rise 1.5 m, P = 50 kN at the apex.",
        _two_bar_truss,
    ),
    Case(
        "V-08",
        "Support settlement",
        "Static, imposed displacements",
        "V = 12EIΔ/L³, M = 6EIΔ/L².",
        "2D fixed-fixed beam, L = 5 m in 2 members; the right support settles Δ = 10 mm.",
        _settlement,
    ),
    Case(
        "V-09",
        "P-Δ: cantilever column under axial load",
        "Static, second order",
        "Beam-column: δ = H (tan kL - kL)/(P k), k = √(P/EI).",
        "2D column, L = 5 m in 10 members with the `PDelta` transformation; P = 0.3 Pcr "
        "and H = 1 kN at the top, Newton in 10 steps.",
        _p_delta,
    ),
    Case(
        "V-10",
        "SDOF period",
        "Dynamics, modal",
        "T = 2π √(m/k), k = 3EI/L³.",
        "Massless 2D cantilever column, L = 3 m, with m = 5 t lumped at the top (lateral).",
        _sdof_period,
    ),
    Case(
        "V-11",
        "Cantilever natural frequencies",
        "Dynamics, modal",
        "f = (βL)²/(2πL²) √(EI/ρA), βL = 1.8751, 4.6941.",
        "2D steel cantilever 0.1 × 0.2 m, L = 4 m in 20 members, consistent mass.",
        _cantilever_modes,
    ),
    Case(
        "V-12",
        "SDOF under a step load",
        "Dynamics, time history",
        "Undamped step response: u(t) = F/k (1 - cos ωt), peak 2F/k.",
        "The V-10 oscillator, F = 10 kN applied at t = 0, Newmark average acceleration, "
        "Δt = T/400.",
        _step_load,
    ),
    Case(
        "V-13",
        "Response spectrum of an SDOF",
        "Dynamics, response spectrum",
        "u = Sa/ω², V = m·Sa.",
        "The V-10 oscillator under a flat spectrum Sa = 3 m/s² in X.",
        _spectrum_sdof,
    ),
    Case(
        "V-14",
        "Simply supported square plate, uniform pressure",
        "Shells",
        "Timoshenko & Woinowsky-Krieger, *Theory of Plates and Shells*, Table 8 "
        "(ν = 0.3): w = 0.00406 qa⁴/D.",
        "2 × 2 m plate, h = 20 mm, 16 × 16 `ShellMITC4`, all edges simply supported, q = 1 kPa.",
        _plate,
    ),
    Case(
        "V-15",
        "Plastic moment of a rectangle",
        "Nonlinear, fibre sections",
        "Mp = fy·b·h²/4.",
        "2D cantilever column, L = 3 m, one force-based element with a 60-fibre "
        "0.3 × 0.5 m elastic-perfectly-plastic section, pushed to 8 yield displacements. "
        "Beyond about 10, the fully yielded section has no tangent stiffness and OpenSees' "
        "force-based element no longer converges its section state: give a perfectly "
        "plastic material a little hardening for large drifts.",
        _plastic_moment,
    ),
    Case(
        "V-16",
        "Influence lines of a two-span continuous beam",
        "Influence lines, moving loads",
        "Müller-Breslau: R_B = x (3L² - x²)/(2L³), 11/16 at mid first span; "
        "R_A = 1 - x/(2L) - R_B/2 (moments about the far support).",
        "2D beam, two spans of 8 m in four members, a unit load walked over 33 stops; "
        "a vehicle of two 100 kN axles 2 m apart moved across both ways.",
        _influence_lines,
    ),
    Case(
        "V-17",
        "Temperature: uniform change and gradient",
        "Static, temperature loads",
        "Free member: δ = α ΔT L, w = α g L²/2. Member held at both ends: N = EA α ΔT, M = EI α g.",
        "2D member, L = 4 m in two members, ΔT = 30 °C and a gradient of 100 °C/m "
        "across local y, α = 1.2e-5; once as a cantilever, once fixed at both ends.",
        _thermal,
    ),
    Case(
        "D-01",
        "AISC: column available strength",
        "Design, AISC 360-16",
        "AISC *Design Examples* v16.0, Example E.1A; Manual Table 4-1a: 892 kips.",
        "W14X132, Fy = 50 ksi, Lc = 30 ft about both axes (E3, minor-axis buckling).",
        _aisc_compression,
    ),
    Case(
        "D-02",
        "AISC: beam flexural strength and LTB",
        "Design, AISC 360-16",
        "AISC *Design Examples* v16.0, Examples F.1-1A and F.1-2A; Manual Table 3-2 "
        "(Lp = 5.83 ft, Lr = 16.9 ft).",
        "W18X50, Fy = 50 ksi; continuously braced, and braced at thirds of a 35 ft span.",
        _aisc_flexure,
    ),
    Case(
        "D-03",
        "AISC: web shear strength",
        "Design, AISC 360-16",
        "AISC *Design Examples* v16.0, Example G.1A: 306 kips (φv = 1.00).",
        "W24X62, Fy = 50 ksi (G2.1(a)).",
        _aisc_shear,
    ),
    Case(
        "D-04",
        "AISC: combined axial force and biaxial flexure",
        "Design, AISC 360-16",
        "AISC *Design Examples* v16.0, Example H.1A.",
        "W14X99, Fy = 50 ksi, Lc = Lb = 14 ft, Pu = 400 kips, Mux = 250 and Muy = 80 kip-ft.",
        _aisc_interaction,
    ),
    Case(
        "D-05",
        "Steel frame check of a beam, end to end",
        "Design, AISC 360-16",
        "M = wL²/8, V = wL/2, Cb = 1.136 for a uniform load (F1-1).",
        "Simply supported W18X50, 20 ft, w = 0.22 kip/in, solved by OpenSees and checked by "
        "Design → Steel Frame Check with Lb = the span.",
        _aisc_beam_check,
    ),
]


# ──────────────────────────── running and rendering ────────────────────────────
def run_all(cases: list[Case] | None = None) -> list[Outcome]:
    outcomes = []
    for case in cases or CASES:
        try:
            outcomes.append(Outcome(case, case.run()))
        except Exception as exc:  # a case that cannot run is a failed case, not a crash
            outcomes.append(Outcome(case, error=f"{type(exc).__name__}: {exc}"))
    return outcomes


def _value(x: float) -> str:
    return f"{x:.6g}"


def _error(check: Check) -> str:
    return f"< {_NOISE:.0e}" if check.error < _NOISE else f"{check.error:.1e}"


def render(outcomes: list[Outcome]) -> str:
    passed = sum(o.passed for o in outcomes)
    lines = [
        "# Verification Manual",
        "",
        "<!-- Generated by tools/verification_manual.py. Do not edit by hand:",
        "     run `python tools/verification_manual.py --write` instead. -->",
        "",
        "Each case below is a small model built with the public `core` API and solved",
        "by the same `OpenSeesRunner` the application uses. The computed values are",
        "compared with a closed-form or published reference; the relative error must",
        "stay within the tolerance shown. CI regenerates this file and fails when a",
        "tolerance is exceeded or the file is out of date",
        "(`tests/integration/test_verification_manual.py`).",
        "",
        "Units are SI (m, N, kg, s) for the V cases and kip-inch for the D (design)",
        "cases, as in the AISC examples. Errors below 1e-6 are floating-point noise",
        "and are printed as `< 1e-6`.",
        "",
        f"**{passed} of {len(outcomes)} cases pass.**",
        "",
        "| Case | Title | Group | Max. error | Verdict |",
        "|---|---|---|---|---|",
    ]
    for outcome in outcomes:
        worst = max(outcome.checks, key=lambda c: c.error) if outcome.checks else None
        error = _error(worst) if worst is not None else "—"
        verdict = "✅ pass" if outcome.passed else "❌ fail"
        anchor = outcome.case.key.lower()
        lines.append(
            f"| [{outcome.case.key}](#{anchor}) | {outcome.case.title} | "
            f"{outcome.case.group} | {error} | {verdict} |"
        )
    for outcome in outcomes:
        case = outcome.case
        lines += [
            "",
            f'<a id="{case.key.lower()}"></a>',
            "",
            f"## {case.key} — {case.title}",
            "",
            f"**Model.** {case.model}",
            "",
            f"**Reference.** {case.reference}",
            "",
        ]
        if outcome.error:
            lines += [f"**Could not run:** `{outcome.error}`"]
            continue
        lines += [
            "| Quantity | Unit | OpenSees Studio | Reference | Rel. error | Tolerance | |",
            "|---|---|---|---|---|---|---|",
        ]
        for check in outcome.checks:
            mark = "✅" if check.passed else "❌"
            lines.append(
                f"| {check.quantity} | {check.unit} | {_value(check.computed)} | "
                f"{_value(check.reference)} | {_error(check)} | {check.tolerance:.0e} | {mark} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="regenerate the manual")
    mode.add_argument("--check", action="store_true", help="fail on a tolerance or a stale manual")
    args = parser.parse_args(argv)

    outcomes = run_all()
    text = render(outcomes)
    failed = [o for o in outcomes if not o.passed]
    for outcome in failed:
        detail = outcome.error or ", ".join(
            f"{c.quantity}: {c.error:.2e} > {c.tolerance:.0e}"
            for c in outcome.checks
            if not c.passed
        )
        print(f"FAIL {outcome.case.key} {outcome.case.title}: {detail}", file=sys.stderr)

    if args.write:
        MANUAL.write_text(text, encoding="utf-8")
        print(
            f"Wrote {MANUAL.relative_to(REPO)} ({len(outcomes) - len(failed)}/{len(outcomes)} pass)."
        )
        return 1 if failed else 0
    if args.check:
        current = MANUAL.read_text(encoding="utf-8") if MANUAL.exists() else ""
        if current != text:
            print(
                f"{MANUAL.relative_to(REPO)} is out of date: run "
                "`python tools/verification_manual.py --write`.",
                file=sys.stderr,
            )
            return 1
        return 1 if failed else 0
    for outcome in outcomes:
        worst = max((c.error for c in outcome.checks), default=float("nan"))
        verdict = "pass" if outcome.passed else "FAIL"
        print(f"{outcome.case.key}  {verdict:4}  max err {worst:.2e}  {outcome.case.title}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
