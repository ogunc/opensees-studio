"""Formula time series as OpenSees evaluates them: a static case steps pseudo-time."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    ElasticUniaxial,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    PulseTimeSeries,
    RectangularTimeSeries,
    StaticCase,
    TriangleTimeSeries,
    TrussElement,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

DT = 0.125


def _factors(series) -> np.ndarray:  # type: ignore[no-untyped-def]
    """The series value at t = DT, 2 DT, ... 32 DT: the bar's displacement times its stiffness."""
    project = Project(
        ndm=2,
        ndf=2,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(1.0, 0.0, 0.0), restraint=(False, False, True, False, False, False)),
        ],
        materials=[ElasticUniaxial(id=1, E=1.0)],
        elements=[TrussElement(id=1, nodes=(1, 2), area=1.0, material_id=1)],
        time_series=[series],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=series.id,
                nodal_loads=[NodalLoad(node_id=2, forces=(1, 0, 0, 0, 0, 0))],
            )
        ],
        analyses=[
            StaticCase(id=1, name="t", pattern_ids=[1], n_steps=32, load_factor_increment=DT)
        ],
    )
    results = OpenSeesRunner(project).run(project.analyses[0])
    return np.asarray(results.node_disp[2])[:, 0]


def test_rectangular_is_the_factor_inside_its_window() -> None:
    values = _factors(RectangularTimeSeries(id=1, factor=3.0, t_start=1.0, t_end=2.0))
    times = DT * np.arange(1, 33)
    inside = (times >= 1.0) & (times <= 2.0)
    assert values[inside] == pytest.approx(3.0)
    assert values[(times < 1.0) | (times > 2.0)] == pytest.approx(0.0)


def test_triangle_peaks_at_a_quarter_period() -> None:
    values = _factors(TriangleTimeSeries(id=1, factor=2.0, t_start=0.0, t_end=4.0, period=2.0))
    assert values[3] == pytest.approx(2.0)  # t = 0.5 = T/4
    assert values[7] == pytest.approx(0.0, abs=1e-12)  # t = 1.0 = T/2
    assert values[11] == pytest.approx(-2.0)  # t = 1.5 = 3T/4


def test_pulse_is_on_for_its_width() -> None:
    values = _factors(
        PulseTimeSeries(id=1, factor=1.0, t_start=0.0, t_end=3.5, period=1.0, width=0.5)
    )
    on = values[:8]  # t = 0.125 .. 1.0
    assert set(np.round(on, 9)) <= {0.0, 1.0} and 1.0 in on and 0.0 in on
    assert values[-1] == pytest.approx(0.0)  # past t_end


def test_a_window_ending_before_it_starts_is_refused() -> None:
    with pytest.raises(ValueError, match="greater than t_start"):
        RectangularTimeSeries(id=1, t_start=2.0, t_end=1.0)
