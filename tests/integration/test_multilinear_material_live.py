"""MultiLinear uniaxial material in real OpenSeesPy runs (M1 to M4).

M1 a monotonic push through every point in both senses; M2 a reversal on a three-point
curve against hand values; M3 a static push of a zeroLength and a twoNodeLink; M4 a
transient run of both elements, whose force history equals the material driven
directly by the element's deformation history. Each test prints its measured numbers
(``pytest -s`` shows them).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

ops = pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (  # noqa: E402
    LinearTimeSeries,
    MultiLinear,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    TransientCase,
    TrigTimeSeries,
    TwoNodeLinkElement,
    ZeroLengthElement,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402

FIXED = (True,) * 6
ONLY_Z = (True, True, False, True, True, True)
HAND = [(0.001, 1.0), (0.002, 1.5), (0.004, 2.0)]
# The Tip-1 wire-rope roll curve (deformation m, force kN).
ROLL = [
    (0.00202, 0.6),
    (0.02, 2.01),
    (0.0285, 2.85),
    (0.0398, 4.23),
    (0.0482, 5.5),
    (0.0596, 7.68),
    (0.0783, 12.85),
]


def _drive(points: list[tuple[float, float]], strains: list[float]) -> list[float]:
    """Build the material through the runner, then drive it with ``testUniaxialMaterial``."""
    OpenSeesRunner(Project(ndm=2, ndf=2, materials=[MultiLinear(id=7, points=points)])).build()
    ops.testUniaxialMaterial(7)
    out = []
    for e in strains:
        ops.setStrain(e)
        out.append(ops.getStress())
    return out


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ M1: monotonic push â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@pytest.mark.parametrize("sense", [1.0, -1.0], ids=["positive", "negative"])
@pytest.mark.parametrize("points", [HAND, ROLL], ids=["hand", "roll"])
def test_m1_monotonic_push_reproduces_every_point(
    points: list[tuple[float, float]], sense: float
) -> None:
    strains = [sense * e for e, _ in points]
    stresses = _drive(points, strains)
    worst = max(abs(f - sense * s) / s for f, (_, s) in zip(stresses, points, strict=True))
    print(f"M1 {len(points)} points, sense {sense:+.0f}: largest relative miss {worst!r}")
    assert worst <= 1e-12


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ M2: reversal â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def test_m2_reversal_traverses_each_segment_twice_its_length() -> None:
    up = [k * 0.0005 for k in range(13)]
    down = [0.006 - k * 0.0005 for k in range(1, 13)]
    stresses = _drive(HAND, up + down)
    at = dict(zip([round(e, 6) for e in up + down][13:], stresses[13:], strict=True))
    print(f"M2 at 0.006 {stresses[12]!r}; back at 0.004 {at[0.004]!r}, 0.002 {at[0.002]!r}, "
          f"0.0 {at[0.0]!r}")  # fmt: skip
    # Up: the last slope continues past 0.004 (2.0 + 250 x 0.002). Down: 1000 over 0.002,
    # 500 over 0.002, 250 over 0.004.
    assert stresses[12] == pytest.approx(2.5, rel=1e-12)
    assert at[0.004] == pytest.approx(0.5, rel=1e-12)
    assert at[0.002] == pytest.approx(-0.5, rel=1e-12)
    assert at[0.0] == pytest.approx(-1.0, rel=1e-12)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ M3: static, zeroLength and twoNodeLink â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _static(link: bool, fz: float) -> Project:
    top = (0.0, 0.0, 0.153 if link else 0.0)
    element: object = (
        TwoNodeLinkElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=(1,))
        if link
        else ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=(3,))
    )
    return Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=FIXED),
            Node(id=2, coords=top, restraint=ONLY_Z),
        ],
        materials=[MultiLinear(id=1, points=HAND)],
        elements=[element],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(0, 0, fz, 0, 0, 0))],
            )
        ],
        analyses=[
            StaticCase(id=1, pattern_ids=[1], n_steps=4, load_factor_increment=0.25,
                       algorithm="Newton")
        ],
    )  # fmt: skip


@pytest.mark.parametrize("fz", [1.25, -1.75], ids=["tension", "compression"])
def test_m3_static_push_of_both_elements(fz: float) -> None:
    # Hand values: 1.25 lies on segment 2 (u = 0.001 + 0.25 / 500), 1.75 on segment 3
    # (u = 0.002 + 0.25 / 250).
    expected = {1.25: 0.0015, -1.75: -0.003}[fz]
    for link in (False, True):
        project = _static(link, fz)
        res = OpenSeesRunner(project).run(project.analyses[0])
        uz = res.node_disp[2][-1, 2]
        force = res.element_forces[1][-1]
        print(f"M3 {'twoNodeLink' if link else 'zeroLength'} fz {fz}: uz {uz!r}, force {force!r}")
        assert uz == pytest.approx(expected, rel=1e-9)
        assert abs(force).max() == pytest.approx(abs(fz), rel=1e-9)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ M4: transient, zeroLength and twoNodeLink â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _transient(link: bool) -> Project:
    top = (0.0, 0.0, 0.153 if link else 0.0)
    element: object = (
        TwoNodeLinkElement(
            id=1, nodes=(1, 2), material_ids=(1, 2, 3), dofs=(1, 2, 3), orient_y=(1.0, 0.0, 0.0)
        )
        if link
        else ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1, 2, 3), dofs=(3, 1, 2))
    )
    return Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=FIXED),
            Node(id=2, coords=top, restraint=(False,) * 3 + (True,) * 3, mass=(0.2,) * 3 + (0,) * 3),
        ],
        materials=[MultiLinear(id=k, points=ROLL) for k in (1, 2, 3)],
        elements=[element],
        time_series=[TrigTimeSeries(id=1, t_end=1.5, period=0.5, factor=1.0)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(1, 0, 0, 0, 0, 0))],
            )
        ],
        analyses=[TransientCase(id=1, pattern_ids=[1], dt=0.005, n_steps=300)],
    )  # fmt: skip


def test_m4_transient_force_equals_the_material_driven_by_the_deformation(
    tmp_path: Path,
) -> None:
    runs = {}
    for link in (False, True):
        project = _transient(link)
        runs[link] = OpenSeesRunner(project).run(project.analyses[0], tmp_path / str(link))
    zl, tl = runs[False], runs[True]
    assert zl.n_steps == tl.n_steps == 300
    ux_zl, ux_tl = zl.node_disp_history(2)[:, 0], tl.node_disp_history(2)[:, 0]
    peak = float(np.abs(ux_tl).max())
    # The shear direction is the zeroLength's second material (dof 1) and the link's local 2.
    shear_zl, shear_tl = zl.element_force_history(1)[:, 1], tl.element_force_history(1)[:, 1]
    deform = tl.element_deformation_history(1)[:, 1]
    driven = np.array(_drive(ROLL, [0.0, *deform.tolist()])[1:])
    fpeak = float(np.abs(shear_tl).max())
    d_elem = float(np.abs(ux_zl - ux_tl).max())
    d_force = float(np.abs(driven - shear_tl).max())
    d_elem_force = float(np.abs(np.abs(shear_zl) - np.abs(shear_tl)).max())
    print(f"M4 peak ux {peak!r} (beyond the first point {ROLL[0][0]}); |ux zeroLength - link| "
          f"{d_elem!r}; peak shear {fpeak!r}; |driven - link force| {d_force!r}; "
          f"|zeroLength - link force| {d_elem_force!r}")  # fmt: skip
    assert ROLL[1][0] > peak > 2 * ROLL[0][0]
    assert d_elem <= 1e-9 * peak
    assert d_elem_force <= 1e-6 * fpeak
    # The deformation recorder keeps 6 significant digits: the largest slope times half a
    # unit in the last digit of the peak deformation bounds the force difference.
    assert d_force <= ROLL[0][1] / ROLL[0][0] * 0.5e-5 * 10 ** np.floor(np.log10(peak)) * 2
