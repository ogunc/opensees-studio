"""Synthetic excitation generators: continuous sine and sine-beat.

Generated inputs are not catalog records. They are stored on the project
as a native ``TrigTimeSeries`` (plain sine, no ramps) or as an embedded
``PathTimeSeries`` whose ``file_path`` is ``generated:<kind>`` and whose
``generator`` field holds the descriptor returned here, so the series can
be regenerated and edited later. ``from_descriptor`` rebuilds the samples
from that descriptor.

Sample values are in whatever unit the amplitude is given in; the caller
decides the unit (g or project acceleration units) and sets the series
factor accordingly.

Sine-beat: each beat is a sine at the test frequency multiplied by a
half-sine envelope spanning the beat, ``sin(2 pi f tau) sin(pi tau / T_beat)``
with ``T_beat = cycles / f``. Because an integer number of cycles puts the
envelope maximum at a zero crossing of the carrier, the sampled beat is
scaled so its peak equals the requested amplitude exactly. The preset
"IEEE 693 style (engineer to confirm)" (5 beats of 10 cycles, 2 s pause)
follows the usual sine-beat description of that standard and must be
checked against the standard's text before it is relied on.
"""

from __future__ import annotations

from typing import Any, NamedTuple

import numpy as np

GeneratorKind = str
SINE = "sine"
SINE_BEAT = "sine-beat"
GENERATED_PREFIX = "generated:"


class GeneratedSeries(NamedTuple):
    """Uniformly sampled synthetic acceleration plus the parameters that made it."""

    dt: float
    accel: np.ndarray
    descriptor: dict[str, Any]


class BeatPreset(NamedTuple):
    """Sine-beat parameter set. ``label`` carries the confirmation caveat."""

    n_beats: int
    cycles_per_beat: int
    pause: float
    label: str


IEEE693_BEAT_PRESET = BeatPreset(
    n_beats=5, cycles_per_beat=10, pause=2.0, label="IEEE 693 style (engineer to confirm)"
)
BEAT_PRESETS: tuple[BeatPreset, ...] = (IEEE693_BEAT_PRESET,)


def generated_source(kind: GeneratorKind) -> str:
    """``file_path`` marker of an embedded generated series (``generated:sine-beat``)."""
    return f"{GENERATED_PREFIX}{kind}"


def _check_positive(name: str, value: float) -> None:
    if not value > 0.0:
        raise ValueError(f"{name} must be positive, got {value!r}.")


def sine_duration(duration: float, dt: float) -> int:
    """Number of samples of a sine of ``duration`` seconds at ``dt`` (inclusive end)."""
    _check_positive("duration", duration)
    _check_positive("dt", dt)
    return round(duration / dt) + 1


def sine_excitation(
    amplitude: float,
    frequency: float,
    duration: float,
    dt: float,
    ramp_in_cycles: float = 0.0,
    ramp_out_cycles: float = 0.0,
) -> GeneratedSeries:
    """Continuous sine ``A sin(2 pi f t)`` with optional linear ramps.

    ``ramp_in_cycles`` cycles at the start rise linearly from zero and
    ``ramp_out_cycles`` cycles at the end fall linearly to zero, so a ramped
    sine starts and ends at exactly zero. The ramps must fit inside the
    duration. ``amplitude`` is the peak of the unramped part.
    """
    _check_positive("amplitude", amplitude)
    _check_positive("frequency", frequency)
    if ramp_in_cycles < 0.0 or ramp_out_cycles < 0.0:
        raise ValueError("ramp cycles must not be negative.")
    n = sine_duration(duration, dt)
    if (ramp_in_cycles + ramp_out_cycles) / frequency > duration + 1e-12:
        raise ValueError(
            f"ramps of {ramp_in_cycles} + {ramp_out_cycles} cycles at {frequency} Hz "
            f"do not fit in {duration} s."
        )
    t = np.arange(n, dtype=float) * dt
    accel = amplitude * np.sin(2.0 * np.pi * frequency * t)
    envelope = np.ones(n)
    if ramp_in_cycles > 0.0:
        envelope = np.minimum(envelope, t / (ramp_in_cycles / frequency))
    if ramp_out_cycles > 0.0:
        # measured from the last sample, so the series ends at exactly zero
        envelope = np.minimum(envelope, (t[-1] - t) / (ramp_out_cycles / frequency))
    accel *= np.clip(envelope, 0.0, 1.0)
    descriptor: dict[str, Any] = {
        "kind": SINE,
        "amplitude": float(amplitude),
        "frequency": float(frequency),
        "duration": float(duration),
        "dt": float(dt),
        "ramp_in_cycles": float(ramp_in_cycles),
        "ramp_out_cycles": float(ramp_out_cycles),
    }
    return GeneratedSeries(float(dt), accel, descriptor)


def sine_beat_duration(frequency: float, cycles_per_beat: int, n_beats: int, pause: float) -> float:
    """Total duration ``n_beats * cycles / f + (n_beats - 1) * pause`` in seconds."""
    return n_beats * cycles_per_beat / frequency + (n_beats - 1) * pause


def sine_beat_excitation(
    amplitude: float,
    frequency: float,
    cycles_per_beat: int,
    n_beats: int,
    pause: float,
    dt: float,
) -> GeneratedSeries:
    """Train of ``n_beats`` sine beats separated by ``pause`` seconds of zeros.

    Each beat holds ``cycles_per_beat`` cycles at ``frequency`` under a
    half-sine envelope and is scaled so its sampled peak equals
    ``amplitude``. Every beat starts with its envelope zero, the pauses are
    exact zeros and one trailing zero closes the series, so the sample
    count is ``n_beats * n_beat + (n_beats - 1) * n_pause + 1`` with
    ``n_beat = round(cycles / (f dt))`` and ``n_pause = round(pause / dt)``.
    """
    _check_positive("amplitude", amplitude)
    _check_positive("frequency", frequency)
    _check_positive("dt", dt)
    if int(cycles_per_beat) < 1 or cycles_per_beat != int(cycles_per_beat):
        raise ValueError(f"cycles_per_beat must be a positive integer, got {cycles_per_beat!r}.")
    if int(n_beats) < 1 or n_beats != int(n_beats):
        raise ValueError(f"n_beats must be a positive integer, got {n_beats!r}.")
    if pause < 0.0:
        raise ValueError("pause must not be negative.")
    t_beat = cycles_per_beat / frequency
    n_beat = round(t_beat / dt)
    if n_beat < 4 * cycles_per_beat:
        raise ValueError(
            f"dt = {dt} is too coarse for {frequency} Hz: fewer than four samples per cycle."
        )
    n_pause = round(pause / dt)
    tau = np.arange(n_beat, dtype=float) * dt
    beat = np.sin(2.0 * np.pi * frequency * tau) * np.sin(np.pi * tau / t_beat)
    beat *= amplitude / float(np.max(np.abs(beat)))
    blocks: list[np.ndarray] = []
    for k in range(int(n_beats)):
        blocks.append(beat)
        if k < n_beats - 1:
            blocks.append(np.zeros(n_pause))
    blocks.append(np.zeros(1))
    accel = np.concatenate(blocks)
    descriptor: dict[str, Any] = {
        "kind": SINE_BEAT,
        "amplitude": float(amplitude),
        "frequency": float(frequency),
        "cycles_per_beat": int(cycles_per_beat),
        "n_beats": int(n_beats),
        "pause": float(pause),
        "dt": float(dt),
    }
    return GeneratedSeries(float(dt), accel, descriptor)


def from_descriptor(descriptor: dict[str, Any]) -> GeneratedSeries:
    """Regenerate a series from the descriptor stored on the project."""
    params = {k: v for k, v in descriptor.items() if k != "kind"}
    kind = descriptor.get("kind")
    if kind == SINE:
        return sine_excitation(**params)
    if kind == SINE_BEAT:
        return sine_beat_excitation(**params)
    raise ValueError(f"Unknown generator kind {kind!r}.")
