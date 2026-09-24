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

Eigen determinism: ARPACK keeps its start vector across ``eigen`` calls,
so only the first eigen call of a process is reproducible. Once an eigen
call has happened in this process, every later case whose routed solver
is ARPACK (see ``core.modal.resolve_modal_solver``) runs in a fresh child
``python -m opensees_studio.run`` with the same project, output directory
and override file; its protocol lines are relayed and its manifest entry
merged, so the caller sees one run. Dense (``fullGenLapack``) cases are
direct solves and run in place.

``OPENSEES_STUDIO_CLI_HARD_EXIT_AFTER=N`` (tests only) makes the process
leave with ``os._exit(255)`` after the N-th progress line, imitating a
solver hard exit.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
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


def _uses_eigen(case: Any) -> bool:
    """True when running ``case`` calls ``ops.eigen`` at least once."""
    from opensees_studio.core import ModalCase, ResponseSpectrumCase, TransientCase

    if isinstance(case, ModalCase | ResponseSpectrumCase):
        return True
    return isinstance(case, TransientCase) and case.rayleigh_mode1_damping is not None


def _routed_to_arpack(project: Any, case: Any) -> bool:
    """True when ``case`` would run its eigen analysis with ARPACK."""
    from opensees_studio.core import ModalCase, ResponseSpectrumCase
    from opensees_studio.core.modal import SOLVER_ARPACK, free_dof_count, resolve_modal_solver

    modal = case
    if isinstance(case, ResponseSpectrumCase):
        modal = next(
            (
                c
                for c in project.analyses
                if isinstance(c, ModalCase) and c.id == case.modal_case_id
            ),
            None,
        )
    if not isinstance(modal, ModalCase):
        return False
    try:
        solver, _reason = resolve_modal_solver(modal.solver, free_dof_count(project), modal.n_modes)
    except ValueError:
        return False  # the runner reports the refusal itself
    return solver == SOLVER_ARPACK


def _run_in_fresh_process(
    protocol: _Protocol, args: argparse.Namespace, case: Any
) -> tuple[dict[str, Any] | None, int]:
    """Run one case in a child CLI, relaying its protocol lines.

    Returns ``(manifest entry or None, exit code)``. The child writes its
    result files into the same output directory; its own ``manifest.json``
    is replaced by the parent's complete one afterwards.
    """
    cmd = [
        sys.executable,
        "-m",
        "opensees_studio.run",
        "--project",
        str(args.project),
        "--cases",
        str(case.id),
        "--out",
        str(args.out),
    ]
    if args.case_override:
        cmd += ["--case-override", str(args.case_override)]
    protocol.log(
        f"Case '{case.name}' uses ARPACK after an earlier eigen call: running it in a "
        "fresh process so its eigen call is the first of that process."
    )
    child = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    entry: dict[str, Any] | None = None
    saw_error = False
    assert child.stdout is not None
    for line in child.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            protocol.log(line)
            continue
        kind = payload.get("type")
        if kind == "case_finished":
            entry = {k: v for k, v in payload.items() if k != "type"}
        elif kind == "error":
            saw_error = True
        protocol.emit(**payload)
    code = child.wait()
    if code != EXIT_OK and not saw_error:
        protocol.emit(
            type="error",
            message=f"Fresh process for case '{case.name}' exited with code {code}.",
            traceback="",
        )
    if code != EXIT_OK:
        return None, EXIT_ANALYSIS_ERROR
    if entry is None:
        protocol.emit(
            type="error",
            message=f"Fresh process for case '{case.name}' finished without a result.",
            traceback="",
        )
        return None, EXIT_ANALYSIS_ERROR
    return entry, EXIT_OK


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
    from opensees_studio.services.results import eigen_solver_note

    entries: list[dict[str, Any]] = []
    eigen_called = False
    protocol.log(f"Building model: {len(project.nodes)} nodes, {len(project.elements)} elements.")
    for case in cases:
        if eigen_called and _routed_to_arpack(project, case):
            entry, code = _run_in_fresh_process(protocol, args, case)
            if entry is None:
                write_manifest(out_dir, entries, str(args.project))
                return code
            entries.append(entry)
            continue
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
        eigen_called = eigen_called or _uses_eigen(case)
        note = eigen_solver_note(results)
        if note:
            protocol.log(note)
        entries.append(entry)
        for warning in entry["warnings"]:
            protocol.log(f"Warning: {warning}")
        protocol.log("Analysis complete.")
        protocol.emit(type="case_finished", **entry)

    write_manifest(out_dir, entries, str(args.project))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
