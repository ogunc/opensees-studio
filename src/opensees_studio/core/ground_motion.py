"""Ground-motion records: catalog model, file readers, content hashing.

A :class:`GroundMotionRecord` is a *reference* to an acceleration record
on disk — the project stores the relative path plus a content hash,
never the sample values themselves (PEER NGA terms do not allow
redistribution, and embedding megabytes of samples in ``.osmodel``
defeats diffing). The samples are re-read from the file on project load
and hydrated into the record-backed ``PathTimeSeries``.

Readers, one per supported format, all return ``(dt, values, fields)``
where ``values`` is a ``numpy.ndarray`` of accelerations and ``fields``
is a dict of whatever the header carried:

* :func:`read_peer_at2` — PEER AT2 / NGA files (header lines, an
  ``NPTS, DT`` line in either the new NGA or the old SMD spelling,
  values row-wise).
* :func:`read_two_column` — ``time  acceleration`` pairs (whitespace or
  comma separated); dt is inferred and validated as uniform.
* :func:`read_single_column` — bare acceleration values with a
  user-given dt. Multiple values per line are accepted and read
  row-wise (PEER "one column" exports commonly wrap 5 per line).

This module is part of ``core``: no Qt, no openseespy.
"""

from __future__ import annotations

import hashlib
import itertools
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import numpy as np
from pydantic import Field, NonNegativeFloat, PositiveFloat, PositiveInt

from opensees_studio.core._base import Entity

GroundMotionFormat = Literal["peer_at2", "two_column", "single_column"]

#: What the sample values are: g, the project's acceleration unit, or unknown.
GroundMotionAccelUnits = Literal["g", "project", "unknown"]

#: Relative tolerance for "is the time column uniform?" in two-column files.
DT_UNIFORMITY_RTOL = 1e-3


class GroundMotionRecord(Entity):
    """Catalog entry referencing an acceleration record file.

    ``source_path`` is stored relative to the project file (POSIX
    separators) so a project travels together with its records.
    ``content_hash`` is the sha256 of the file bytes after CRLF → LF
    normalisation (same rule as the codegen stamp), so the hash is
    stable across platforms and line-ending conversions.
    """

    source_path: str = Field(
        ...,
        description="Record file path, relative to the project file (POSIX separators).",
    )
    content_hash: str = Field(
        default="",
        description=(
            "sha256 hex digest of the file bytes after CRLF-to-LF normalisation. "
            "Empty only while the entry is 'pending_sidecar' (legacy values not "
            "yet written to disk)."
        ),
    )
    format: GroundMotionFormat = Field(
        ...,
        description="File format the record is parsed with.",
    )
    dt: PositiveFloat = Field(..., description="Sampling interval (s).")
    npts: PositiveInt = Field(..., description="Number of acceleration samples.")
    accel_units: GroundMotionAccelUnits = Field(
        default="unknown",
        description=(
            "Units of the raw file values: 'g', or 'project' for length/s^2 in "
            "the project's unit system. 'unknown' for migrated legacy entries "
            "whose units were never recorded — the series' scale factor still "
            "carries whatever conversion the user set up."
        ),
    )
    source_note: str = Field(
        default="",
        description="Free-text provenance: event, station, component, ...",
    )
    status: Literal["ok", "missing", "hash_mismatch", "pending_sidecar"] = Field(
        default="ok",
        description=(
            "Load-time health of the reference. 'missing': file not found; "
            "'hash_mismatch': file found but its content hash changed; "
            "'pending_sidecar': legacy embedded values not yet written to a "
            "sidecar file (created at the next save). Analysis refuses to run "
            "cases whose records are not 'ok'."
        ),
    )
    total_duration: NonNegativeFloat = Field(
        default=0.0,
        description="Convenience: (npts - 1) * dt, kept in sync on import.",
    )


# ──────────────────────────── hashing ────────────────────────────
def content_hash_of_bytes(raw: bytes) -> str:
    """sha256 hex digest of ``raw`` after CRLF → LF normalisation."""
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def content_hash_of_file(path: str | Path) -> str:
    """sha256 hex digest of the file at ``path`` (CRLF-normalised)."""
    return content_hash_of_bytes(Path(path).read_bytes())


# ──────────────────────────── readers ────────────────────────────
_NPTS_DT_OLD = re.compile(r"NPTS\s*=\s*(\d+)\s*,?\s*DT\s*=\s*([0-9.eE+\-]+)")
_NPTS_DT_NEW = re.compile(r"^\s*(\d+)\s+([0-9.eE+\-]+)\s+NPTS\s*,\s*DT")
_UNITS_LINE = re.compile(r"IN UNITS OF\s+(\S+)", re.IGNORECASE)


def _float_tokens(line: str) -> list[float]:
    """Every numeric token in ``line`` (comma or whitespace separated).

    Raises ``ValueError`` on the first non-numeric token so a stray text
    line is reported instead of silently skipped.
    """
    return [float(tok) for tok in line.replace(",", " ").split()]


def read_peer_at2(path: str | Path) -> tuple[float, np.ndarray, dict[str, Any]]:
    """Read a PEER AT2 / NGA record.

    Accepts both header spellings (mirroring OpenSees ``ReadRecord.tcl``):

    * new NGA: ``3930    0.00500    NPTS, DT``
    * old SMD: ``NPTS=  3930, DT= .00500 SEC``

    Returns ``(dt, values, fields)``. ``fields`` carries ``npts`` and
    ``dt`` from the header, plus ``units`` (from an ``IN UNITS OF …``
    line, e.g. ``"G"``) and ``event`` (the second header line of the
    standard PEER layout) when present.

    Raises:
        ValueError: no ``NPTS/DT`` header found, no data after the
            header, or the sample count contradicts the header.
    """
    lines = Path(path).read_text().splitlines()

    npts: int | None = None
    dt: float | None = None
    data_start: int | None = None
    fields: dict[str, Any] = {}

    for i, line in enumerate(lines[:10]):
        stripped = line.strip()
        if not stripped:
            continue
        m = _NPTS_DT_OLD.search(stripped) or _NPTS_DT_NEW.match(stripped)
        if m:
            npts = int(m.group(1))
            dt = float(m.group(2))
            data_start = i + 1
            break
        m_units = _UNITS_LINE.search(stripped)
        if m_units:
            fields["units"] = m_units.group(1)
        elif i == 1:
            fields["event"] = stripped

    if npts is None or dt is None or data_start is None:
        raise ValueError(
            f"{path}: no 'NPTS, DT' header line found in the first 10 lines - "
            "not a PEER AT2 record. Import it as two-column or single-column instead."
        )
    fields["npts"] = npts
    fields["dt"] = dt

    values: list[float] = []
    for line in lines[data_start:]:
        values.extend(_float_tokens(line))
    if not values:
        raise ValueError(f"{path}: header parsed but no data lines follow it.")
    if len(values) < npts:
        raise ValueError(
            f"{path}: header announces NPTS={npts} but only {len(values)} values follow."
        )
    return dt, np.asarray(values[:npts], dtype=float), fields


def read_two_column(
    path: str | Path,
    rtol: float = DT_UNIFORMITY_RTOL,
) -> tuple[float, np.ndarray, dict[str, Any]]:
    """Read a ``time acceleration`` file (whitespace or comma separated).

    dt is inferred from the time column and validated as uniform within
    ``rtol`` (relative to the median step).

    Raises:
        ValueError: fewer than 2 rows, a row without exactly 2 numbers,
            or a non-uniform time step.
    """
    rows: list[tuple[float, float]] = []
    for lineno, line in enumerate(Path(path).read_text().splitlines(), start=1):
        if not line.strip():
            continue
        toks = _float_tokens(line)
        if len(toks) != 2:
            raise ValueError(
                f"{path}:{lineno}: expected 2 columns (time, acceleration), got {len(toks)} values."
            )
        rows.append((toks[0], toks[1]))
    if len(rows) < 2:
        raise ValueError(f"{path}: a two-column record needs at least 2 rows.")

    times = np.array([r[0] for r in rows])
    accel = np.array([r[1] for r in rows])
    steps = np.diff(times)
    dt = float(np.median(steps))
    if dt <= 0.0:
        raise ValueError(f"{path}: time column is not strictly increasing.")
    bad = np.flatnonzero(np.abs(steps - dt) > rtol * dt)
    if bad.size:
        i = int(bad[0])
        raise ValueError(
            f"{path}: non-uniform time step - dt is {dt:.6g} but the step from "
            f"t={times[i]:.6g} to t={times[i + 1]:.6g} (row {i + 2}) is {steps[i]:.6g}. "
            "Resample the record to a uniform dt before importing."
        )
    return dt, accel, {"t0": float(times[0])}


def read_single_column(
    path: str | Path,
    dt: float,
) -> tuple[float, np.ndarray, dict[str, Any]]:
    """Read bare acceleration values with a user-given ``dt``.

    Values may be wrapped several per line (read row-wise), matching
    PEER "one column" exports and files like the bundled examples'
    ``A10000.txt`` (5 per line).

    Raises:
        ValueError: ``dt <= 0``, no values, or a non-numeric token.
    """
    if dt <= 0.0:
        raise ValueError(f"dt must be positive, got {dt}.")
    return float(dt), np.asarray(read_plain_values(path), dtype=float), {}


def read_plain_values(path: str | Path) -> list[float]:
    """Every numeric token in ``path``, read row-wise, with no header.

    The value list behind :func:`read_single_column`; also what the
    legacy ``services.peer_record.parse_plain_values`` delegates to.

    Raises:
        ValueError: no values, or a non-numeric token.
    """
    values: list[float] = []
    for line in Path(path).read_text().splitlines():
        values.extend(_float_tokens(line))
    if not values:
        raise ValueError(f"{path}: no numeric values found.")
    return values


# ──────────────────────────── detection ────────────────────────────
def detect_format(path: str | Path) -> GroundMotionFormat:
    """Guess the record format from the file content.

    * an ``NPTS/DT`` header line → ``peer_at2``
    * every data line exactly 2 numbers with an increasing first
      column → ``two_column``
    * anything else that parses as numbers → ``single_column``

    The caller can always override the guess by invoking a specific
    reader directly.

    Raises:
        ValueError: the file does not look like any supported format.
    """
    lines = Path(path).read_text().splitlines()

    for line in lines[:10]:
        stripped = line.strip()
        if _NPTS_DT_OLD.search(stripped) or _NPTS_DT_NEW.match(stripped):
            return "peer_at2"

    numeric_lines: list[list[float]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            numeric_lines.append(_float_tokens(line))
        except ValueError:
            raise ValueError(
                f"{path}: unrecognised ground-motion file - no NPTS/DT header "
                "and a non-numeric line outside one."
            ) from None
    if not numeric_lines:
        raise ValueError(f"{path}: file contains no data.")

    if all(len(toks) == 2 for toks in numeric_lines) and len(numeric_lines) >= 2:
        first_col = [toks[0] for toks in numeric_lines]
        if all(b > a for a, b in itertools.pairwise(first_col)):
            return "two_column"
    return "single_column"


def read_record(
    path: str | Path,
    format: GroundMotionFormat,  # shadows the builtin on purpose: mirrors the model field
    dt: float | None = None,
) -> tuple[float, np.ndarray, dict[str, Any]]:
    """Dispatch to the reader for ``format``.

    ``dt`` is required for (and only used by) ``single_column``.
    """
    if format == "peer_at2":
        return read_peer_at2(path)
    if format == "two_column":
        return read_two_column(path)
    if dt is None:
        raise ValueError("single_column format requires an explicit dt.")
    return read_single_column(path, dt)


# ──────────────────────────── import helper ────────────────────────────
def sanitize_record_filename(name: str) -> str:
    """A filesystem-safe stem: keep word chars, dash and dot; rest becomes '_'."""
    cleaned = re.sub(r"[^\w.\-]+", "_", name.strip()).strip("._")
    return cleaned or "record"


def import_record(
    path: str | Path,
    base_dir: str | Path | None,
    record_id: int,
    name: str = "",
    format: GroundMotionFormat | None = None,
    dt: float | None = None,
    accel_units: GroundMotionAccelUnits = "unknown",
    source_note: str = "",
) -> tuple[GroundMotionRecord, list[float]]:
    """Build a catalog entry for the record file at ``path``.

    ``base_dir`` is the directory the project file lives in (or will be
    saved to); ``source_path`` is stored relative to it, POSIX style.
    ``base_dir=None`` (project never saved) stores the absolute path.
    ``format=None`` auto-detects from the content; ``dt`` is required
    for ``single_column``. ``accel_units`` left ``"unknown"`` becomes
    ``"g"`` when a PEER header states ``IN UNITS OF G``.

    Returns ``(record, values)`` - the values are NOT stored on the
    record; the caller hydrates them into the record-backed
    :class:`~opensees_studio.core.loads.PathTimeSeries`.
    """
    src = Path(path)
    fmt = format if format is not None else detect_format(src)
    file_dt, values, fields = read_record(src, fmt, dt=dt)
    if accel_units == "unknown" and str(fields.get("units", "")).upper() == "G":
        accel_units = "g"  # the PEER header says "IN UNITS OF G"
    if base_dir is None:
        rel = src.resolve().as_posix()
    else:
        rel = PurePosixPath(os.path.relpath(src, Path(base_dir))).as_posix()
    record = GroundMotionRecord(
        id=record_id,
        name=name or src.stem,
        source_path=rel,
        content_hash=content_hash_of_file(src),
        format=fmt,
        dt=file_dt,
        npts=len(values),
        accel_units=accel_units,
        source_note=source_note,
        total_duration=(len(values) - 1) * file_dt,
    )
    return record, [float(v) for v in values]
