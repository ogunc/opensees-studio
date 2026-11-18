"""Batch CLI: ``python -m opensees_studio.batch FILE_OR_FOLDER ... [--cases all] [--jobs N]``.

Runs the chosen cases of many projects unattended, each in its own analysis
child (``opensees_studio.run``, through
:func:`~opensees_studio.child_cli.analysis_cli_command`), up to ``--jobs`` at a
time. Every project keeps its results beside it (``<stem>_batch_results/`` and
``<stem>_results.sqlite``, see :mod:`opensees_studio.services.batch`), so
opening it later shows them without solving again.

Prints one line per finished project and writes the summary to
``<summary>.json`` and ``<summary>.csv`` (default ``batch_summary`` in the
current folder). Exit code 0 when every project ran, 1 when any failed or was
skipped, 2 for a bad command line (an unknown ``--engine``).

The engine is the one chosen in Options → Solver unless ``--engine`` names
another; each child gets it in ``OPENSEES_STUDIO_ENGINE`` and the OpenSeesPy
folder in ``OPENSEES_STUDIO_ENGINE_PATH`` exactly as a run from the GUI does.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from opensees_studio.services import batch
from opensees_studio.services.batch import BatchJob, BatchOutcome
from opensees_studio.services.engines import ENGINE_KEY_ENV

EXIT_ALL_OK = 0
EXIT_SOME_FAILED = 1
EXIT_USAGE = 2


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m opensees_studio.batch",
        description="Run the analysis cases of many OpenSees Studio projects and keep the results.",
    )
    parser.add_argument("inputs", nargs="+", help=".osmodel files or folders holding them")
    parser.add_argument(
        "--cases",
        default="all",
        help="'all' (default) or comma-separated case names or ids, e.g. 'Dead,Modal'",
    )
    parser.add_argument(
        "--jobs", type=int, default=1, help="projects solved at the same time (default 1)"
    )
    parser.add_argument(
        "--engine", default=None, help="engine key (default: the one chosen in Options → Solver)"
    )
    parser.add_argument(
        "--summary",
        default="batch_summary",
        help="summary path without extension: writes .json and .csv (default batch_summary)",
    )
    return parser.parse_args(argv)


def _child_env(engine_key: str | None) -> dict[str, str] | None:
    """The children's environment, None when ``engine_key`` is not an installed engine."""
    from opensees_studio.services import engines

    settings = engines.load_settings()
    if engine_key is not None:
        if engine_key not in engines.engines():
            return None
        settings = replace(settings, engine=engine_key)
    return {**os.environ, "PYTHONUNBUFFERED": "1", **engines.child_environment(settings)}


class _Batch:
    """Runs jobs on a thread pool, one subprocess each; Ctrl+C kills them all."""

    def __init__(self, env: dict[str, str]) -> None:
        self._env = env
        self._lock = threading.Lock()
        self._live: set[subprocess.Popen[str]] = set()
        self.cancelled = False

    def run_job(self, job: BatchJob) -> BatchOutcome:
        clock = batch.Stopwatch()
        outcome = BatchOutcome(
            project=str(job.project),
            status=batch.FAILED,
            cases=list(job.case_names),
            results_dir=str(job.out_dir),
        )
        if self.cancelled:
            outcome.status = batch.CANCELLED
            return outcome
        last_error = ""
        try:
            batch.prepare_out_dir(job)
            stderr_path = job.out_dir / batch.STDERR_LOG
            with stderr_path.open("w", encoding="utf-8", errors="replace") as stderr:
                child = subprocess.Popen(
                    batch.job_command(job),
                    stdout=subprocess.PIPE,
                    stderr=stderr,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=self._env,
                )
                with self._lock:
                    self._live.add(child)
                assert child.stdout is not None
                for line in child.stdout:
                    payload = batch.parse_line(line)
                    if payload is not None and payload.get("type") == "error":
                        last_error = str(payload.get("message", ""))
                code = child.wait()
                with self._lock:
                    self._live.discard(child)
        except OSError as exc:
            outcome.message = str(exc)
            outcome.seconds = clock.seconds()
            return outcome
        outcome.exit_code = code
        outcome.seconds = clock.seconds()
        outcome.status, outcome.message = batch.finish_job(
            job,
            code,
            last_error,
            cancelled=self.cancelled,
            engine=self._env.get(ENGINE_KEY_ENV, ""),
        )
        return outcome

    def cancel(self) -> None:
        self.cancelled = True
        with self._lock:
            for child in self._live:
                child.kill()


def _report(outcome: BatchOutcome) -> None:
    detail = f"  {outcome.message}" if outcome.message else ""
    print(f"[{outcome.status:>9}] {outcome.seconds:8.2f} s  {outcome.project}{detail}", flush=True)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    env = _child_env(args.engine)
    if env is None:
        print(f"Unknown engine '{args.engine}'.", file=sys.stderr)
        return EXIT_USAGE
    jobs = batch.plan_batch(args.inputs, batch.parse_case_selector(args.cases))
    if not jobs:
        print("No project files found.", file=sys.stderr)
        return EXIT_SOME_FAILED
    print(f"Batch: {len(jobs)} project(s), {max(1, args.jobs)} at a time.", flush=True)

    runner = _Batch(env)
    results: dict[int, BatchOutcome] = {}
    runnable = []
    for index, job in enumerate(jobs):
        if job.error:
            results[index] = batch.skipped_outcome(job)
            _report(results[index])
        else:
            runnable.append((index, job))
    pool = ThreadPoolExecutor(max_workers=max(1, args.jobs))
    futures = {index: pool.submit(runner.run_job, job) for index, job in runnable}
    try:
        for index, future in futures.items():
            results[index] = future.result()
            _report(results[index])
    except KeyboardInterrupt:
        runner.cancel()
        print("Cancelled: stopping the running analyses.", file=sys.stderr, flush=True)
        for index, future in futures.items():
            if index not in results:
                results[index] = future.result()
    finally:
        pool.shutdown(wait=True)

    outcomes = [results[i] for i in range(len(jobs))]
    json_path, csv_path = batch.write_summary(outcomes, Path(args.summary))
    counts = batch.summary_counts(outcomes)
    print(
        ", ".join(f"{n} {status}" for status, n in counts.items() if n)
        + f". Summary: {json_path}, {csv_path}",
        flush=True,
    )
    return EXIT_ALL_OK if counts[batch.OK] == len(outcomes) else EXIT_SOME_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
