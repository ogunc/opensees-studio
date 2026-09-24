"""Analysis CLI: ``python -m opensees_studio.run --project P --cases IDS --out DIR``.

The GUI runs every analysis through this entry point in a child process
(``QProcess``), so a hard exit inside OpenSees cannot take the
application down. The script loads the project (normally the pre-run
snapshot), runs the requested cases with the ordinary
:class:`~opensees_studio.services.opensees_runner.OpenSeesRunner`, writes
each case's results to ``DIR`` through
:mod:`~opensees_studio.services.result_store` and finishes with
``DIR/manifest.json``.

Progress protocol (stdout, one JSON object per line, flushed per line):

- ``{"type": "log", "message": str}``
- ``{"type": "case_started", "case_id": int, "case_type": str, "case_name": str}``
- ``{"type": "progress", "case_id": int, "step": int, "total": int}``
- ``{"type": "case_finished", "case_id": int, "result_type": str, "files": [...],
  "completed_steps": int | null, "early_stop": bool, "warnings": [...]}``
- ``{"type": "error", "message": str, "traceback": str}``

Everything OpenSees itself prints goes to stderr: file descriptor 1 is
redirected to 2 right at start and the protocol writes to a private copy
of the original stdout, so native output can never corrupt a line.

Exit codes:

- 0: every case ran (an early stop is a result, not an error);
- 2: a Python-side analysis error, reported in an ``error`` line;
- 3: the project is invalid or a reference does not resolve;
- anything else: the process died (a hard exit inside OpenSees, a signal).

``OPENSEES_STUDIO_CLI_HARD_EXIT_AFTER=N`` (tests only) makes the process
leave with ``os._exit(255)`` after the N-th progress line, imitating a
solver hard exit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_ANALYSIS_ERROR = 2
EXIT_INVALID_PROJECT = 3
HARD_EXIT_ENV = "OPENSEES_STUDIO_CLI_HARD_EXIT_AFTER"


class _Protocol:
    """Writes protocol lines to the original stdout, one JSON object per line."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self.progress_lines = 0
        limit = os.environ.get(HARD_EXIT_ENV)
        self._hard_exit_after = int(limit) if limit else None

    def emit(self, **payload: Any) -> None:
        self._stream.write(json.dumps(payload) + "\n")
        self._stream.flush()
        if payload.get("type") == "progress":
            self.progress_lines += 1
            if self._hard_exit_after is not None and self.progress_lines >= self._hard_exit_after:
                self._stream.flush()
                os._exit(255)

    def log(self, message: str) -> None:
        self.emit(type="log", message=message)


def _claim_stdout() -> Any:
    """Return a private text stream on the original stdout and send fd 1 to stderr."""
    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    stream = os.fdopen(protocol_fd, "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr
    return stream


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m opensees_studio.run",
        description="Run analysis cases of an OpenSees Studio project and write the results.",
    )
    parser.add_argument(
        "--project", required=True, help="project file (.osmodel), usually the pre-run snapshot"
    )
    parser.add_argument(
        "--cases",
        required=True,
        type=int,
        nargs="+",
        metavar="ID",
        help="case ids to run, in order",
    )
    parser.add_argument(
        "--out", required=True, help="output directory for results and manifest.json"
    )
    parser.add_argument(
        "--case-override",
        default=None,
        help="JSON file with a list of case objects that replace the same-id cases for this run",
    )
    return parser.parse_args(argv)


def _throttled(protocol: _Protocol, case_id: int) -> Any:
    """Progress callback emitting at most about 100 lines per case plus the last step."""
    last_emitted = {"step": -1}

    def on_progress(step: int, total: int) -> None:
        stride = max(1, total // 100)
        if (step == total or step % stride == 0) and step != last_emitted["step"]:
            last_emitted["step"] = step
            protocol.emit(type="progress", case_id=case_id, step=step, total=total)

    return on_progress


def main(argv: list[str] | None = None) -> int:
    protocol = _Protocol(_claim_stdout())
    args = _parse_args(argv)

    from opensees_studio.core import Project
    from opensees_studio.services.persistence import load_project
    from opensees_studio.services.result_store import write_manifest, write_results

    out_dir = Path(args.out)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        project = load_project(args.project, on_notice=protocol.log)
        if args.case_override:
            overrides = json.loads(Path(args.case_override).read_text(encoding="utf-8"))
            by_id = {int(c["id"]): c for c in overrides}
            analyses = [by_id.get(c.id, c) for c in project.analyses]
            project = Project.model_validate(
                {
                    **project.model_dump(mode="json", by_alias=True),
                    "analyses": [
                        a if isinstance(a, dict) else a.model_dump(mode="json", by_alias=True)
                        for a in analyses
                    ],
                }
            )
        project.validate_references()
        cases = []
        for cid in args.cases:
            case = next((c for c in project.analyses if c.id == cid), None)
            if case is None:
                raise ValueError(f"No analysis case with id {cid} in the project.")
            cases.append(case)
    except Exception as exc:
        protocol.emit(type="error", message=str(exc), traceback=traceback.format_exc())
        return EXIT_INVALID_PROJECT

    from opensees_studio.services.opensees_runner import OpenSeesRunner

    entries: list[dict[str, Any]] = []
    protocol.log(f"Building model: {len(project.nodes)} nodes, {len(project.elements)} elements.")
    for case in cases:
        protocol.emit(
            type="case_started", case_id=case.id, case_type=type(case).__name__, case_name=case.name
        )
        protocol.log(f"Running case '{case.name}' ({type(case).__name__}) ...")
        try:
            runner = OpenSeesRunner(project, on_progress=_throttled(protocol, case.id))
            results = runner.run(case, results_dir=out_dir)
            entry = write_results(results, out_dir)
        except Exception as exc:
            protocol.emit(type="error", message=str(exc), traceback=traceback.format_exc())
            write_manifest(out_dir, entries, str(args.project))
            return EXIT_ANALYSIS_ERROR
        entries.append(entry)
        for warning in entry["warnings"]:
            protocol.log(f"Warning: {warning}")
        protocol.log("Analysis complete.")
        protocol.emit(type="case_finished", **entry)

    write_manifest(out_dir, entries, str(args.project))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
