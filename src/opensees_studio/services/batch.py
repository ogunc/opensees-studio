"""Batch analysis: run many projects unattended and keep their results.

Shared by the batch CLI (``python -m opensees_studio.batch``) and File → Run
Batch…. Each project is one *job*: the analysis CLI (``opensees_studio.run``,
spawned through :func:`~opensees_studio.child_cli.analysis_cli_command`) runs
the chosen cases of the project file itself and writes

- ``<stem>_batch_results/``: the HDF5 store and ``manifest.json``
  (:mod:`~opensees_studio.services.result_store`), plus :data:`STORED_NAME`,
  written here once the child succeeded, with the model fingerprint the results
  belong to;
- ``<stem>_results.sqlite``: the queryable results database
  (:mod:`~opensees_studio.services.results_db`, through ``--record-db``).

Opening the project later finds the store with :func:`stored_results` and
offers to show the results without solving again — only while the model still
has the fingerprint they were computed on.

No Qt and no OpenSeesPy here: the solver only ever runs in the child.
"""

from __future__ import annotations

import csv
import json
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opensees_studio.child_cli import analysis_cli_command
from opensees_studio.core.combinations import model_fingerprint
from opensees_studio.services.persistence import (
    PROJECT_FILE_SUFFIX,
    RUN_SNAPSHOT_SUFFIX,
    load_project,
)
from opensees_studio.services.result_store import MANIFEST_NAME, load_manifest
from opensees_studio.services.results_db import database_path

#: Folder beside ``model.osmodel`` that holds a batch's result store.
RESULTS_DIR_SUFFIX = "_batch_results"

#: Written into the result folder once every case of the job ran.
STORED_NAME = "batch.json"

#: The analysis child's stderr (OpenSees' own output), kept in the result folder.
STDERR_LOG = "analysis.stderr.log"

#: What a ``--cases`` selector of every case looks like.
ALL_CASES = "all"

#: Outcome statuses.
OK, FAILED, SKIPPED, CANCELLED = "ok", "failed", "skipped", "cancelled"

#: Columns of the CSV summary, in order.
SUMMARY_FIELDS = ("project", "status", "seconds", "cases", "exit_code", "message", "results_dir")


@dataclass
class BatchJob:
    """One project of a batch, planned: what runs and where it goes."""

    project: Path
    case_ids: list[int] = field(default_factory=list)
    case_names: list[str] = field(default_factory=list)
    fingerprint: str = ""
    #: Why the job cannot run (unreadable file, no matching case); "" when it can.
    error: str = ""

    @property
    def out_dir(self) -> Path:
        return results_dir_for(self.project)

    @property
    def db_path(self) -> Path:
        return database_path(self.project)


@dataclass
class BatchOutcome:
    """How one job ended, one row of the summary."""

    project: str
    status: str
    seconds: float = 0.0
    cases: list[str] = field(default_factory=list)
    exit_code: int | None = None
    message: str = ""
    results_dir: str = ""


def results_dir_for(project_path: str | Path) -> Path:
    """``model.osmodel`` → ``model_batch_results/`` beside it."""
    path = Path(project_path)
    return path.parent / f"{path.stem}{RESULTS_DIR_SUFFIX}"


# ─────────────────────────── planning ───────────────────────────
def expand_inputs(paths: Iterable[str | Path]) -> list[Path]:
    """Project files named by ``paths``: files as given, folders by their ``*.osmodel``.

    A folder is not searched recursively. Pre-run snapshots are left out, and a
    file named twice runs once, in the order first given.
    """
    found: list[Path] = []
    seen: set[Path] = set()
    for raw in paths:
        path = Path(raw).expanduser()
        candidates = sorted(path.glob(f"*{PROJECT_FILE_SUFFIX}")) if path.is_dir() else [path]
        for candidate in candidates:
            if candidate.name.endswith(RUN_SNAPSHOT_SUFFIX):
                continue
            key = candidate.resolve()
            if key not in seen:
                seen.add(key)
                found.append(candidate)
    return found


def parse_case_selector(text: str) -> list[str] | None:
    """``"all"`` (or empty) → None; otherwise the comma-separated case names or ids."""
    if text.strip().lower() in {"", ALL_CASES}:
        return None
    return [part.strip() for part in text.split(",") if part.strip()]


def select_cases(analyses: Iterable[Any], selector: list[str] | None) -> list[Any]:
    """The cases ``selector`` names, in the project's order.

    ``None`` takes every case. A selector entry matches a case by its name
    (ignoring case and surrounding spaces) or by its id written as a number.
    """
    cases = list(analyses)
    if selector is None:
        return cases
    names = {s.strip().casefold() for s in selector}
    return [c for c in cases if (c.name or "").strip().casefold() in names or str(c.id) in names]


def plan_job(project_path: str | Path, selector: list[str] | None) -> BatchJob:
    """Read ``project_path`` and decide which of its cases run."""
    path = Path(project_path)
    job = BatchJob(project=path)
    if not path.is_file():
        job.error = "File not found."
        return job
    try:
        project = load_project(path)
        project.validate_references()
    except Exception as exc:
        job.error = f"Cannot read the project: {exc}"
        return job
    cases = select_cases(project.analyses, selector)
    if not cases:
        job.error = (
            "The project has no analysis case."
            if selector is None
            else f"No case named {', '.join(selector)}."
        )
        return job
    job.case_ids = [c.id for c in cases]
    job.case_names = [c.name or f"#{c.id}" for c in cases]
    job.fingerprint = model_fingerprint(project)
    return job


def plan_batch(paths: Iterable[str | Path], selector: list[str] | None) -> list[BatchJob]:
    """One planned job per project file of ``paths`` (see :func:`expand_inputs`)."""
    return [plan_job(path, selector) for path in expand_inputs(paths)]


def job_arguments(job: BatchJob) -> list[str]:
    """Arguments of the analysis CLI for ``job``, after the program prefix."""
    return [
        "--project",
        str(job.project),
        "--cases",
        *(str(cid) for cid in job.case_ids),
        "--out",
        str(job.out_dir),
        "--record-db",
        str(job.db_path),
    ]


def job_command(job: BatchJob) -> list[str]:
    """Full argv of the analysis child for ``job``."""
    return [*analysis_cli_command(), *job_arguments(job)]


# ─────────────────────────── one job ───────────────────────────
def prepare_out_dir(job: BatchJob) -> None:
    """Create the job's result folder and drop the previous run's manifest and marker.

    A run that fails part-way must not leave the previous results looking current.
    """
    job.out_dir.mkdir(parents=True, exist_ok=True)
    for name in (MANIFEST_NAME, STORED_NAME):
        (job.out_dir / name).unlink(missing_ok=True)


def mark_stored(job: BatchJob, engine: str = "") -> Path:
    """Record that ``job``'s results are complete and which model they belong to."""
    target = job.out_dir / STORED_NAME
    payload = {
        "project": str(job.project),
        "fingerprint": job.fingerprint,
        "cases": job.case_ids,
        "engine": engine,
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def finish_job(
    job: BatchJob, exit_code: int, last_error: str, *, cancelled: bool, engine: str = ""
) -> tuple[str, str]:
    """``(status, message)`` of a job whose child exited, marking its results stored.

    An exit 0 is a finished job even when Cancel came at the same moment: its
    results are complete. Anything else after a Cancel is cancelled.
    """
    if exit_code == 0:
        mark_stored(job, engine=engine)
        return OK, ""
    if cancelled:
        return CANCELLED, ""
    try:
        tail = (job.out_dir / STDERR_LOG).read_text(encoding="utf-8", errors="replace")[-4000:]
    except OSError:
        tail = ""
    return FAILED, failure_message(exit_code, last_error, tail)


def failure_message(exit_code: int | None, last_error: str, stderr_tail: str = "") -> str:
    """One line saying why a job failed."""
    if last_error:
        return last_error
    if exit_code is None:
        return "The analysis process could not be started."
    tail = [line for line in stderr_tail.splitlines() if line.strip()]
    hint = f" Last output: {tail[-1].strip()}" if tail else ""
    return f"The analysis process died (exit code {exit_code}).{hint}"


def parse_line(line: str) -> dict[str, Any] | None:
    """A protocol line of the analysis CLI as a dict; None for anything else."""
    line = line.strip()
    if not line:
        return None
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


class Stopwatch:
    """Seconds since construction (monotonic)."""

    def __init__(self) -> None:
        self._start = time.monotonic()

    def seconds(self) -> float:
        return round(time.monotonic() - self._start, 3)


# ─────────────────────────── summary ───────────────────────────
def skipped_outcome(job: BatchJob) -> BatchOutcome:
    return BatchOutcome(project=str(job.project), status=SKIPPED, message=job.error)


def summary_counts(outcomes: Iterable[BatchOutcome]) -> dict[str, int]:
    """Number of outcomes per status, every status present."""
    counts = dict.fromkeys((OK, FAILED, SKIPPED, CANCELLED), 0)
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    return counts


def summary_payload(outcomes: list[BatchOutcome]) -> dict[str, Any]:
    return {
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "counts": summary_counts(outcomes),
        "jobs": [asdict(o) for o in outcomes],
    }


def write_summary(outcomes: list[BatchOutcome], stem: str | Path) -> tuple[Path, Path]:
    """Write ``<stem>.json`` and ``<stem>.csv``; return both paths."""
    base = Path(stem)
    if base.suffix.lower() in {".json", ".csv"}:
        base = base.with_suffix("")
    base.parent.mkdir(parents=True, exist_ok=True)
    json_path, csv_path = base.with_suffix(".json"), base.with_suffix(".csv")
    json_path.write_text(json.dumps(summary_payload(outcomes), indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for outcome in outcomes:
            row = asdict(outcome)
            row["cases"] = "; ".join(outcome.cases)
            writer.writerow({k: row[k] for k in SUMMARY_FIELDS})
    return json_path, csv_path


# ─────────────────────────── reopening ───────────────────────────
@dataclass
class StoredResults:
    """A batch's results found beside a project, still current for its model."""

    out_dir: Path
    entries: list[dict[str, Any]]
    finished_at: str


def stored_results(project_path: str | Path | None, project: Any) -> StoredResults | None:
    """The batch results of ``project_path`` when they belong to ``project`` as it is.

    None when there are none, the run did not finish, or the model changed
    since (its :func:`~opensees_studio.core.combinations.model_fingerprint`
    differs): those numbers would describe another model.
    """
    if project_path is None or project is None:
        return None
    out_dir = results_dir_for(project_path)
    try:
        marker = json.loads((out_dir / STORED_NAME).read_text(encoding="utf-8"))
        entries = list(load_manifest(out_dir).get("cases", []))
    except (OSError, ValueError, AttributeError):
        return None
    if not entries or marker.get("fingerprint") != model_fingerprint(project):
        return None
    return StoredResults(
        out_dir=out_dir, entries=entries, finished_at=str(marker.get("finished_at", ""))
    )
