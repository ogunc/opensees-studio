"""Tendons applied as equivalent loads against closed forms.

A simply supported beam (span L, EI) with a tendon of force P:

* straight at eccentricity e: a uniform moment ``-P e``, midspan camber
  ``P e L² / 8 EI`` upward for a tendon below the centroid (e < 0), and the axial
  shortening ``P L / EA``;
* parabolic from the centroid at the ends to ``-d`` at midspan: the balancing
  load ``8 P d / L²`` upward, midspan camber ``5 w L⁴ / 384 EI``, and no end
  moment;
* both with no reactions: the tendon's push is self-equilibrated.
"""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    TendonLoad,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

SPAN, E, A, INERTIA, P = 12.0, 30e9, 0.3, 0.009, 1.5e6
PIN = (True, False, True, False, False, False)
ROLLER = (False, False, True, False, False, False)


def _beam(tendon: TendonLoad, pieces: int = 4) -> Project:
    nodes = [
        Node(
            id=k + 1,
            coords=(SPAN * k / pieces, 0.0, 0.0),
            restraint=PIN if k == 0 else ROLLER if k == pieces else (False,) * 6,
        )
        for k in range(pieces + 1)
    ]
    return Project(
        ndm=2,
        ndf=3,
        nodes=nodes,
        sections=[ElasticSection(id=1, E=E, A=A, Iz=INERTIA, Iy=INERTIA, G=E / 2.4, J=INERTIA)],
        elements=[
            ElasticBeamColumn(id=k + 1, nodes=(k + 1, k + 2), section_id=1) for k in range(pieces)
        ],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[PlainLoadPattern(id=1, time_series_id=1, tendon_loads=[tendon])],
        analyses=[StaticCase(id=1, name="PT", pattern_ids=[1])],
    )


def _one_member(tendon: TendonLoad) -> Project:
    return _beam(tendon, pieces=1)


def test_a_straight_eccentric_tendon_bends_the_beam_uniformly() -> None:
    e = -0.25
    project = _beam(TendonLoad(element_id=1, force=P, e_i=e, e_mid=e, e_j=e))
    # one tendon per piece, each straight at e
    project.load_patterns[0].tendon_loads = [
        TendonLoad(element_id=k, force=P, e_i=e, e_mid=e, e_j=e) for k in range(1, 5)
    ]
    r = OpenSeesRunner(project).run(project.analyses[0])
    camber = r.node_disp[3][-1][1]
    assert camber == pytest.approx(-P * e * SPAN**2 / (8 * E * INERTIA), rel=1e-9)
    assert r.node_disp[5][-1][0] == pytest.approx(-P * SPAN / (E * A), rel=1e-9)
    assert sum(r.node_reaction[n][-1][1] for n in (1, 5)) == pytest.approx(0.0, abs=1e-6)


def test_a_parabolic_tendon_balances_a_uniform_load() -> None:
    d = 0.4
    project = _one_member(TendonLoad(element_id=1, force=P, e_mid=-d))
    # Midspan deflection needs a node there: split the member into two with the
    # matching halves of the parabola.
    half = _beam(TendonLoad(element_id=1, force=P), pieces=2)
    half.load_patterns[0].tendon_loads = [
        TendonLoad(element_id=1, force=P, e_i=0.0, e_mid=-0.75 * d, e_j=-d),
        TendonLoad(element_id=2, force=P, e_i=-d, e_mid=-0.75 * d, e_j=0.0),
    ]
    r = OpenSeesRunner(half).run(half.analyses[0])
    w = 8 * P * d / SPAN**2
    assert r.node_disp[2][-1][1] == pytest.approx(5 * w * SPAN**4 / (384 * E * INERTIA), rel=1e-6)
    whole = OpenSeesRunner(project).run(project.analyses[0])
    end_moment = whole.element_forces[1][-1][2]
    assert end_moment == pytest.approx(0.0, abs=1e-6 * P)


def test_friction_and_long_term_loss_reduce_the_balancing_load() -> None:
    lossless = OpenSeesRunner(_one_member(TendonLoad(element_id=1, force=P, e_mid=-0.4))).run(
        StaticCase(id=1, name="PT", pattern_ids=[1])
    )
    lossy_project = _one_member(
        TendonLoad(
            element_id=1, force=P, e_mid=-0.4, friction=0.2, wobble=0.002, long_term_loss=0.15
        )
    )
    lossy = OpenSeesRunner(lossy_project).run(lossy_project.analyses[0])
    assert abs(lossy.node_disp[2][-1][0]) < 0.85 * abs(lossless.node_disp[2][-1][0])
