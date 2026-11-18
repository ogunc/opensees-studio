"""Design → Concrete Frame Check on solved models, against hand calculations.

A simply supported beam, 300 x 500 mm, three 20 mm bars at d = 440 mm, f'c = 28
MPa, fy = 420 MPa, span 6 m under a factored uniform load: the governing check is
flexure at midspan with ``Mu = w L² / 8`` against ``φMn = 0.9 As fy (d - a/2)``;
the shear at the supports is ``w L / 2`` against ``0.75 (Vc + Vs)``.
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("openseespy")

from tools.verification_manual import ACI_AS as AS
from tools.verification_manual import ACI_B as B
from tools.verification_manual import ACI_COVER as COVER
from tools.verification_manual import ACI_FC as FC
from tools.verification_manual import ACI_FY as FY
from tools.verification_manual import ACI_H as H
from tools.verification_manual import ACI_SPAN as SPAN
from tools.verification_manual import ACI_W as W
from tools.verification_manual import aci_beam_project as _beam

from opensees_studio.core import (
    UniformElementLoad,
)
from opensees_studio.core.design.settings import DesignSettings
from opensees_studio.services.concrete_design import concrete_frame_check
from opensees_studio.services.opensees_runner import OpenSeesRunner


def test_flexure_governs_at_midspan_with_the_hand_ratio() -> None:
    project = _beam()
    results = {1: OpenSeesRunner(project).run(project.analyses[0])}
    report = concrete_frame_check(project, results, DesignSettings())
    members = {m.element_id: m for m in report.members}
    assert set(members) == {1, 2}
    d = H - COVER
    a = AS * FY / (0.85 * FC * B)
    phi_mn = 0.9 * AS * FY * (d - a / 2)
    mu = abs(W) * SPAN**2 / 8
    flexure = members[1].ratios["Flexure M3 with axial force"]
    assert flexure == pytest.approx(mu / phi_mn, rel=0.01)
    # Shear at the support with the default stirrups (157 mm² at 150 mm, 420 MPa).
    bw = B * H / H
    vc = 0.17 * math.sqrt(28.0) * 1e6 * bw * d
    vs = 157e-6 * 420e6 * d / 0.150
    vu = abs(W) * SPAN / 2
    assert members[1].ratios["Shear V2"] == pytest.approx(vu / (0.75 * (vc + vs)), rel=0.02)


def test_hogging_uses_the_top_steel() -> None:
    """The beam has no top bars: a hogging moment finds almost no capacity."""
    project = _beam()
    project.load_patterns[0].element_loads = [
        UniformElementLoad(element_id=k, wy=-W) for k in (1, 2)
    ]  # uplift: hogging
    results = {1: OpenSeesRunner(project).run(project.analyses[0])}
    report = concrete_frame_check(project, results, DesignSettings())
    assert max(m.ratio for m in report.members) > 3.0
