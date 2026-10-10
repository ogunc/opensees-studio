"""Sine and sine-beat excitation generators."""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest

from opensees_studio.core import (
    IEEE693_BEAT_PRESET,
    from_descriptor,
    generated_source,
    sine_beat_duration,
    sine_beat_excitation,
    sine_excitation,
)

DT = 0.01
F = 1.0


def _nonzero_segments(a: np.ndarray) -> list[tuple[int, int]]:
    """(start, stop) index pairs of the maximal runs of non-zero samples."""
    nz = a != 0.0
    edges = np.flatnonzero(np.diff(np.concatenate(([False], nz, [False]))))
    return [(int(s), int(e)) for s, e in zip(edges[::2], edges[1::2], strict=True)]


# ── continuous sine ───────────────────────────────────────────────────


def test_sine_peak_equals_amplitude() -> None:
    dt, accel, _ = sine_excitation(0.35, F, 10.0, DT)
    assert dt == DT
    assert float(np.max(np.abs(accel))) == pytest.approx(0.35, rel=1e-12)
    assert float(np.max(accel)) == pytest.approx(0.35, rel=1e-12)
    assert float(np.min(accel)) == pytest.approx(-0.35, rel=1e-12)


def test_sine_duration_formula() -> None:
    _, accel, _ = sine_excitation(1.0, F, 10.0, DT)
    assert accel.size == round(10.0 / DT) + 1
    assert (accel.size - 1) * DT == pytest.approx(10.0)


def test_sine_matches_closed_form_without_ramps() -> None:
    _, accel, _ = sine_excitation(2.0, 2.5, 4.0, 0.005)
    t = np.arange(accel.size) * 0.005
    assert np.allclose(accel, 2.0 * np.sin(2.0 * np.pi * 2.5 * t), atol=1e-12)


def test_ramped_sine_starts_and_ends_at_zero() -> None:
    _, accel, _ = sine_excitation(1.0, F, 10.0, DT, ramp_in_cycles=2.0, ramp_out_cycles=2.0)
    assert accel[0] == 0.0
    assert accel[-1] == 0.0
    # the ramps stay below the amplitude, the flat middle reaches it
    n_ramp = round(2.0 / F / DT)
    assert float(np.max(np.abs(accel[:n_ramp]))) < 1.0
    assert float(np.max(np.abs(accel[-n_ramp:]))) < 1.0
    assert float(np.max(np.abs(accel[n_ramp:-n_ramp]))) == pytest.approx(1.0, rel=1e-12)
    # the ramp is linear: the envelope of the first ramp grows with t
    t = np.arange(accel.size) * DT
    inside = slice(1, n_ramp)
    assert np.all(np.abs(accel[inside]) <= t[inside] / 2.0 + 1e-12)


def test_sine_descriptor_roundtrip() -> None:
    series = sine_excitation(0.5, 3.0, 6.0, 0.002, ramp_in_cycles=1.0, ramp_out_cycles=0.5)
    assert series.descriptor["kind"] == "sine"
    assert generated_source(series.descriptor["kind"]) == "generated:sine"
    again = from_descriptor(series.descriptor)
    assert again.dt == series.dt
    assert np.array_equal(again.accel, series.accel)


def test_sine_rejects_bad_parameters() -> None:
    with pytest.raises(ValueError, match="do not fit"):
        sine_excitation(1.0, F, 2.0, DT, ramp_in_cycles=1.5, ramp_out_cycles=1.0)
    with pytest.raises(ValueError, match="frequency"):
        sine_excitation(1.0, 0.0, 2.0, DT)
    with pytest.raises(ValueError, match="dt"):
        sine_excitation(1.0, F, 2.0, 0.0)
    with pytest.raises(ValueError, match="negative"):
        sine_excitation(1.0, F, 2.0, DT, ramp_in_cycles=-1.0)


# ── sine-beat ─────────────────────────────────────────────────────────


def test_beat_peak_equals_amplitude() -> None:
    _, accel, _ = sine_beat_excitation(0.5, F, 10, 5, 2.0, DT)
    assert float(np.max(np.abs(accel))) == pytest.approx(0.5, rel=1e-12)
    # every beat reaches the same peak
    for start, stop in _nonzero_segments(accel):
        assert float(np.max(np.abs(accel[start:stop]))) == pytest.approx(0.5, rel=1e-12)


def test_beat_count_and_zero_pause_segments_exact() -> None:
    _, accel, _ = sine_beat_excitation(1.0, F, 10, 5, 2.0, DT)
    segments = _nonzero_segments(accel)
    assert len(segments) == 5
    n_pause = round(2.0 / DT)
    # each gap is the pause plus the next beat's own zero start sample
    gaps = [nxt[0] - cur[1] for cur, nxt in pairwise(segments)]
    assert gaps == [n_pause + 1] * 4
    assert accel[0] == 0.0 and accel[-1] == 0.0
    assert np.all(accel[segments[-1][1] :] == 0.0)


def test_beat_zero_pause_keeps_beats_adjacent() -> None:
    _, accel, _ = sine_beat_excitation(1.0, F, 10, 3, 0.0, DT)
    segments = _nonzero_segments(accel)
    assert len(segments) == 3
    assert [nxt[0] - cur[1] for cur, nxt in pairwise(segments)] == [1, 1]


def test_beat_duration_formula() -> None:
    _, accel, _ = sine_beat_excitation(1.0, F, 10, 5, 2.0, DT)
    n_beat = round(10 / F / DT)
    n_pause = round(2.0 / DT)
    assert accel.size == 5 * n_beat + 4 * n_pause + 1
    assert (accel.size - 1) * DT == pytest.approx(sine_beat_duration(F, 10, 5, 2.0))
    assert sine_beat_duration(F, 10, 5, 2.0) == pytest.approx(58.0)


def test_beat_is_half_sine_modulated() -> None:
    _, accel, _ = sine_beat_excitation(1.0, F, 10, 1, 0.0, DT)
    beat = accel[:-1]
    # symmetric magnitude about the beat centre (half-sine envelope, integer cycles)
    assert np.allclose(np.abs(beat[1:]), np.abs(beat[1:][::-1]), atol=1e-12)
    # the envelope is |sin(pi tau / T_beat)| scaled: peaks of each cycle follow it
    tau = np.arange(beat.size) * DT
    env = np.abs(np.sin(np.pi * tau / 10.0))
    assert np.all(np.abs(beat) <= env * np.max(np.abs(beat) / np.where(env > 0, env, 1)) + 1e-12)


def test_beat_preset_and_descriptor_roundtrip() -> None:
    assert IEEE693_BEAT_PRESET.n_beats == 5
    assert IEEE693_BEAT_PRESET.cycles_per_beat == 10
    assert IEEE693_BEAT_PRESET.pause == 2.0
    assert "engineer to confirm" in IEEE693_BEAT_PRESET.label
    series = sine_beat_excitation(
        0.3,
        2.0,
        IEEE693_BEAT_PRESET.cycles_per_beat,
        IEEE693_BEAT_PRESET.n_beats,
        IEEE693_BEAT_PRESET.pause,
        0.005,
    )
    assert series.descriptor["kind"] == "sine-beat"
    assert generated_source("sine-beat") == "generated:sine-beat"
    again = from_descriptor(series.descriptor)
    assert np.array_equal(again.accel, series.accel)


def test_beat_rejects_bad_parameters() -> None:
    with pytest.raises(ValueError, match="too coarse"):
        sine_beat_excitation(1.0, 10.0, 10, 1, 0.0, 0.05)
    with pytest.raises(ValueError, match="n_beats"):
        sine_beat_excitation(1.0, F, 10, 0, 0.0, DT)
    with pytest.raises(ValueError, match="cycles_per_beat"):
        sine_beat_excitation(1.0, F, 0, 1, 0.0, DT)
    with pytest.raises(ValueError, match="Unknown generator kind"):
        from_descriptor({"kind": "noise"})
