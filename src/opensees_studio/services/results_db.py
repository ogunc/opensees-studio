"""Queryable results database written after every analysis run.

The in-memory containers in :mod:`opensees_studio.services.results` keep the
current run available to the GUI, and the HDF5 store keeps a transient series
losslessly. Neither is convenient to query a month later, which is what this is
for: one SQLite file per project, one row per node / element / step, indexed, so
a notebook, a spreadsheet or the ``sqlite3`` CLI can ask "what was the drift at
joint 12 in case 3" without loading the application.

Why SQLite and not CSV or JSON: a static case on a 500-joint model writes
thousands of rows and a time history writes millions. SQLite is a single file,
ships with Python, indexes the (run, node) and (run, element) lookups, and can
be opened by anything. It is also crash-safe: a failed write cannot leave a
half-parsed text file behind.

The file is **append-only history**: every run adds a row to ``runs`` and its
results carry that ``run_id``. Nothing is overwritten except by copying the
file, so re-running a case keeps the earlier numbers reachable.

Layout (schema version 1)::

    meta(key, value)                  schema and app version
    runs(run_id, case_id, case_name, case_type, kind, recorded_at, ...)
    node_disp(run_id, node_id, step, ux, uy, uz, rx, ry, rz)
    node_reaction(...)                same shape as node_disp
    element_forces(run_id, element_id, step, c1 .. c12)
    element_stresses(run_id, element_id, step, n11, n22, n12, m11, m22, m12, v13, v23)
    storey_shear(run_id, storey_id, step, s1, s2, s3)
    section_cut_forces(run_id, section_cut_id, step, fx, fy, fz, mx, my, mz)
    mode_shapes(run_id, mode, node_id, ux, uy, uz, rx, ry, rz)
    modal(run_id, mode, eigenvalue, period, frequency)

Every table is keyed by ``(run_id, ...)`` and indexed on the id columns, so a
query never scans the file end to end.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from opensees_studio.services.persistence import app_data_dir
from opensees_studio.services.results import (
    CombinationResults,
    ModalResults,
    PushoverResults,
    ResponseSpectrumResults,
    StaticResults,
    TransientResults,
)

#: Suffix of the results database, next to the project file.
DB_SUFFIX = "_results.sqlite"

#: Bumped when the schema changes in a way old files cannot be read with.
SCHEMA_VERSION = 2

#: Widest DOF set a node can carry (ndf = 6).
_NDF = 6

#: Longest local-force vector an element reports (a 3D frame: 12 components).
_MAX_FORCE_COMPONENTS = 12

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id      INTEGER,
    case_name    TEXT    NOT NULL DEFAULT '',
    case_type    TEXT    NOT NULL DEFAULT '',
    kind         TEXT    NOT NULL,
    recorded_at  TEXT    NOT NULL,
    project_path TEXT,
    n_steps      INTEGER,
    dt           REAL,
    h5_path      TEXT,
    notes        TEXT,
    dedupe_key   TEXT
);
CREATE TABLE IF NOT EXISTS node_disp (
    run_id INTEGER NOT NULL, node_id INTEGER NOT NULL, step INTEGER NOT NULL,
    ux REAL, uy REAL, uz REAL, rx REAL, ry REAL, rz REAL
);
CREATE TABLE IF NOT EXISTS node_reaction (
    run_id INTEGER NOT NULL, node_id INTEGER NOT NULL, step INTEGER NOT NULL,
    ux REAL, uy REAL, uz REAL, rx REAL, ry REAL, rz REAL
);
CREATE TABLE IF NOT EXISTS element_forces (
    run_id INTEGER NOT NULL, element_id INTEGER NOT NULL, step INTEGER NOT NULL,
    c1 REAL, c2 REAL, c3 REAL, c4 REAL, c5 REAL, c6 REAL,
    c7 REAL, c8 REAL, c9 REAL, c10 REAL, c11 REAL, c12 REAL
);
CREATE TABLE IF NOT EXISTS element_stresses (
    run_id INTEGER NOT NULL, element_id INTEGER NOT NULL, step INTEGER NOT NULL,
    n11 REAL, n22 REAL, n12 REAL, m11 REAL, m22 REAL, m12 REAL, v13 REAL, v23 REAL
);
CREATE TABLE IF NOT EXISTS storey_shear (
    run_id INTEGER NOT NULL, storey_id INTEGER NOT NULL, step INTEGER NOT NULL,
    s1 REAL, s2 REAL, s3 REAL
);
CREATE TABLE IF NOT EXISTS section_cut_forces (
    run_id INTEGER NOT NULL, section_cut_id INTEGER NOT NULL, step INTEGER NOT NULL,
    fx REAL, fy REAL, fz REAL, mx REAL, my REAL, mz REAL
);
CREATE TABLE IF NOT EXISTS mode_shapes (
    run_id INTEGER NOT NULL, mode INTEGER NOT NULL, node_id INTEGER NOT NULL,
    ux REAL, uy REAL, uz REAL, rx REAL, ry REAL, rz REAL
);
CREATE TABLE IF NOT EXISTS modal (
    run_id INTEGER NOT NULL, mode INTEGER NOT NULL,
    eigenvalue REAL, period REAL, frequency REAL
);
CREATE INDEX IF NOT EXISTS idx_node_disp       ON node_disp(run_id, node_id);
CREATE INDEX IF NOT EXISTS idx_node_reaction   ON node_reaction(run_id, node_id);
CREATE INDEX IF NOT EXISTS idx_element_forces  ON element_forces(run_id, element_id);
CREATE INDEX IF NOT EXISTS idx_element_stresses ON element_stresses(run_id, element_id);
CREATE INDEX IF NOT EXISTS idx_storey_shear    ON storey_shear(run_id, storey_id);
CREATE INDEX IF NOT EXISTS idx_section_cut     ON section_cut_forces(run_id, section_cut_id);
CREATE INDEX IF NOT EXISTS idx_mode_shapes     ON mode_shapes(run_id, mode, node_id);
CREATE INDEX IF NOT EXISTS idx_modal           ON modal(run_id, mode);
CREATE INDEX IF NOT EXISTS idx_runs_case       ON runs(case_id, recorded_at);
"""


def database_path(project_path: str | Path | None) -> Path:
    """Where the results of ``project_path`` live.

    Beside the project file (``model.osmodel`` → ``model_results.sqlite``); a
    project that has never been saved writes to the application data directory,
    because it has no directory of its own yet.
    """
    if project_path is None:
        return app_data_dir() / f"untitled{DB_SUFFIX}"
    path = Path(project_path).expanduser()
    return path.parent / f"{path.stem}{DB_SUFFIX}"


def record_results(
    results: Any,
    *,
    project_path: str | Path | None = None,
    project: Any = None,
    db_path: str | Path | None = None,
) -> int | None:
    """Append ``results`` to the project's database and return the run id.

    ``project`` is only needed for a transient run, whose per-node histories
    live in HDF5 and are read back to be indexed. Returns ``None`` for a result
    kind this writer does not understand, so a new kind never breaks a run.
    """
    path = Path(db_path) if db_path is not None else database_path(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as con, con:
        _ensure_schema(con)
        if isinstance(results, CombinationResults):
            first = _record_static(
                con,
                results.max,
                project_path,
                kind="combination:max",
                dedupe_key=f"combination:{results.combination_id}:max",
            )
            _record_static(
                con,
                results.min,
                project_path,
                kind="combination:min",
                dedupe_key=f"combination:{results.combination_id}:min",
            )
            return first
        if isinstance(results, PushoverResults):
            return _record_pushover(con, results, project_path)
        if isinstance(results, StaticResults):
            return _record_static(con, results, project_path, kind="static")
        if isinstance(results, ModalResults):
            return _record_modal(con, results, project_path)
        if isinstance(results, ResponseSpectrumResults):
            return _record_spectrum(con, results, project_path)
        if isinstance(results, TransientResults):
            return _record_transient(con, results, project_path, project)
    return None


# ── schema ──────────────────────────────────────────────────────────
def _ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(_SCHEMA)
    # A file written by the first schema lacks dedupe_key; add it in place rather
    # than throwing the recorded results away.
    columns = {row[1] for row in con.execute("PRAGMA table_info(runs)")}
    if "dedupe_key" not in columns:
        con.execute("ALTER TABLE runs ADD COLUMN dedupe_key TEXT")
    con.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    con.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('written_by', 'OpenSees Studio')",
    )


def _delete_runs(con: sqlite3.Connection, run_ids: list[int]) -> None:
    """Remove ``run_ids`` and every result row that belongs to them."""
    for run_id in run_ids:
        for table in _RESULT_TABLES:
            con.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))
    con.executemany("DELETE FROM runs WHERE run_id = ?", [(run_id,) for run_id in run_ids])


def _delete_by_key(con: sqlite3.Connection, key: str) -> None:
    """Drop the run recorded under ``key`` (a case re-run replaces it)."""
    ids = [
        int(row[0]) for row in con.execute("SELECT run_id FROM runs WHERE dedupe_key = ?", (key,))
    ]
    _delete_runs(con, ids)


def delete_all_results(db_path: str | Path) -> bool:
    """Delete the results file. True when there was one to delete."""
    path = Path(db_path)
    if not path.exists():
        return False
    path.unlink()
    return True


def _insert_run(
    con: sqlite3.Connection,
    *,
    kind: str,
    case_id: int | None,
    case_name: str,
    case_type: str,
    project_path: str | Path | None,
    n_steps: int | None = None,
    dt: float | None = None,
    h5_path: str | Path | None = None,
    notes: str | None = None,
    dedupe_key: str | None = None,
) -> int:
    # Re-running a case replaces its previous rows: one run per dedupe key.
    if dedupe_key is not None:
        _delete_by_key(con, dedupe_key)
    cursor = con.execute(
        """
        INSERT INTO runs (case_id, case_name, case_type, kind, recorded_at,
                          project_path, n_steps, dt, h5_path, notes, dedupe_key)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            case_id,
            case_name,
            case_type,
            kind,
            datetime.now(UTC).isoformat(timespec="seconds"),
            None if project_path is None else str(project_path),
            n_steps,
            dt,
            None if h5_path is None else str(h5_path),
            notes,
            dedupe_key,
        ),
    )
    return int(cursor.lastrowid or 0)


# ── row helpers ─────────────────────────────────────────────────────
def _padded(vector: np.ndarray, width: int) -> list[float | None]:
    """``vector`` as ``width`` floats, padded with NULL (unknown DOF)."""
    values = [float(v) for v in np.asarray(vector, dtype=float).ravel()[:width]]
    return values + [None] * (width - len(values))


def _step_rows(
    run_id: int,
    values: dict[int, np.ndarray],
    width: int,
    steps: int | None,
) -> list[tuple[Any, ...]]:
    """``(run_id, entity_id, step, *components)`` for every entity and step."""
    rows: list[tuple[Any, ...]] = []
    for entity_id, array in values.items():
        data = np.asarray(array, dtype=float)
        if data.ndim == 1:
            data = data.reshape(1, -1)
        for step in range(len(data) if steps is None else min(steps, len(data))):
            rows.append((run_id, int(entity_id), step, *_padded(data[step], width)))
    return rows


def _write_rows(
    con: sqlite3.Connection,
    table: str,
    id_column: str,
    columns: list[str],
    rows: list[tuple[Any, ...]],
) -> None:
    """Insert ``rows`` as ``(run_id, <id_column>, step, *columns)``."""
    if not rows:
        return
    placeholders = ", ".join("?" * (3 + len(columns)))
    names = ", ".join(["run_id", id_column, "step", *columns])
    con.executemany(f"INSERT INTO {table} ({names}) VALUES ({placeholders})", rows)


# ── per-kind writers ────────────────────────────────────────────────
#: Every table keyed by run_id, for the replace and delete paths.
_RESULT_TABLES = (
    "node_disp",
    "node_reaction",
    "element_forces",
    "element_stresses",
    "storey_shear",
    "section_cut_forces",
    "mode_shapes",
    "modal",
)

_DOF_COLUMNS = ["ux", "uy", "uz", "rx", "ry", "rz"]
_FORCE_COLUMNS = [f"c{i}" for i in range(1, _MAX_FORCE_COMPONENTS + 1)]
_STRESS_COLUMNS = ["n11", "n22", "n12", "m11", "m22", "m12", "v13", "v23"]


def _write_static_bodies(con: sqlite3.Connection, run_id: int, results: Any, steps: int) -> None:
    """The node/element tables shared by static, pushover and spectrum results."""
    _write_rows(
        con,
        "node_disp",
        "node_id",
        _DOF_COLUMNS,
        _step_rows(run_id, getattr(results, "node_disp", {}), _NDF, steps),
    )
    _write_rows(
        con,
        "node_reaction",
        "node_id",
        _DOF_COLUMNS,
        _step_rows(run_id, getattr(results, "node_reaction", {}), _NDF, steps),
    )
    _write_rows(
        con,
        "element_forces",
        "element_id",
        _FORCE_COLUMNS,
        _step_rows(run_id, getattr(results, "element_forces", {}), _MAX_FORCE_COMPONENTS, steps),
    )
    _write_rows(
        con,
        "element_stresses",
        "element_id",
        _STRESS_COLUMNS,
        _step_rows(run_id, getattr(results, "element_stresses", {}), len(_STRESS_COLUMNS), steps),
    )
    storeys = getattr(results, "storey_shear", {})
    if storeys:
        _write_rows(
            con,
            "storey_shear",
            "storey_id",
            ["s1", "s2", "s3"],
            _step_rows(run_id, storeys, 3, steps),
        )
    cuts = getattr(results, "section_cut_forces", {})
    if cuts:
        _write_rows(
            con,
            "section_cut_forces",
            "section_cut_id",
            ["fx", "fy", "fz", "mx", "my", "mz"],
            _step_rows(run_id, cuts, 6, steps),
        )


def _record_static(
    con: sqlite3.Connection,
    results: StaticResults,
    project_path: str | Path | None,
    *,
    kind: str,
    dedupe_key: str | None = None,
) -> int:
    run_id = _insert_run(
        con,
        kind=kind,
        case_id=results.case_id,
        case_name=results.case_name,
        case_type="Static",
        project_path=project_path,
        n_steps=results.n_steps,
        dedupe_key=dedupe_key or f"case:{results.case_id}",
    )
    _write_static_bodies(con, run_id, results, results.n_steps)
    return run_id


def _record_pushover(
    con: sqlite3.Connection,
    results: PushoverResults,
    project_path: str | Path | None,
) -> int:
    steps = results.n_steps + 1  # the control arrays include t = 0
    run_id = _insert_run(
        con,
        kind="pushover",
        case_id=results.case_id,
        case_name=results.case_name,
        case_type="Pushover",
        project_path=project_path,
        n_steps=steps,
        notes=f"control node {results.control_node}, DOF {results.control_dof}",
        dedupe_key=f"case:{results.case_id}",
    )
    _write_static_bodies(con, run_id, results, steps)
    return run_id


def _record_modal(
    con: sqlite3.Connection,
    results: ModalResults,
    project_path: str | Path | None,
) -> int:
    n_modes = len(results.eigenvalues)
    run_id = _insert_run(
        con,
        kind="modal",
        case_id=results.case_id,
        case_name=results.case_name,
        case_type="Modal",
        project_path=project_path,
        n_steps=n_modes,
        notes=f"solver {results.solver}, {results.n_free_dof} free DOF",
        dedupe_key=f"case:{results.case_id}",
    )
    modal_rows = [
        (
            run_id,
            mode,
            float(results.eigenvalues[mode - 1]),
            float(results.periods[mode - 1]),
            float(results.frequencies[mode - 1]),
        )
        for mode in range(1, n_modes + 1)
    ]
    con.executemany(
        "INSERT INTO modal (run_id, mode, eigenvalue, period, frequency) VALUES (?, ?, ?, ?, ?)",
        modal_rows,
    )
    shape_rows: list[tuple[Any, ...]] = []
    for mode, nodes in results.mode_shapes.items():
        for node_id, vector in nodes.items():
            shape_rows.append((run_id, int(mode), int(node_id), *_padded(vector, _NDF)))
    con.executemany(
        "INSERT INTO mode_shapes (run_id, mode, node_id, ux, uy, uz, rx, ry, rz) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        shape_rows,
    )
    return run_id


def _record_spectrum(
    con: sqlite3.Connection,
    results: ResponseSpectrumResults,
    project_path: str | Path | None,
) -> int:
    run_id = _insert_run(
        con,
        kind="response_spectrum",
        case_id=results.case_id,
        case_name=results.case_name,
        case_type="ResponseSpectrum",
        project_path=project_path,
        n_steps=1,
        notes=(
            f"direction {results.direction}, {results.combination}, "
            f"{len(results.modes)} mode(s), solver {results.solver}"
        ),
        dedupe_key=f"case:{results.case_id}",
    )
    # The spectrum container names its peaks combined_disp; the shared writer
    # expects the static names, so hand it a shim. One pseudo-step: they are
    # peaks, not a history.
    peaks = SimpleNamespace(
        node_disp=results.combined_disp,
        node_reaction=results.node_reaction,
        element_forces=results.element_forces,
        element_stresses=results.element_stresses,
    )
    _write_static_bodies(con, run_id, peaks, steps=1)
    return run_id


def _record_transient(
    con: sqlite3.Connection,
    results: TransientResults,
    project_path: str | Path | None,
    project: Any,
) -> int:
    run_id = _insert_run(
        con,
        kind="transient",
        case_id=results.case_id,
        case_name=results.case_name,
        case_type="Transient",
        project_path=project_path,
        n_steps=results.n_steps,
        dt=results.dt,
        h5_path=results.h5_path,
        notes=results.steps_summary(),
        dedupe_key=f"case:{results.case_id}",
    )
    # The displacement history is the one series worth indexing; the lossless
    # copy (velocity, acceleration, element state) stays in the HDF5 file.
    if project is not None:
        rows: list[tuple[Any, ...]] = []
        for node in getattr(project, "nodes", []):
            try:
                history = results.node_disp_history(int(node.id))
            except Exception:  # a node with no recorded history
                continue
            for step in range(len(history)):
                rows.append((run_id, int(node.id), step, *_padded(history[step], _NDF)))
        con.executemany(
            "INSERT INTO node_disp (run_id, node_id, step, ux, uy, uz, rx, ry, rz) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return run_id


# ── read side (used by the tests and by future viewers) ─────────────
def read_runs(db_path: str | Path) -> list[sqlite3.Row]:
    """Every recorded run, newest last. Empty when the file does not exist."""
    path = Path(db_path)
    if not path.exists():
        return []
    with closing(sqlite3.connect(path)) as con, con:
        con.row_factory = sqlite3.Row
        return list(con.execute("SELECT * FROM runs ORDER BY run_id"))


def count_rows(db_path: str | Path, table: str) -> int:
    """Row count of ``table`` (a diagnostic, and what the tests assert on)."""
    with closing(sqlite3.connect(Path(db_path))) as con, con:
        return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
