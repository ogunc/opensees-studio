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


def _aisc_beam_parts():  # type: ignore[no-untyped-def]
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
    return project, report, member, span, w


def _aisc_beam_check() -> list[Check]:
    from opensees_studio.core.design.aisc360 import flexure_major

    project, report, member, span, w = _aisc_beam_parts()
    del project, report
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


def _aisc_memory_check() -> list[Check]:
    """The calculation memory of the D-05 beam keeps every limit state."""
    from opensees_studio.services.calc_memory import build_member_memory

    project, report, member, _span, _w = _aisc_beam_parts()
    page = build_member_memory(project, report, language="en", fmt="html")
    limit_states = sum(1 for check in member.checks if f">{check.name}</td>" in page)
    steps = sum(
        1 for check in member.checks for step in check.steps if f">{step.label}</td>" in page
    )
    return [
        Check(
            "Limit states printed in the member sheet",
            "-",
            limit_states,
            len(member.checks),
            0.0,
        ),
        Check(
            "Calculation steps printed",
            "-",
            steps,
            sum(len(check.steps) for check in member.checks),
            0.0,
        ),
        Check(
            "Governing ratio printed",
            "-",
            1.0 if f"{member.ratio:.4g}" in page else 0.0,
            1.0,
            0.0,
        ),
    ]


def _aisc_expected_brace() -> list[Check]:
    """F2.3: expected tension and compression of a W18X50 brace."""
    from opensees_studio.core.design.aisc341 import expected_brace_strength

    shape = _aisc("W18X50")
    steel = _a992()
    strength = expected_brace_strength(shape, steel, ry=1.1, length_x=280.0, length_y=280.0)
    fe = math.pi**2 * steel.E / (280.0 / shape.ry) ** 2
    return [
        Check(
            "Expected tension Ry Fy Ag",
            "kip",
            strength.tension,
            1.1 * 50.0 * shape.A,
            1e-9,
        ),
        Check(
            "Expected compression (1/0.877) Fe Ag",
            "kip",
            strength.compression,
            fe * shape.A,
            2e-3,
        ),
        Check(
            "Post-buckling 0.3 C",
            "kip",
            strength.post_buckling,
            0.3 * fe * shape.A,
            2e-3,
        ),
    ]


def _aisc_brace_connection() -> list[Check]:
    """F2.6c: the required strengths of the W18X50 brace connection and weld."""
    from opensees_studio.core.design.aisc341 import expected_brace_strength
    from opensees_studio.core.design.brace_connections import (
        brace_connection_demands,
        gusset_weld_required_leg,
    )

    shape = _aisc("W18X50")
    steel = _a992()
    expected = expected_brace_strength(shape, steel, ry=1.1, length_x=280.0, length_y=280.0)
    demands = brace_connection_demands(
        ry=1.1,
        fy=50.0,
        ag=shape.A,
        expected_compression=expected.compression,
        plastic_modulus=shape.Zy,
    )
    fe = math.pi**2 * steel.E / (280.0 / shape.ry) ** 2
    return [
        Check(
            "Required tension Ry Fy Ag / alpha_s",
            "kip",
            demands.tension,
            1.1 * 50.0 * shape.A,
            1e-9,
        ),
        Check(
            "Required compression P_expected / alpha_s",
            "kip",
            demands.compression,
            fe * shape.A,
            2e-3,
        ),
        Check(
            "Required flexure 1.1 Ry Fy Z / alpha_s",
            "kip-in",
            demands.flexure,
            1.1 * 1.1 * 50.0 * shape.Zy,
            2e-3,
        ),
        Check(
            "Required weld leg, tp = 0.5 in, E70, both sides",
            "in",
            gusset_weld_required_leg(ry=1.1, fy=50.0, thickness=0.5, fexx=70.0),
            0.3704,
            2e-3,
        ),
    ]


def _aisc_scbf_joint() -> list[Check]:
    """F2.6b: the required moment of the W18X50/W14X99 beam-to-column joint."""
    from opensees_studio.core.design.scbf_joints import scbf_beam_column_moment

    beam = _aisc("W18X50")
    column = _aisc("W14X99")
    moment = scbf_beam_column_moment(
        ry=1.1,
        beam_fy=50.0,
        beam_z=beam.Zx,
        columns=[(50.0, column.Zx)],
    )
    return [
        Check(
            "Beam expected moment 1.1 Ry Fy Zb / alpha_s",
            "kip-in",
            moment.beam_moment,
            1.1 * 1.1 * 50.0 * beam.Zx,
            1e-9,
        ),
        Check(
            "Column expected moment 1.1 Ry Fy Zc / alpha_s",
            "kip-in",
            moment.column_moment,
            1.1 * 1.1 * 50.0 * column.Zx,
            1e-9,
        ),
        Check(
            "Required moment min(beam, column)",
            "kip-in",
            moment.required,
            min(
                1.1 * 1.1 * 50.0 * beam.Zx,
                1.1 * 1.1 * 50.0 * column.Zx,
            ),
            1e-9,
        ),
    ]


def _aisc_column_splice() -> list[Check]:
    """F2.6d: required moment and shear of a W14X99 column splice."""
    from opensees_studio.core.design.scbf_joints import column_splice_demand

    shape = _aisc("W14X99")
    splice = column_splice_demand(
        top_fy=50.0,
        top_z=shape.Zx,
        bottom_fy=50.0,
        bottom_z=shape.Zx,
        clear_height=144.0,
    )
    return [
        Check(
            "Required splice moment 0.5 Mp / alpha_s",
            "kip-in",
            splice.moment,
            0.5 * 50.0 * shape.Zx,
            1e-9,
        ),
        Check(
            "Required splice shear (Mp_top + Mp_bottom) / (alpha_s Hc)",
            "kip",
            splice.shear,
            2.0 * 50.0 * shape.Zx / 144.0,
            1e-9,
        ),
    ]


def _aisc_ocbf_brace() -> list[Check]:
    """F1.5b: the OCBF V-brace slenderness limit and one brace ratio."""
    from opensees_studio.core.design.aisc341 import ocbf_brace_slenderness_limit

    shape = _aisc("W18X50")
    limit = ocbf_brace_slenderness_limit(29000.0, 50.0)
    slenderness = 280.0 / min(shape.rx, shape.ry)
    return [
        Check(
            "OCBF slenderness limit 4 sqrt(E/Fy)",
            "-",
            limit,
            4.0 * math.sqrt(29000.0 / 50.0),
            1e-9,
        ),
        Check(
            "Brace Lc/r",
            "-",
            slenderness,
            280.0 / min(shape.rx, shape.ry),
            1e-9,
        ),
        Check(
            "Brace Lc/r over the limit",
            "-",
            slenderness / limit,
            (280.0 / min(shape.rx, shape.ry)) / limit,
            1e-9,
        ),
    ]


def _aisc_chapter_j() -> list[Check]:
    """AISC 360 Chapter J: fillet weld, bolt shear, bearing and block shear."""
    from opensees_studio.core.design.chapter_j import (
        block_shear_strength,
        bolt_bearing_strength,
        bolt_shear_strength,
        fillet_weld_strength,
    )

    weld = fillet_weld_strength(fexx=70.0, leg=0.25, length=10.0, both_sides=False)
    bolts = bolt_shear_strength(fnv=54.0, diameter=0.75, count=4)
    bearing = bolt_bearing_strength(
        fu=65.0,
        thickness=0.5,
        diameter=0.75,
        count=4,
        edge_distance=1.5,
        hole_diameter=0.8125,
    )
    block = block_shear_strength(
        fy=50.0,
        fu=65.0,
        agv=6.0,
        anv=4.375,
        ant=1.0,
    )
    return [
        Check("Fillet weld nominal J2-4", "kip", weld.nominal, 74.247, 2e-3),
        Check("Bolt shear nominal J3-1", "kip", bolts.nominal, 95.426, 2e-3),
        Check("Bolt bearing/tearout nominal J3-6", "kip", bearing.nominal, 170.625, 2e-3),
        Check("Block shear nominal J4-5", "kip", block.nominal, 235.625, 2e-3),
    ]


def _aisc_chapter_j_concentrated() -> list[Check]:
    """AISC 360 J10.1-J10.5: concentrated forces on flanges and webs."""
    from opensees_studio.core.design.chapter_j import (
        flange_local_bending,
        web_compression_buckling,
        web_local_crippling,
        web_local_yielding,
        web_sidesway_buckling,
    )

    flange = flange_local_bending(fyf=50.0, tf=0.5, bf=6.0, lb=2.0, distance_to_end=20.0)
    yielding_far = web_local_yielding(fyw=50.0, tw=0.3, k=1.0, lb=2.0, d=14.0, distance_to_end=20.0)
    yielding_near = web_local_yielding(
        fyw=50.0, tw=0.3, k=1.0, lb=2.0, d=14.0, distance_to_end=10.0
    )
    crippling_far = web_local_crippling(
        fyw=50.0, e=29000.0, tw=0.3, tf=0.5, d=14.0, lb=2.0, distance_to_end=10.0
    )
    crippling_near = web_local_crippling(
        fyw=50.0, e=29000.0, tw=0.3, tf=0.5, d=14.0, lb=4.0, distance_to_end=5.0
    )
    sidesway_restrained = web_sidesway_buckling(
        fy=50.0, sx=100.0, mr=1000.0, tw=1.0, tf=0.5, h=10.0, bf=8.0, lb=100.0
    )
    sidesway_unrestrained = web_sidesway_buckling(
        fy=50.0,
        sx=100.0,
        mr=1000.0,
        tw=1.0,
        tf=0.5,
        h=10.0,
        bf=8.0,
        lb=100.0,
        restrained=False,
    )
    compression = web_compression_buckling(
        e=29000.0, fyw=50.0, tw=0.5, h=12.0, distance_to_end=10.0, d=14.0
    )
    return [
        Check("Flange local bending nominal J10-1", "kip", flange.nominal, 78.125, 2e-3),
        Check(
            "Web local yielding nominal J10-2",
            "kip",
            yielding_far.nominal,
            105.0,
            2e-3,
        ),
        Check(
            "Web local yielding nominal J10-3",
            "kip",
            yielding_near.nominal,
            67.5,
            2e-3,
        ),
        Check(
            "Web local crippling nominal J10-4",
            "kip",
            crippling_far.nominal,
            134.223,
            2e-3,
        ),
        Check(
            "Web local crippling nominal J10-5b",
            "kip",
            crippling_near.nominal,
            80.488,
            2e-3,
        ),
        Check(
            "Web sidesway nominal J10-6",
            "kip",
            sidesway_restrained.nominal,
            5783.04,
            2e-3,
        ),
        Check(
            "Web sidesway nominal J10-7",
            "kip",
            sidesway_unrestrained.nominal,
            983.04,
            2e-3,
        ),
        Check(
            "Web compression nominal J10-8",
            "kip",
            compression.nominal,
            301.04,
            2e-3,
        ),
    ]


def _aisc_chapter_j_fillers() -> list[Check]:
    """AISC 360 J5-J8: fillers, splices, bearing and concrete bearing."""
    from opensees_studio.core.design.chapter_j import (
        bearing_strength,
        concrete_bearing_strength,
        filler_bolt_factor,
        filler_weld_required_leg,
        splice_strength,
    )

    factor = filler_bolt_factor(0.5)
    leg = filler_weld_required_leg(0.25, 0.125)
    splice = splice_strength(nominal=1000.0)
    bearing = bearing_strength(fy=50.0, apb=2.0)
    concrete = concrete_bearing_strength(fc=4.0, a1=100.0, a2=400.0)
    return [
        Check("Filler bolt factor J5.2", "-", factor, 0.9, 1e-9),
        Check("Filler weld leg J5.1a", "in", leg, 0.375, 1e-9),
        Check("Groove-welded splice nominal J6", "kip", splice.nominal, 1000.0, 1e-9),
        Check("Bearing nominal J7-1", "kip", bearing.nominal, 180.0, 1e-9),
        Check("Concrete bearing nominal J8-2", "kip", concrete.nominal, 680.0, 1e-9),
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
    Case(
        "D-06",
        "Calculation memory of the D-05 beam",
        "Design, AISC 360-16",
        "Every limit state and calculation step of the member check appears in the memory.",
        "The D-05 beam, rendered as the English HTML calculation memory.",
        _aisc_memory_check,
    ),
    Case(
        "D-07",
        "AISC 341: expected SCBF brace strength",
        "Design, AISC 341-22",
        "F2.3: RyFyAg in tension and (1/0.877)FneAg in compression, with Fne from "
        "AISC 360 E3 using RyFy.",
        "W18X50 brace, Ry = 1.1, Fy = 50 ksi, Lc = 280 in about both axes.",
        _aisc_expected_brace,
    ),
    Case(
        "D-08",
        "AISC 341: SCBF brace connection demands",
        "Design, AISC 341-22",
        "F2.6c: RyFyAg/alpha_s, P_expected/alpha_s, 1.1RyFyZ/alpha_s and the "
        "F2.6c.4 weld leg for 0.6RyFytp/alpha_s with E70 fillets.",
        "W18X50 brace, Ry = 1.1, Fy = 50 ksi, Lc = 280 in; gusset tp = 0.5 in, "
        "double-sided E70 fillet welds.",
        _aisc_brace_connection,
    ),
    Case(
        "D-09",
        "AISC 341: SCBF beam-to-column connection moment",
        "Design, AISC 341-22",
        "F2.6b: min(1.1RyFybZb/alpha_s, 1.1RyΣFycZc/alpha_s).",
        "W18X50 beam and W14X99 column, Ry = 1.1, Fy = 50 ksi.",
        _aisc_scbf_joint,
    ),
    Case(
        "D-10",
        "AISC 341: SCBF column splice demand",
        "Design, AISC 341-22",
        "F2.6d: 0.5 min(Mp_top, Mp_bottom)/alpha_s and (Mp_top + Mp_bottom)/(alpha_s Hc).",
        "W14X99 column, Fy = 50 ksi, clear height Hc = 144 in.",
        _aisc_column_splice,
    ),
    Case(
        "D-11",
        "AISC 341: OCBF brace slenderness",
        "Design, AISC 341-22",
        "F1.5b: Lc/r <= 4 sqrt(E/Fy) for V and inverted-V braces.",
        "W18X50 brace, Fy = 50 ksi, Lc = 280 in about the minor axis.",
        _aisc_ocbf_brace,
    ),
    Case(
        "D-12",
        "AISC 360 Chapter J: weld, bolts and block shear",
        "Design, AISC 360-16",
        "J2-4, J3-1, J3-6 and J4-5 with the AISC 360 factors.",
        "Fillet weld E70, 1/4 in. leg, 10 in.; four 3/4 in. A325 bolts; "
        "1/2 in. plate, 1.5 in. edge distance; block shear with Agv = 6, "
        "Anv = 4.375 and Ant = 1 in.2.",
        _aisc_chapter_j,
    ),
    Case(
        "D-13",
        "AISC 360 Chapter J: concentrated forces",
        "Design, AISC 360-16",
        "J10-1 to J10-8 with the AISC 360 factors and the 50% end reductions.",
        "W-shape web with Fy = 50 ksi, tf = 1/2 in., tw = 0.3 in., "
        "bf = 6 in., h = 12 in., d = 14 in., lb = 2 in.; sidesway with "
        "tw = 1 in., h = 10 in., bf = 8 in., Lb = 100 in.",
        _aisc_chapter_j_concentrated,
    ),
    Case(
        "D-14",
        "AISC 360 Chapter J: fillers, splices and bearing",
        "Design, AISC 360-16",
        "J5.1/J5.2, J6, J7-1 and J8-2 with the AISC 360 factors; J9 uses the J3 bolt checks.",
        "1/2 in. filler; 1/4 in. weld leg with a 1/8 in. filler; 1000 kip "
        "splice; 50 ksi bearing on 2 in.2; f'c = 4 ksi, A1 = 100 in.2 and "
        "A2 = 400 in.2.",
        _aisc_chapter_j_fillers,
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
