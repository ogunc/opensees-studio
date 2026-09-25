"""Project persistence — read/write ``.osmodel`` JSON files.

The on-disk format is the result of ``Project.model_dump(by_alias=True)``
with indented JSON. The schema is fully captured by the Pydantic models;
external schema files are intentionally avoided.

Loading routes through Pydantic validation, so a corrupt or
out-of-spec file fails loudly with a precise error message rather than
loading half-broken data.

Ground-motion records (schema v2)
---------------------------------
Records are referenced from the project by relative path plus a content
hash, never embedded in ``.osmodel``:

* **On load**, a legacy (v1) embedded ``PathTimeSeries`` that carries a
  ``file_path`` is migrated into a ``ground_motions`` catalog entry —
  but only when its source can be identified with certainty: the file
  resolves next to the project (or in its ``data/`` folder) AND parses
  to exactly the embedded values. Unresolvable sources keep their
  values in memory with status ``pending_sidecar``; unmatched or
  ``generated:*`` sources stay embedded untouched.
* Record-backed series are then **hydrated**: values re-read from the
  file. A missing file or changed content flags the catalog entry
  (``missing`` / ``hash_mismatch``) — the project still loads, and the
  analysis runner refuses to run cases that use the flagged record.
* **On save**, ``pending_sidecar`` values are written to a
  ``<project-stem>.records/`` sidecar folder (full float precision,
  never overwriting a file with different content), and the ``values``
  of every healthy record-backed series are dropped from the JSON.

``on_notice`` (both :func:`load_project` and :func:`save_project`)
receives one-line human-readable messages about migrations, sidecar
writes, and flagged records — the GUI routes them to the status bar.
"""

from __future__ import annotations

import json
import os
import sys
import warnings
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import numpy as np

from opensees_studio.core import Project
from opensees_studio.core.ground_motion import (
    content_hash_of_bytes,
    content_hash_of_file,
    detect_format,
    read_record,
    record_path_to_posix,
    sanitize_record_filename,
)

PROJECT_FILE_SUFFIX = ".osmodel"

#: Current on-disk schema. 1 = records embedded in PathTimeSeries;
#: 2 = ground_motions catalog with record-backed series.
SCHEMA_VERSION = 2

#: Sidecar folder for legacy values that had no locatable source file:
#: ``<project-stem>`` + this suffix, next to the ``.osmodel``.
SIDECAR_DIR_SUFFIX = ".records"

#: Relative tolerance when deciding whether a resolved file really is
#: the source of embedded legacy values.
_MIGRATION_RTOL = 1e-9

Notice = Callable[[str], None]


def _path_series(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        ts
        for ts in payload.get("time_series", [])
        if isinstance(ts, dict) and ts.get("type") == "Path"
    ]


def _resolve_legacy_source(base_dir: Path, file_path: str) -> Path | None:
    """Find a legacy ``file_path`` next to the project or in ``data/``."""
    file_path = record_path_to_posix(file_path)
    for candidate in (base_dir / file_path, base_dir / "data" / file_path):
        if candidate.is_file():
            return candidate
    return None


def _migrate_embedded_records(
    payload: dict[str, Any],
    base_dir: Path,
    project_stem: str,
    notice: Notice | None,
) -> None:
    """Turn v1 embedded record series into catalog references, in place.

    Only migrates a series whose source is known with certainty (see
    module docstring). Idempotent: series that already carry a
    ``record_id`` are skipped.
    """

    def say(msg: str) -> None:
        if notice is not None:
            notice(msg)

    catalog: list[dict[str, Any]] = payload.setdefault("ground_motions", [])
    next_id = max((int(gm["id"]) for gm in catalog), default=0) + 1

    for ts in _path_series(payload):
        file_path = ts.get("file_path")
        if (
            ts.get("record_id") is not None
            or not ts.get("values")
            or not file_path
            or file_path.startswith("generated:")
        ):
            continue
        if ts.get("dt") is None:
            # Records are uniform-dt by definition; a times-based series
            # cannot be represented as one.
            say(f"Time series {ts.get('id')}: has no uniform dt, left embedded.")
            continue

        name = ts.get("name") or Path(file_path).stem
        resolved = _resolve_legacy_source(base_dir, file_path)

        if resolved is None:
            # Source unknown: keep the values in memory, write them out
            # as a sidecar at the next save (never during load).
            stem = sanitize_record_filename(name)
            catalog.append(
                {
                    "id": next_id,
                    "name": name,
                    "source_path": f"{project_stem}{SIDECAR_DIR_SUFFIX}/{stem}.txt",
                    "content_hash": "",
                    "format": "single_column",
                    "dt": ts["dt"],
                    "npts": len(ts["values"]),
                    "accel_units": "unknown",
                    "source_note": f"Migrated from embedded time series {ts.get('id')} "
                    f"(original source '{file_path}' not found).",
                    "status": "pending_sidecar",
                    "total_duration": (len(ts["values"]) - 1) * ts["dt"],
                }
            )
            ts["record_id"] = next_id
            next_id += 1
            say(
                f"Ground motion '{name}': source file '{file_path}' not found; "
                "its values will be written to a sidecar file at the next save."
            )
            continue

        fmt = detect_format(resolved)
        file_dt, file_values, _fields = read_record(resolved, fmt, dt=ts["dt"])
        if abs(file_dt - ts["dt"]) > _MIGRATION_RTOL * max(file_dt, ts["dt"]):
            raise ValueError(
                f"Ground-motion migration stopped: time series {ts.get('id')} "
                f"('{name}') has dt={ts['dt']} but its source file "
                f"'{resolved.name}' declares dt={file_dt}. Resolve the "
                "disagreement before migrating this project."
            )
        embedded = np.asarray(ts["values"], dtype=float)
        if file_values.size != embedded.size or not np.allclose(
            file_values, embedded, rtol=_MIGRATION_RTOL, atol=0.0
        ):
            say(
                f"Ground motion '{name}': file '{resolved.name}' does not match "
                "the embedded values; left embedded."
            )
            continue

        rel = Path(os.path.relpath(resolved, base_dir)).as_posix()
        catalog.append(
            {
                "id": next_id,
                "name": name,
                "source_path": rel,
                "content_hash": content_hash_of_file(resolved),
                "format": fmt,
                "dt": ts["dt"],
                "npts": int(file_values.size),
                "accel_units": "unknown",
                "source_note": f"Migrated from embedded time series {ts.get('id')}.",
                "status": "ok",
                "total_duration": (int(file_values.size) - 1) * ts["dt"],
            }
        )
        ts["record_id"] = next_id
        next_id += 1
        say(f"Ground motion '{name}': migrated to catalog reference '{rel}'.")

    if not catalog:
        # Don't force an empty list into every old payload we touched.
        payload.pop("ground_motions", None)


def _normalize_record_paths(payload: dict[str, Any]) -> None:
    """Forward slashes in every catalog ``source_path``, in place.

    Projects saved on Windows before paths were normalised carry
    backslashes; hydration resolves the raw payload, so this runs first.
    """
    for gm in payload.get("ground_motions", []):
        if isinstance(gm, dict) and isinstance(gm.get("source_path"), str):
            gm["source_path"] = record_path_to_posix(gm["source_path"])


def _hydrate_record_backed_series(
    payload: dict[str, Any],
    base_dir: Path,
    notice: Notice | None,
) -> None:
    """Fill ``values`` of record-backed series from their files, in place.

    Flags the catalog entry (``missing`` / ``hash_mismatch``) instead of
    raising, so a project with a lost record still opens.
    """

    def say(msg: str) -> None:
        if notice is not None:
            notice(msg)

    gm_by_id = {gm["id"]: gm for gm in payload.get("ground_motions", [])}

    for ts in _path_series(payload):
        rec_id = ts.get("record_id")
        if rec_id is None:
            continue
        rec = gm_by_id.get(rec_id)
        if rec is None:
            raise ValueError(
                f"Time series {ts.get('id')} references ground-motion record "
                f"{rec_id}, which is not in the catalog."
            )
        if rec.get("status") == "pending_sidecar":
            continue  # values are still embedded in the payload
        src = base_dir / rec["source_path"]
        if not src.is_file():
            rec["status"] = "missing"
            ts["values"] = []
            say(f"Ground motion '{rec.get('name')}': file not found at '{src}'.")
            continue
        if content_hash_of_file(src) != rec.get("content_hash"):
            rec["status"] = "hash_mismatch"
            ts["values"] = []
            say(
                f"Ground motion '{rec.get('name')}': '{src}' changed on disk "
                "since it was catalogued (hash mismatch)."
            )
            continue
        _dt, values, _fields = read_record(src, rec["format"], dt=rec["dt"])
        ts["values"] = [float(v) for v in values]
        rec["status"] = "ok"


def _write_pending_sidecars(
    project: Project,
    target: Path,
    notice: Notice | None,
) -> None:
    """Write ``pending_sidecar`` values to disk and heal their entries.

    Full float precision (``repr``), one value per line — the
    ``single_column`` reader parses it back bit-identically. Never
    overwrites a file with different content: a numbered suffix is
    appended instead.
    """
    pending = [gm for gm in project.ground_motions if gm.status == "pending_sidecar"]
    if not pending:
        return

    folder = target.parent / f"{target.stem}{SIDECAR_DIR_SUFFIX}"
    written: list[str] = []
    for rec in pending:
        ts = next(
            (
                t
                for t in project.time_series
                if getattr(t, "record_id", None) == rec.id and t.values
            ),
            None,
        )
        if ts is None:
            continue  # nothing in memory to write; stays pending
        folder.mkdir(parents=True, exist_ok=True)
        content = ("\n".join(repr(float(v)) for v in ts.values) + "\n").encode("ascii")

        stem = sanitize_record_filename(rec.name or f"record-{rec.id}")
        final = None
        for i in range(1, 1000):
            candidate = folder / (f"{stem}.txt" if i == 1 else f"{stem}_{i}.txt")
            if not candidate.exists():
                candidate.write_bytes(content)
                final = candidate
                break
            if candidate.read_bytes() == content:
                final = candidate  # identical content: reuse
                break
        if final is None:  # pragma: no cover - 999 conflicting sidecars
            raise RuntimeError(f"Could not find a free sidecar name for '{stem}' in {folder}.")

        rec.source_path = f"{folder.name}/{final.name}"
        rec.content_hash = content_hash_of_bytes(content)
        rec.status = "ok"
        written.append(final.name)

    if written and notice is not None:
        notice(f"Ground motions written to {folder.name}: {', '.join(written)}")


def _is_absolute_source(source_path: str) -> bool:
    return PurePosixPath(source_path).is_absolute() or PureWindowsPath(source_path).is_absolute()


def _reanchor_absolute_paths(project: Project, target: Path, notice: Notice | None) -> None:
    """Make absolute ``source_path`` entries relative to the project file.

    A record imported into a never-saved project has no anchor and is
    stored with its absolute path; the first save turns it into the
    normal relative reference. A path that cannot be expressed relative
    to the project (another drive on Windows) stays absolute and is
    named in the notice.
    """
    base = target.parent.resolve()
    made_relative: list[str] = []
    kept_absolute: list[str] = []
    for rec in project.ground_motions:
        if not _is_absolute_source(rec.source_path):
            continue
        try:
            rel = os.path.relpath(Path(rec.source_path), base)
        except ValueError:
            kept_absolute.append(rec.name or str(rec.id))
            continue
        rec.source_path = Path(rel).as_posix()
        made_relative.append(rec.name or str(rec.id))
    if notice is None:
        return
    if made_relative:
        notice(f"Ground-motion paths made relative to {target.name}: {', '.join(made_relative)}")
    if kept_absolute:
        notice(
            f"Ground-motion paths kept absolute (not on the drive of {target.name}): "
            f"{', '.join(kept_absolute)}"
        )


def save_project(
    project: Project,
    path: str | Path,
    on_notice: Notice | None = None,
) -> Path:
    """Serialize ``project`` to disk as indented JSON.

    Args:
        project: The project to save.
        path: Destination path. The ``.osmodel`` suffix is appended if missing.
        on_notice: Optional sink for one-line messages (sidecar writes).

    Returns:
        The resolved path actually written.
    """
    target = Path(path)
    if target.suffix != PROJECT_FILE_SUFFIX:
        target = target.with_suffix(PROJECT_FILE_SUFFIX)
    target.parent.mkdir(parents=True, exist_ok=True)

    _reanchor_absolute_paths(project, target, on_notice)
    _write_pending_sidecars(project, target, on_notice)

    target.write_text(_project_json(project), encoding="utf-8")
    return target


def _project_json(project: Project) -> str:
    """Serialize ``project`` the way ``save_project`` writes it, without touching disk.

    Record-backed series whose catalog entry is ``ok`` drop their values
    (they are re-read from the record file on load); ``pending_sidecar``
    entries keep theirs embedded.
    """
    payload = project.model_dump(mode="json", by_alias=True)
    payload["schema_version"] = SCHEMA_VERSION

    gm_status = {gm.id: gm.status for gm in project.ground_motions}
    for ts in _path_series(payload):
        rec_id = ts.get("record_id")
        if rec_id is not None and gm_status.get(rec_id) == "ok":
            del ts["values"]

    return json.dumps(payload, indent=2, ensure_ascii=False)


# ─────────────────────── pre-run snapshot ───────────────────────
RUN_SNAPSHOT_SUFFIX = ".run-snapshot" + PROJECT_FILE_SUFFIX
"""``<stem>.run-snapshot.osmodel`` next to the project file."""

UNTITLED_SNAPSHOT_STEM = "untitled"
"""Stem of the snapshot of a never-saved project (kept in the app data directory)."""

DATA_DIR_ENV = "OPENSEES_STUDIO_DATA_DIR"
"""Environment override for the app data directory (tests point it at a temp dir)."""


def app_data_dir() -> Path:
    """Per-user data directory of the application.

    ``OPENSEES_STUDIO_DATA_DIR`` wins when set. Otherwise the platform
    convention: ``%LOCALAPPDATA%`` on Windows, ``~/Library/Application Support``
    on macOS, ``$XDG_DATA_HOME`` (default ``~/.local/share``) elsewhere.
    """
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override)
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return base / "OpenSees Studio"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OpenSees Studio"
    base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "opensees-studio"


def run_snapshot_path(project_path: str | Path | None) -> Path:
    """Where the pre-run snapshot of a project lives.

    Next to the project file as ``<stem>.run-snapshot.osmodel`` so relative
    record paths resolve exactly as they do for the project itself; for a
    never-saved project, ``untitled.run-snapshot.osmodel`` in the app data
    directory.
    """
    if project_path is None:
        return app_data_dir() / f"{UNTITLED_SNAPSHOT_STEM}{RUN_SNAPSHOT_SUFFIX}"
    target = Path(project_path)
    return target.parent / f"{target.stem}{RUN_SNAPSHOT_SUFFIX}"


def write_run_snapshot(project: Project, project_path: str | Path | None) -> Path:
    """Write the crash-recovery snapshot of ``project`` atomically.

    The content is what ``save_project`` would write, but the project is
    not mutated (no re-anchoring, no sidecar writes) and the user's own
    project file is never touched. The JSON goes to a temporary file in
    the same directory which is then renamed over the snapshot, so a
    crash mid-write leaves either the previous snapshot or none.
    """
    target = run_snapshot_path(project_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    tmp.write_text(_project_json(project), encoding="utf-8")
    os.replace(tmp, target)
    return target


def newer_run_snapshot(project_path: str | Path) -> Path | None:
    """The snapshot of ``project_path`` if it exists and is newer than the project file."""
    src = Path(project_path)
    snapshot = run_snapshot_path(src)
    if not snapshot.is_file():
        return None
    if src.is_file() and snapshot.stat().st_mtime <= src.stat().st_mtime:
        return None
    return snapshot


def discard_run_snapshot(project_path: str | Path | None) -> bool:
    """Delete the snapshot of ``project_path`` if there is one. Returns True when a file went."""
    snapshot = run_snapshot_path(project_path)
    if snapshot.is_file():
        snapshot.unlink()
        return True
    return False


def load_project(path: str | Path, on_notice: Notice | None = None) -> Project:
    """Load and validate a project from disk.

    Args:
        path: Path to a ``.osmodel`` file.
        on_notice: Optional sink for one-line messages (legacy record
            migration, missing or changed record files).

    Returns:
        A fully validated :class:`Project`.

    Raises:
        FileNotFoundError: if the path does not exist.
        pydantic.ValidationError: if the file is structurally invalid.
        ValueError: re-raised from upstream invariants (ndm/ndf, duplicate
            ids), or a ground-motion migration conflict (dt disagreement,
            record referencing a non-existent catalog entry).
    """
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"Project file not found: {src}")
    payload = json.loads(src.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        _normalize_record_paths(payload)
        _migrate_embedded_records(payload, src.parent, src.stem, on_notice)
        _hydrate_record_backed_series(payload, src.parent, on_notice)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", UserWarning)
        project = Project.model_validate(payload)
    for w in caught:
        # Model validators warn about stored values they had to replace (for
        # example an eigen solver name this build does not offer).
        if on_notice is not None:
            on_notice(str(w.message))
        else:
            warnings.warn(w.message, w.category, stacklevel=2)
    return project
