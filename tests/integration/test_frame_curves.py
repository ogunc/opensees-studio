"""The bent shape of solved members, as the deformed shape draws them."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    UniformElementLoad,
)
from opensees_studio.core.geometry.frame_options import EndRelease, FrameReleases
from opensees_studio.services.deformation import static_to_deformation
from opensees_studio.services.frame_curves import static_frame_curves
from opensees_studio.services.opensees_runner import OpenSeesRunner

E = 2.0e8
A = 0.02
I_SEC = 2.0e-4
L = 6.0
W = 10.0
PIN = (True, False, True, False, False, False)
ROLLER = (False, False, True, False, False, False)


def _beam(*, elements: list[ElasticBeamColumn], nodes: list[Node], loads: dict) -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=nodes,
        sections=[ElasticSection(id=1, E=E, A=A, Iz=I_SEC)],
        elements=elements,
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[PlainLoadPattern(id=1, time_series_id=1, **loads)],
        analyses=[StaticCase(id=1, name="static", n_steps=1, pattern_ids=[1])],
    )


def test_a_uniformly_loaded_beam_draws_its_quartic_sag(tmp_path: Path) -> None:
    """The joints of a simply supported beam do not move: only the curve shows the load."""
    project = _beam(
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=PIN),
            Node(id=2, coords=(L, 0, 0), restraint=ROLLER),
        ],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        loads={"element_loads": [UniformElementLoad(element_id=1, wy=-W)]},
    )
    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)

    curves = static_frame_curves(project, results)

    assert curves.element_ids.tolist() == [1]
    mid = len(curves.stations) // 2
    assert curves.stations[mid] == pytest.approx(0.5)
    expected = 5.0 * W * L**4 / (384.0 * E * I_SEC)
    # Downward (global -Z) at midspan, zero at the pinned ends.
    assert curves.offsets[0, mid, 2] == pytest.approx(-expected, rel=2e-3)
    assert np.allclose(curves.offsets[0, [0, -1], 2], 0.0, atol=1e-12)

    # The deformed shape carries the curve; the joints alone would be straight.
    source = static_to_deformation(project, results)
    assert source.frame_curves is not None
    assert source.frame_curves.offsets[0, mid, 2] == pytest.approx(-expected, rel=2e-3)
    # Without span loads (a combination's bound) the cubic of the end rotations
    # still bends: wL^4/(120 EI) at midspan for the end slopes of this beam.
    hermite = static_frame_curves(project, results, span_loads=False)
    rotation = W * L**3 / (24.0 * E * I_SEC)
    assert hermite.offsets[0, mid, 2] == pytest.approx(-rotation * L / 4.0, rel=2e-3)


def test_a_cantilever_tip_load_draws_the_cubic_of_its_end_rotation(tmp_path: Path) -> None:
    tip = 10.0
    project = _beam(
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(L, 0, 0)),
        ],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        loads={"nodal_loads": [NodalLoad(node_id=2, forces=(0.0, 0.0, -tip, 0.0, 0.0, 0.0))]},
    )
    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)

    curves = static_frame_curves(project, results)

    mid = len(curves.stations) // 2
    assert curves.offsets[0, -1, 2] == pytest.approx(-tip * L**3 / (3.0 * E * I_SEC), rel=1e-6)
    assert curves.offsets[0, mid, 2] == pytest.approx(
        -5.0 * tip * L**3 / (48.0 * E * I_SEC), rel=1e-6
    )


def test_a_released_end_does_not_take_the_joint_rotation(tmp_path: Path) -> None:
    """A member pinned into a joint that rotates bends as a cantilever with a free tip."""
    pin_at_j = FrameReleases(j=EndRelease(released=("M3",)))
    project = _beam(
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(L, 0.0, 0.0)),
            Node(id=3, coords=(2 * L, 0.0, 0.0), restraint=(True,) * 6),
        ],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1, releases=pin_at_j),
            ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
        ],
        loads={"nodal_loads": [NodalLoad(node_id=2, forces=(0.0, 0.0, -W, 0.0, 0.0, 0.0))]},
    )
    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)
    joint = results.node_disp[2][-1]
    assert abs(joint[2]) > 1e-6  # the joint rotates (member 2 bends)

    curves = static_frame_curves(project, results, span_loads=False)

    # Member 1: fixed at 1, no moment at 2: v = d (3t^2 - t^3) / 2, 5/16 d at midspan.
    mid = len(curves.stations) // 2
    deflection = float(joint[1])
    assert curves.offsets[0, -1, 2] == pytest.approx(deflection, rel=1e-9)
    assert curves.offsets[0, mid, 2] == pytest.approx(5.0 / 16.0 * deflection, rel=1e-9)
    # The integrated moment (span_loads) agrees: member 1 has no span load.
    integrated = static_frame_curves(project, results)
    assert integrated.offsets[0, mid, 2] == pytest.approx(5.0 / 16.0 * deflection, rel=1e-9)
