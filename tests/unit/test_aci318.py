"""ACI 318-19 by hand: the strain-compatibility engine on a rectangle."""

from __future__ import annotations

import math

import numpy as np
import pytest

from opensees_studio.core.design.aci318 import (
    RcSection,
    ShearReinforcement,
    check_station,
    design_moment_capacity,
    interaction_curve,
)

B, H, FC, FY = 0.3, 0.5, 28e6, 420e6
BAR = math.pi * 0.02**2 / 4


def _section(bars: list[tuple[float, float]]) -> RcSection:
    ny, nz = 100, 30
    ys = (np.arange(ny) + 0.5) / ny * H - H / 2
    zs = (np.arange(nz) + 0.5) / nz * B - B / 2
    y, z = np.meshgrid(ys, zs, indexing="ij")
    concrete = np.column_stack([y.ravel(), z.ravel(), np.full(y.size, B * H / (ny * nz))])
    return RcSection(
        concrete=concrete,
        bars=np.array([[by, bz, BAR] for by, bz in bars]),
        fc=FC,
        fy=FY,
        es=200e9,
    )


def test_beta1_follows_the_strength() -> None:
    assert _section([(0.0, 0.0)]).beta1 == pytest.approx(0.85)
    strong = RcSection(np.zeros((1, 3)) + 1, np.zeros((1, 3)), fc=56e6, fy=FY, es=200e9)
    assert strong.beta1 == pytest.approx(0.65)


def test_phi_goes_from_compression_to_tension_controlled() -> None:
    section = _section([(0.0, 0.0)])
    eps_ty = FY / 200e9
    assert section.phi(eps_ty) == pytest.approx(0.65)
    assert section.phi(eps_ty + 0.0015) == pytest.approx(0.775)
    assert section.phi(0.01) == 0.9


def test_beam_flexure_by_hand() -> None:
    section = _section([(-H / 2 + 0.06, z) for z in (-0.1, 0.0, 0.1)])
    capacity, phi = design_moment_capacity(interaction_curve(section, "y"), 0.0, section, 1.0)
    a = 3 * BAR * FY / (0.85 * FC * B)
    assert phi == 0.9
    assert capacity == pytest.approx(0.9 * 3 * BAR * FY * (H - 0.06 - a / 2), rel=2e-3)


def test_column_squash_load_and_maximum() -> None:
    section = _section([(y, z) for y in (-0.19, 0.19) for z in (-0.09, 0.09)])
    p0 = 0.85 * FC * (B * H - 4 * BAR) + FY * 4 * BAR
    assert section.p0 == pytest.approx(p0)
    assert section.pn_max == pytest.approx(0.80 * 0.65 * p0)
    outcome = check_station(
        section,
        {"y": interaction_curve(section, "y"), "z": interaction_curve(section, "z")},
        pu=0.5 * section.pn_max,
        m3=0.0,
        m2=0.0,
        v2=0.0,
        v3=0.0,
        t=0.0,
        shear=None,
    )
    assert outcome.governing is not None and outcome.governing.ratio == pytest.approx(0.5)


def test_shear_by_hand() -> None:
    section = _section([(-H / 2 + 0.06, 0.0)])
    stirrups = ShearReinforcement(av=157e-6, spacing=0.15, fyt=420e6)
    d = H - 0.06
    vc = 0.17 * math.sqrt(28.0) * 1e6 * B * d
    vs = 157e-6 * 420e6 * d / 0.15
    outcome = check_station(
        section,
        {"y": interaction_curve(section, "y"), "z": interaction_curve(section, "z")},
        pu=0.0,
        m3=0.0,
        m2=0.0,
        v2=100e3,
        v3=0.0,
        t=0.0,
        shear=stirrups,
    )
    shear = next(c for c in outcome.checks if c.name == "Shear V2")
    # d is measured from the outermost concrete fibre centre: 0.25 % of h short.
    assert shear.ratio == pytest.approx(100e3 / (0.75 * (vc + vs)), rel=5e-3)
