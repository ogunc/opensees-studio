"""GroundMotionCatalogViewModel: Qt-free state behind the Ground Motions dialog.

Reads the project's ground-motion catalog, parses record files for the
trace plot and the metadata columns (PGA, D5-95), computes response
spectra in g, previews scale factors against the project's target
spectrum, and builds the new or relinked
:class:`~opensees_studio.core.GroundMotionRecord` entries and the
:class:`~opensees_studio.core.TargetSpectrum` the dialog then applies
through undoable commands. No Qt import: the dialog owns an instance
and calls plain methods.

``base_dir`` is the directory of the project file; relative
``source_path`` entries resolve against it. For a project that has
never been saved there is no anchor yet, so imports store an absolute
path; the first save re-anchors it to a relative one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from opensees_studio.core import (
    DEFAULT_DAMPING,
    TBDY_RANGE_PRESET,
    ElasticSpectrum,
    GroundMotionAccelUnits,
    GroundMotionFormat,
    GroundMotionMetadata,
    GroundMotionRecord,
    PathTimeSeries,
    Project,
    ScalingMethod,
    TargetSpectrum,
    TimeSeries,
    TrigTimeSeries,
    UnitSystem,
    accel_in_g,
    compute_metadata,
    default_periods,
    from_descriptor,
    generated_source,
    gravity,
    import_record,
    period_range_scale_factors,
    pga_scale_factor,
    read_record,
    response_spectrum,
    sa_t1_scale_factor,
    series_factor,
    sine_beat_excitation,
    sine_excitation,
)

#: Combo entries for the import-format override: (key, label).
#: ``None`` key = auto-detect from content.
FORMAT_CHOICES: list[tuple[GroundMotionFormat | None, str]] = [
    (None, "Auto-detect"),
    ("peer_at2", "PEER AT2 / NGA"),
    ("two_column", "Two columns: time, acceleration"),
    ("single_column", "Values only (dt given below)"),
]

#: Combo entries for a record's acceleration units.
UNIT_CHOICES: list[tuple[GroundMotionAccelUnits, str]] = [
    ("g", "g"),
    ("project", "Project units"),
    ("unknown", "Unknown"),
]

#: Combo entries for the scaling method.
METHOD_CHOICES: list[tuple[ScalingMethod, str]] = [
    ("pga", "PGA to target PGA"),
    ("sa_t1", "Sa(T1) to target Sa(T1)"),
    ("period_range", "Period range [a T1, b T1], mean spectrum"),
]

#: Combo entries for the excitation generator: (kind, label).
GENERATOR_CHOICES: list[tuple[str, str]] = [
    ("sine", "Continuous sine"),
    ("sine-beat", "Sine-beat"),
]

#: Units the generated amplitude can be given in: (key, label).
GENERATED_UNIT_CHOICES: list[tuple[GroundMotionAccelUnits, str]] = [
    ("g", "g"),
    ("project", "Project units"),
]

#: Periods for the spectrum plot: the default grid without T = 0 (log axis).
PLOT_PERIODS = default_periods()[1:]


@dataclass
class ScalingPreview:
    """Factors computed for a set of records, nothing applied yet."""

    method: ScalingMethod
    factors: dict[int, float] = field(default_factory=dict)
    """Amplitude factor per record id (multiplies the record in g)."""
    series_factors: dict[int, float] = field(default_factory=dict)
    """New ``PathTimeSeries.factor`` per series id backed by those records."""
    unbacked: list[int] = field(default_factory=list)
    """Record ids no time series is backed by (nowhere to write a factor)."""
    periods: np.ndarray | None = None
    scaled_mean_sa: np.ndarray | None = None
    governing_period: float | None = None
    min_ratio: float | None = None
    summary: str = ""


def read_user_spectrum_table(path: str | Path) -> tuple[list[float], list[float]]:
    """``period  Sa[g]`` rows (whitespace or comma separated, ``#`` comments)."""
    periods: list[float] = []
    sa: list[float] = []
    for lineno, line in enumerate(Path(path).read_text().splitlines(), start=1):
        text = line.split("#", 1)[0].strip()
        if not text:
            continue
        toks = text.replace(",", " ").split()
        if len(toks) != 2:
            raise ValueError(f"{path}:{lineno}: expected 2 columns (period, Sa in g).")
        periods.append(float(toks[0]))
        sa.append(float(toks[1]))
    if len(periods) < 2:
        raise ValueError(f"{path}: a user spectrum needs at least 2 rows.")
    return periods, sa


def _default_generated_name(descriptor: dict[str, Any]) -> str:
    kind = descriptor.get("kind", "generated")
    freq = float(descriptor.get("frequency", 0.0))
    amp = float(descriptor.get("amplitude", 0.0))
    units = descriptor.get("units", "")
    return f"{kind} {freq:g} Hz {amp:g} {units}".strip()


class GroundMotionCatalogViewModel:
    """Catalog reads, record parsing, metadata, spectra; mutations stay in commands."""

    def __init__(self, project: Project | None, base_dir: Path | None = None) -> None:
        self._project = project
        self._base_dir = base_dir
        self._values_cache: dict[int, np.ndarray | None] = {}
        self._metadata_cache: dict[int, GroundMotionMetadata | None] = {}
        self._spectrum_cache: dict[tuple[int, float], ElasticSpectrum] = {}

    def set_project(self, project: Project | None, base_dir: Path | None = None) -> None:
        self._project = project
        self._base_dir = base_dir
        self.invalidate()

    def invalidate(self) -> None:
        """Drop cached samples/metadata/spectra (after any catalog mutation)."""
        self._values_cache.clear()
        self._metadata_cache.clear()
        self._spectrum_cache.clear()

    # ---- reads -------------------------------------------------------------
    def records(self) -> list[GroundMotionRecord]:
        return list(self._project.ground_motions) if self._project else []

    def record(self, record_id: int) -> GroundMotionRecord:
        if self._project is None:
            raise KeyError(record_id)
        return self._project.ground_motion(record_id)

    def unit_system(self) -> UnitSystem:
        return self._project.meta.units if self._project else UnitSystem.SI_M_N

    def series_using(self, record_id: int) -> list[int]:
        """Ids of time series backed by ``record_id`` (blocks removal)."""
        if self._project is None:
            return []
        return [
            ts.id for ts in self._project.time_series if getattr(ts, "record_id", None) == record_id
        ]

    def resolve(self, record: GroundMotionRecord) -> Path:
        base = self._base_dir if self._base_dir is not None else Path()
        return base / record.source_path

    def values_for(self, record: GroundMotionRecord) -> np.ndarray | None:
        """The record's samples for the trace plot, or None when unreadable."""
        if record.id not in self._values_cache:
            self._values_cache[record.id] = self._read(record)
        return self._values_cache[record.id]

    def metadata_for(self, record: GroundMotionRecord) -> GroundMotionMetadata | None:
        if record.id not in self._metadata_cache:
            values = self.values_for(record)
            self._metadata_cache[record.id] = (
                compute_metadata(record.dt, values) if values is not None else None
            )
        return self._metadata_cache[record.id]

    def accel_g_for(self, record: GroundMotionRecord) -> np.ndarray:
        """The record's samples in g.

        Raises:
            ValueError: unreadable file, or ``accel_units == "unknown"``
                (the message names the record and how to fix it).
        """
        values = self.values_for(record)
        if values is None:
            raise ValueError(
                f"'{record.name}': cannot read {record.source_path} (status: {record.status})."
            )
        return accel_in_g(values, record.accel_units, self.unit_system(), record.name)

    def spectrum_for(
        self, record: GroundMotionRecord, damping: float = DEFAULT_DAMPING
    ) -> ElasticSpectrum:
        """Elastic spectrum in g on :data:`PLOT_PERIODS` (cached)."""
        key = (record.id, float(damping))
        if key not in self._spectrum_cache:
            self._spectrum_cache[key] = response_spectrum(
                record.dt, self.accel_g_for(record), damping, periods=PLOT_PERIODS
            )
        return self._spectrum_cache[key]

    def active_target(self) -> TargetSpectrum | None:
        """The project's target spectrum (the first entry), if any."""
        if self._project is None or not self._project.target_spectra:
            return None
        return self._project.target_spectra[0]

    def _read(self, record: GroundMotionRecord) -> np.ndarray | None:
        if record.status not in ("ok", "pending_sidecar"):
            return None
        if record.status == "pending_sidecar":
            values = self._pending_values(record)
            return np.asarray(values, dtype=float) if values else None
        try:
            _dt, values, _fields = read_record(self.resolve(record), record.format, dt=record.dt)
        except (OSError, ValueError):
            return None
        return values

    def _pending_values(self, record: GroundMotionRecord) -> list[float] | None:
        """Legacy values still held in memory by the backed series."""
        if self._project is None:
            return None
        return next(
            (
                ts.values
                for ts in self._project.time_series
                if getattr(ts, "record_id", None) == record.id and ts.values
            ),
            None,
        )

    # ---- entry builders (applied via commands by the dialog) ---------------
    def build_import(
        self,
        path: str | Path,
        format: GroundMotionFormat | None = None,
        dt: float | None = None,
        name: str = "",
    ) -> GroundMotionRecord:
        """Parse ``path`` into a new catalog entry (not yet added)."""
        if self._project is None:
            raise ValueError("No open project to import into.")
        record, _values = import_record(
            path,
            base_dir=self._base_dir,
            record_id=self._project.next_ground_motion_id(),
            name=name or Path(path).stem,
            format=format,
            dt=dt,
        )
        return record

    def build_relink(
        self,
        record: GroundMotionRecord,
        new_path: str | Path,
    ) -> tuple[GroundMotionRecord, list[float]]:
        """Re-import ``new_path`` under the entry's id; hash re-checked.

        The file is parsed with the entry's stored format (its dt for a
        single-column file), so a wrong pick fails with the reader's
        message instead of silently changing the record's meaning.
        """
        relinked, values = import_record(
            new_path,
            base_dir=self._base_dir,
            record_id=record.id,
            name=record.name,
            format=record.format,
            dt=record.dt,
            accel_units=record.accel_units,
            source_note=record.source_note,
        )
        return relinked, values

    def _target_id(self) -> int:
        active = self.active_target()
        if active is not None:
            return active.id
        return self._project.next_target_spectrum_id() if self._project else 1

    def build_target_tbdy(self, sds: float, sd1: float, name: str = "") -> TargetSpectrum:
        """A TBDY 2018 target that replaces the active one (same id)."""
        return TargetSpectrum(
            id=self._target_id(),
            name=name or f"TBDY 2018 SDS={sds:g} SD1={sd1:g}",
            kind="tbdy2018",
            sds=sds,
            sd1=sd1,
        )

    def build_target_user(self, path: str | Path, name: str = "") -> TargetSpectrum:
        """A user-table target parsed from ``path`` (period, Sa in g)."""
        periods, sa = read_user_spectrum_table(path)
        return TargetSpectrum(
            id=self._target_id(),
            name=name or Path(path).stem,
            kind="user",
            periods=periods,
            sa=sa,
        )

    # ---- generated inputs (not records) ------------------------------------
    def generated_series(self) -> list[TimeSeries]:
        """Time series built by the generator: Trig series and generated Path series."""
        if self._project is None:
            return []
        return [
            ts
            for ts in self._project.time_series
            if isinstance(ts, TrigTimeSeries)
            or (isinstance(ts, PathTimeSeries) and ts.generator is not None)
        ]

    def next_series_id(self) -> int:
        if self._project is None:
            return 1
        return self._project.next_time_series_id()

    @staticmethod
    def generated_accel(descriptor: dict[str, Any]) -> tuple[float, np.ndarray]:
        """``(dt, accel)`` in the descriptor's amplitude unit (``ValueError`` on bad parameters)."""
        series = from_descriptor(descriptor)
        return series.dt, series.accel

    def generated_spectrum(
        self, descriptor: dict[str, Any], damping: float = DEFAULT_DAMPING
    ) -> ElasticSpectrum:
        """Elastic spectrum in g of the series a descriptor describes, on :data:`PLOT_PERIODS`."""
        dt, accel = self.generated_accel(descriptor)
        units = descriptor.get("units", "g")
        return response_spectrum(
            dt, accel_in_g(accel, units, self.unit_system(), "generated"), damping, PLOT_PERIODS
        )

    def build_generated_series(
        self,
        descriptor: dict[str, Any],
        *,
        series_id: int | None = None,
        name: str = "",
    ) -> TimeSeries:
        """The project entity for a generator descriptor (``units`` key required).

        A plain sine without ramps becomes a native :class:`TrigTimeSeries`
        (amplitude folded into its factor); everything else an embedded
        :class:`PathTimeSeries` with ``file_path="generated:<kind>"``. The
        descriptor is stored on the entity so the generator can reopen it.
        The unit conversion lives in the factor: g when the amplitude is in g,
        1.0 for project units. Nothing is added to the catalog.
        """
        units = descriptor.get("units")
        if units not in ("g", "project"):
            raise ValueError("Generated amplitude units must be g or project units.")
        kind = descriptor.get("kind")
        scale = gravity(self.unit_system()) if units == "g" else 1.0
        sid = series_id if series_id is not None else self.next_series_id()
        label = name or _default_generated_name(descriptor)
        if kind == "sine" and not (
            descriptor.get("ramp_in_cycles") or descriptor.get("ramp_out_cycles")
        ):
            generated = sine_excitation(
                **{k: v for k, v in descriptor.items() if k not in ("kind", "units")}
            )
            return TrigTimeSeries(
                id=sid,
                name=label,
                factor=float(descriptor["amplitude"]) * scale,
                t_start=0.0,
                t_end=float(descriptor["duration"]),
                period=1.0 / float(descriptor["frequency"]),
                generator=dict(generated.descriptor, units=units),
            )
        if kind == "sine":
            generated = sine_excitation(
                **{k: v for k, v in descriptor.items() if k not in ("kind", "units")}
            )
        elif kind == "sine-beat":
            generated = sine_beat_excitation(
                **{k: v for k, v in descriptor.items() if k not in ("kind", "units")}
            )
        else:
            raise ValueError(f"Unknown generator kind {kind!r}.")
        return PathTimeSeries(
            id=sid,
            name=label,
            dt=generated.dt,
            values=generated.accel.tolist(),
            factor=scale,
            file_path=generated_source(str(kind)),
            generator=dict(generated.descriptor, units=units),
        )

    @staticmethod
    def generator_descriptor_of(ts: TimeSeries) -> dict[str, Any] | None:
        """The descriptor to reopen the generator with, or None for a hand-made series."""
        generator = getattr(ts, "generator", None)
        if generator is not None:
            return dict(generator)
        if isinstance(ts, TrigTimeSeries):
            # a Trig series defined without the generator: amplitude in project units
            return {
                "kind": "sine",
                "amplitude": abs(ts.factor),
                "frequency": ts.frequency,
                "duration": ts.t_end - ts.t_start,
                "dt": 0.01,
                "ramp_in_cycles": 0.0,
                "ramp_out_cycles": 0.0,
                "units": "project",
            }
        return None

    # ---- scaling preview ------------------------------------------------------
    def preview_scaling(
        self,
        method: ScalingMethod,
        record_ids: list[int],
        *,
        target_pga: float | None = None,
        t1: float | None = None,
        a: float = TBDY_RANGE_PRESET.a,
        b: float = TBDY_RANGE_PRESET.b,
        alpha: float = TBDY_RANGE_PRESET.alpha,
        individual: bool = False,
        pair_consecutive: bool = False,
        damping: float = DEFAULT_DAMPING,
    ) -> ScalingPreview:
        """Factors for ``record_ids`` by ``method``; nothing is applied.

        Raises:
            ValueError: no records, unknown units (the refusal text), no
                target spectrum for the spectrum methods, bad parameters.
        """
        if not record_ids:
            raise ValueError("Select at least one record to scale.")
        records = [self.record(rid) for rid in record_ids]
        accel_g = {rec.id: (rec.dt, self.accel_g_for(rec)) for rec in records}
        preview = ScalingPreview(method=method)

        if method == "pga":
            if target_pga is None:
                raise ValueError("Target PGA is required for PGA scaling.")
            for rec in records:
                preview.factors[rec.id] = pga_scale_factor(accel_g[rec.id][1], target_pga)
            preview.summary = f"PGA scaled to {target_pga:g} g."
        else:
            target = self.active_target()
            if target is None:
                raise ValueError("Set a target spectrum first (TBDY 2018 or a user table).")
            if t1 is None or t1 <= 0.0:
                raise ValueError("T1 must be positive.")
            if method == "sa_t1":
                for rec in records:
                    dt, acc = accel_g[rec.id]
                    preview.factors[rec.id] = sa_t1_scale_factor(dt, acc, target, t1, damping)
                preview.summary = f"Sa(T1={t1:g} s) matched to target {target.sa_at(t1)[0]:.4g} g."
            else:
                pairs = None
                if pair_consecutive:
                    if len(record_ids) % 2:
                        raise ValueError("Pairing needs an even number of selected records.")
                    pairs = [
                        (record_ids[i], record_ids[i + 1]) for i in range(0, len(record_ids), 2)
                    ]
                result = period_range_scale_factors(
                    accel_g,
                    target,
                    t1,
                    a=a,
                    b=b,
                    alpha=alpha,
                    individual=individual,
                    pairs=pairs,
                    damping=damping,
                )
                preview.factors = dict(result.factors)
                preview.periods = result.periods
                preview.scaled_mean_sa = result.scaled_mean_sa
                preview.governing_period = result.governing_period
                preview.min_ratio = result.min_ratio
                preview.summary = (
                    f"Range [{a:g} T1, {b:g} T1] = [{a * t1:.3g}, {b * t1:.3g}] s, "
                    f"alpha {alpha:g}: governing period {result.governing_period:.3g} s, "
                    f"minimum mean/target ratio {result.min_ratio:.4g}."
                )

        units = self.unit_system()
        for rec in records:
            series = self.series_using(rec.id)
            if not series:
                preview.unbacked.append(rec.id)
            for sid in series:
                preview.series_factors[sid] = series_factor(
                    preview.factors[rec.id], rec.accel_units, units
                )
        return preview
