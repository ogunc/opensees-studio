"""``TrigTimeSeries`` model, generated-series descriptor and runner emission."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from opensees_studio.core import (
    ElasticUniaxial,
    Node,
    PathTimeSeries,
    Project,
    TrigTimeSeries,
    UniformExcitationPattern,
    ZeroLengthElement,
    from_descriptor,
    sine_beat_excitation,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner


def _project(series) -> Project:  # type: ignore[no-untyped-def]
    return Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(
                id=2,
                coords=(0, 0, 0),
                restraint=(False, True, True, True, True, True),
                mass=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            ),
        ],
        materials=[ElasticUniaxial(id=1, E=100.0)],
        elements=[ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=(1,))],
        time_series=[series],
        load_patterns=[UniformExcitationPattern(id=7, direction=1, accel_series_id=series.id)],
    )


def test_trig_defaults_and_frequency() -> None:
    ts = TrigTimeSeries(id=3, t_end=10.0, period=0.5)
    assert ts.type == "Trig"
    assert ts.factor == 1.0 and ts.t_start == 0.0 and ts.shift == 0.0 and ts.zero_shift == 0.0
    assert ts.frequency == pytest.approx(2.0)
    assert ts.generator is None


def test_trig_rejects_bad_window() -> None:
    with pytest.raises(ValueError, match="t_end"):
        TrigTimeSeries(id=1, t_start=5.0, t_end=5.0, period=1.0)
    with pytest.raises(ValueError):
        TrigTimeSeries(id=1, t_end=5.0, period=0.0)


def test_trig_round_trips_through_project_dump() -> None:
    ts = TrigTimeSeries(
        id=1,
        name="Sine 2 Hz",
        factor=3.5,
        t_end=8.0,
        period=0.5,
        shift=0.1,
        generator={"kind": "sine", "amplitude": 3.5, "frequency": 2.0, "duration": 8.0},
    )
    clone = Project.model_validate(_project(ts).model_dump(mode="json"))
    got = clone.time_series[0]
    assert isinstance(got, TrigTimeSeries)
    assert got == ts
    clone.validate_references()


def test_generated_path_series_keeps_descriptor_and_regenerates() -> None:
    series = sine_beat_excitation(0.4, 2.0, 10, 5, 2.0, 0.005)
    ts = PathTimeSeries(
        id=4,
        name="Beat",
        dt=series.dt,
        values=series.accel.tolist(),
        file_path="generated:sine-beat",
        generator=series.descriptor,
    )
    clone = Project.model_validate(_project(ts).model_dump(mode="json"))
    got = clone.time_series[0]
    assert isinstance(got, PathTimeSeries)
    assert got.generator == series.descriptor
    assert got.file_path == "generated:sine-beat"
    assert np.array_equal(from_descriptor(got.generator).accel, np.asarray(got.values))


def test_trig_emission_arguments() -> None:
    ts = TrigTimeSeries(
        id=5, factor=2.5, t_start=1.0, t_end=9.0, period=0.25, shift=0.3, zero_shift=0.1
    )
    ops = MagicMock()
    runner = OpenSeesRunner(_project(ts), ops_module=ops)
    runner._emit_patterns_for_case([7])
    call = ops.timeSeries.call_args_list[0]
    assert call.args == (
        "Trig",
        5,
        1.0,
        9.0,
        0.25,
        "-factor",
        2.5,
        "-shift",
        0.3,
        "-zeroShift",
        0.1,
    )
    pat = ops.pattern.call_args_list[0]
    assert pat.args[:4] == ("UniformExcitation", 7, 1, "-accel")
    assert pat.args[4] == 5
