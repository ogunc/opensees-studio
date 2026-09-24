"""GroundMotionCatalogViewModel: Qt-free state behind the Ground Motions dialog.

Reads the project's ground-motion catalog, parses record files for the
trace plot and the metadata columns (PGA, D5-95), and builds the new or
relinked :class:`~opensees_studio.core.GroundMotionRecord` entries the
dialog then applies through undoable commands. No Qt import: the dialog
owns an instance and calls plain methods.

``base_dir`` is the directory of the project file — relative
``source_path`` entries resolve against it. For a project that has
never been saved there is no anchor yet, so imports store an absolute
path (still portable once the user saves next to the record and
relinks; revisited with the GM-2 scaling work).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from opensees_studio.core import (
    GroundMotionFormat,
    GroundMotionMetadata,
    GroundMotionRecord,
    Project,
    compute_metadata,
    import_record,
    read_record,
)

#: Combo entries for the import-format override: (key, label).
#: ``None`` key = auto-detect from content.
FORMAT_CHOICES: list[tuple[GroundMotionFormat | None, str]] = [
    (None, "Auto-detect"),
    ("peer_at2", "PEER AT2 / NGA"),
    ("two_column", "Two columns: time, acceleration"),
    ("single_column", "Values only (dt given below)"),
]


class GroundMotionCatalogViewModel:
    """Catalog reads, record parsing, metadata; mutations stay in commands."""

    def __init__(self, project: Project | None, base_dir: Path | None = None) -> None:
        self._project = project
        self._base_dir = base_dir
        self._values_cache: dict[int, np.ndarray | None] = {}
        self._metadata_cache: dict[int, GroundMotionMetadata | None] = {}

    def set_project(self, project: Project | None, base_dir: Path | None = None) -> None:
        self._project = project
        self._base_dir = base_dir
        self.invalidate()

    def invalidate(self) -> None:
        """Drop cached samples/metadata (after any catalog mutation)."""
        self._values_cache.clear()
        self._metadata_cache.clear()

    # ---- reads -------------------------------------------------------------
    def records(self) -> list[GroundMotionRecord]:
        return list(self._project.ground_motions) if self._project else []

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
