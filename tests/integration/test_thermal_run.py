"""Temperature loads solved by OpenSees, against the elastic closed forms.

* a free bar grows α ΔT L and carries nothing;
* a cantilever under a gradient bends to α g L² / 2 at the tip, toward the cool
  face, and carries nothing;
* a member held at both ends does not move and carries EA α ΔT in compression
  and a constant moment EI α g;
* a ramp in N steps applies the load in N parts;
* other case types refuse a pattern with temperature loads.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    Project,
    PushoverCase,
    StaticCase,
    TemperatureLoad,
)
from opensees_studio.services.element_forces import ForceComponent, extract_diagram_data
from opensees_studio.services.opensees_runner import OpenSeesRunner

E, A, I, L, ALPHA = 200e9, 0.01, 1e-4, 4.0, 1.2e-5  # noqa: E741
DT, G = 30.0, 100.0  # °, °/m


def _project(ndm: int, *, held: bool, load: dict[str, float], n_steps: int = 1) -> Project:
    fixed = (True,) * 6
    xs = [0.0, L / 2, L]
    nodes = [
        Node(
            id=k + 1,
            coords=(x, 0.0, 0.0),
            restraint=fixed if k == 0 or (held and k == 2) else (False,) * 6,
        )
        for k, x in enumerate(xs)
    ]
    section = ElasticSection(
        id=1, E=E, A=A, Iz=I, **({"Iy": 2 * I, "G": 77e9, "J": 1e-4} if ndm == 3 else {})
    )
    elements = [ElasticBeamColumn(id=k, nodes=(k, k + 1), section_id=1) for k in (1, 2)]
    return Project(
        ndm=ndm,
        ndf=3 if ndm == 2 else 6,
        nodes=nodes,
        sections=[section],
        elements=elements,
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="Heat",
                time_series_id=1,
                temperature_loads=[
                    TemperatureLoad(element_id=k, alpha=ALPHA, **load) for k in (1, 2)
                ],
            )
        ],
        analyses=[
            StaticCase(
                id=1,
                name="T",
                pattern_ids=[1],
                n_steps=n_steps,
                load_factor_increment=1.0 / n_steps,
            )
        ],
    )


def _run(project: Project):  # type: ignore[no-untyped-def]
    return OpenSeesRunner(project).run(project.analyses[0])


@pytest.mark.parametrize("ndm", [2, 3])
def test_a_free_bar_grows_and_carries_nothing(ndm: int) -> None:
    results = _run(_project(ndm, held=False, load={"uniform": DT}))
    assert results.node_disp[3][-1][0] == pytest.approx(ALPHA * DT * L)
    assert np.abs(results.element_forces[1][-1]).max() < 1e-6


def test_a_2d_cantilever_bends_toward_the_cool_face() -> None:
    results = _run(_project(2, held=False, load={"gradient_y": G}))
    # In 2D local y is up (+Z) for a member along X: the hot top face bends it down.
    assert results.node_disp[3][-1][1] == pytest.approx(-ALPHA * G * L**2 / 2)
    assert np.abs(results.element_forces[2][-1]).max() < 1e-6


@pytest.mark.parametrize(("gradient", "axis"), [("gradient_y", 1), ("gradient_z", 2)])
def test_a_3d_cantilever_bends_toward_the_cool_face(gradient: str, axis: int) -> None:
    # In 3D a member along X has local y = +Y and local z = +Z (up), see
    # core.geometry.local_axes: each gradient bends it toward its cool face.
    results = _run(_project(3, held=False, load={gradient: G}))
    assert results.node_disp[3][-1][axis] == pytest.approx(-ALPHA * G * L**2 / 2)
    assert np.abs(results.element_forces[1][-1]).max() < 1e-6


@pytest.mark.parametrize("ndm", [2, 3])
def test_a_held_member_is_compressed_and_bent(ndm: int) -> None:
    project = _project(ndm, held=True, load={"uniform": DT, "gradient_y": G}, n_steps=2)
    results = _run(project)
    assert np.abs(results.node_disp[2][-1]).max() < 1e-12
    axial = extract_diagram_data(project, results, ForceComponent.N)
    np.testing.assert_allclose(axial.values_i, E * A * ALPHA * DT)  # diagrams: compression +
    # The y gradient bends about local z (Iz) in 2D and in 3D.
    moment = extract_diagram_data(project, results, ForceComponent.M3)
    np.testing.assert_allclose(np.abs(moment.values_i), E * I * ALPHA * G)
    np.testing.assert_allclose(moment.values_i, moment.values_j)  # constant along the member
    # The first of two steps carries half the load.
    assert results.element_forces[1][0][0] == pytest.approx(E * A * ALPHA * DT / 2)


def test_other_case_types_refuse_temperature_loads() -> None:
    project = _project(2, held=False, load={"uniform": DT})
    push = PushoverCase(
        id=2,
        name="Push",
        pattern_ids=[1],
        control_node=3,
        control_dof=1,
        target_disp=0.01,
        step_size=0.001,
    )
    project.analyses.append(push)
    with pytest.raises(ValueError, match="run in static cases only"):
        OpenSeesRunner(project).run(push)
