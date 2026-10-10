"""The W-shape fiber template gives the section response of OpenSees WFSection2d.

Both sections share one Steel02 material and are driven to the same axial strain and
curvature through a zeroLengthSection (Lagrange constraints keep the imposed
deformation exact). The template goes through the runner's own emission; WFSection2d is
built with the command the ThreeStorySteel example uses.
"""

from __future__ import annotations

import numpy as np
import openseespy.opensees as ops
import pytest

from opensees_studio.core import (
    FiberSection,
    Node,
    Project,
    Steel02,
    ZeroLengthSectionElement,
    w_shape_patches,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

# ThreeStorySteel: section('WFSection2d', tag, matTag, d, tw, bf, tf, Nfw, Nff)
SHAPES = {
    "column": (10.5, 0.26, 5.77, 0.44, 15, 16),
    "outer beam": (8.3, 0.44, 8.11, 0.685, 15, 15),
    "inner beam": (8.2, 0.40, 8.01, 0.650, 15, 15),
    "roof beam": (8.0, 0.40, 7.89, 0.600, 15, 15),
}
# Steel02 of the example: Fy 60, Es 29000, b 0.10, R0 18, cR1 0.925, cR2 0.15.
STEEL = Steel02(id=1, Fy=60.0, E0=29000.0, b=0.10, R0=18.0, cR1=0.925, cR2=0.15)
# (axial strain, curvature): elastic, yielding, reversed signs, deep plastic.
PAIRS = [
    (5e-4, 0.0),
    (0.0, 2e-4),
    (-1e-3, 8e-4),
    (3e-3, -1e-3),
    (0.0, 3e-3),
    (-4e-3, -2e-3),
]


def _impose(eps: float, kappa: float) -> tuple[np.ndarray, np.ndarray]:
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    ops.sp(2, 1, eps)
    ops.sp(2, 3, kappa)
    ops.constraints("Lagrange")
    ops.numberer("Plain")
    ops.system("UmfPack")
    ops.test("NormDispIncr", 1e-12, 50)
    ops.algorithm("Newton")
    ops.integrator("LoadControl", 1.0)
    ops.analysis("Static")
    assert ops.analyze(1) == 0
    assert ops.eleResponse(1, "section", "deformation") == pytest.approx([eps, kappa], abs=1e-15)
    force = np.array(ops.eleResponse(1, "section", "force"))
    tangent = np.array(ops.eleResponse(1, "section", "stiffness"))
    return force, tangent


def _template(shape: tuple, eps: float, kappa: float) -> tuple[np.ndarray, np.ndarray]:  # type: ignore[type-arg]
    d, tw, bf, tf, nfw, nff = shape
    section = FiberSection(
        id=1,
        patches=w_shape_patches(1, d=d, bf=bf, tf=tf, tw=tw, n_web=nfw, n_flange=nff),
    )
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True, True, False, False, False, True)),
            Node(id=2, coords=(0, 0, 0), restraint=(False, True, False, False, False, False)),
        ],
        materials=[STEEL],
        sections=[section],
        elements=[ZeroLengthSectionElement(id=1, nodes=(1, 2), section_id=1)],
    )
    OpenSeesRunner(project).build()
    return _impose(eps, kappa)


def _wf_section_2d(shape: tuple, eps: float, kappa: float) -> tuple[np.ndarray, np.ndarray]:  # type: ignore[type-arg]
    d, tw, bf, tf, nfw, nff = shape
    ops.wipe()
    ops.model("basic", "-ndm", 2, "-ndf", 3)
    ops.node(1, 0.0, 0.0)
    ops.node(2, 0.0, 0.0)
    ops.fix(1, 1, 1, 1)
    ops.fix(2, 0, 1, 0)
    ops.uniaxialMaterial("Steel02", 1, 60.0, 29000.0, 0.10, 18.0, 0.925, 0.15)
    ops.section("WFSection2d", 1, 1, d, tw, bf, tf, nfw, nff)
    ops.element("zeroLengthSection", 1, 1, 2, 1)
    return _impose(eps, kappa)


def _rel(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.max(np.abs(a - b)) / np.max(np.abs(b)))


@pytest.mark.parametrize("name", list(SHAPES))
def test_template_matches_wf_section_2d_force_and_tangent(name: str) -> None:
    shape = SHAPES[name]
    worst = 0.0
    for eps, kappa in PAIRS:
        force, tangent = _template(shape, eps, kappa)
        ref_force, ref_tangent = _wf_section_2d(shape, eps, kappa)
        worst = max(worst, _rel(force, ref_force), _rel(tangent, ref_tangent))
    ops.wipe()
    print(f"{name}: max relative difference {worst:.3e}")
    assert worst < 1e-9


def test_template_patches_have_the_wf_fibre_count_and_area() -> None:
    d, tw, bf, tf, nfw, nff = SHAPES["column"]
    patches = w_shape_patches(1, d=d, bf=bf, tf=tf, tw=tw, n_web=nfw, n_flange=nff)
    assert sum(p.n_fib_y * p.n_fib_z for p in patches) == nfw + 2 * nff
    area = sum((p.y_j - p.y_i) * (p.z_j - p.z_i) for p in patches)
    assert area == pytest.approx(2 * bf * tf + (d - 2 * tf) * tw, rel=1e-14)
