"""Results snapshots: every example's results, fingerprinted and pinned.

Each project in ``examples/`` runs through the analysis CLI the application
uses (``python -m opensees_studio.run``, one child per project, every case in
the project's order). Each case's results are reduced to a *fingerprint* — a
few order-independent numbers per result kind: the largest displacement per
DOF, the sum of the reactions, the largest element force and the norms of
both, the periods, the step count — and compared with the pinned values in
``tests/data/results_snapshots.json``.

A change of results is never silent. When a fix moves numbers, ``--check``
fails and names them; ``--write`` refuses to pin the new values without a
``--reason``, and then appends the before/after of every changed quantity to
``docs/results-changes.md``, the record the CHANGELOG's *Results changed*
section points to.

Usage (from the repository root, with the ``opensees`` extra installed)::

    python tools/results_snapshot.py --check                 # what CI runs
    python tools/results_snapshot.py --write --reason "..."  # pin new results

``tests/integration/test_results_snapshot.py`` runs the check in CI.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"
SNAPSHOTS = REPO / "tests" / "data" / "results_snapshots.json"
CHANGES = REPO / "docs" / "results-changes.md"

#: Relative change a quantity may show before it counts as a change of results.
#: Far above floating-point noise across platforms and BLAS builds (1e-12 to
#: 1e-9 on these models), far below any change an engineer would act on.
RTOL = 1e-5
#: Within one list (the six DOFs of a maximum, the periods), values smaller than
#: this fraction of the list's largest are compared with that as an absolute
#: tolerance: a rotation of 1e-17 next to a translation of 1e-2 is noise.
FLOOR = 1e-9
#: Significant digits stored in the snapshot file.
DIGITS = 10

Fingerprint = dict[str, Any]


# ─────────────────────────── fingerprints ───────────────────────────
def _round(value: float) -> float:
    if not math.isfinite(value) or value == 0.0:
        return float(value)
    return float(f"{value:.{DIGITS}g}")


def _rounded(values: Any) -> list[float]:
    return [_round(float(v)) for v in np.ravel(values)]


def _last_rows(arrays: dict[int, np.ndarray]) -> np.ndarray:
    """The last row of every array, stacked (ragged widths padded with 0)."""
    rows = [np.atleast_2d(np.asarray(a, dtype=float))[-1] for a in arrays.values() if np.size(a)]
    if not rows:
        return np.zeros((0, 0))
    width = max(r.size for r in rows)
    return np.array([np.pad(r, (0, width - r.size)) for r in rows])


def _all_rows(arrays: dict[int, np.ndarray]) -> np.ndarray:
    rows = [np.atleast_2d(np.asarray(a, dtype=float)) for a in arrays.values() if np.size(a)]
    if not rows:
        return np.zeros((0, 0))
    width = max(r.shape[1] for r in rows)
    return np.vstack([np.pad(r, ((0, 0), (0, width - r.shape[1]))) for r in rows])


def _field(prefix: str, matrix: np.ndarray, *, per_column: bool = True) -> Fingerprint:
    """Largest absolute value (per column), and the Frobenius norm, of ``matrix``."""
    if matrix.size == 0:
        return {}
    out: Fingerprint = {f"{prefix}_norm": _round(float(np.linalg.norm(matrix)))}
    if per_column:
        out[f"{prefix}_max"] = _rounded(np.max(np.abs(matrix), axis=0))
    else:
        out[f"{prefix}_max"] = _round(float(np.max(np.abs(matrix))))
    return out


def fingerprint(result: Any) -> Fingerprint:
    """The numbers a case is pinned by (see the module docstring)."""
    from opensees_studio.services.results import (
        InfluenceLineResults,
        ModalResults,
        PushoverResults,
        ResponseSpectrumResults,
        StaticResults,
        TransientResults,
    )

    out: Fingerprint = {"kind": type(result).__name__}
    if isinstance(result, InfluenceLineResults):
        # Every stop counts; the last one alone (the load over a support) is noise.
        out["n_steps"] = int(result.n_steps)
        out |= _field("line_disp", _all_rows(result.node_disp))
        out |= _field("line_reaction", _all_rows(result.node_reaction))
        out |= _field("line_force", _all_rows(result.element_forces), per_column=False)
    elif isinstance(result, StaticResults):
        out["n_steps"] = int(result.n_steps)
        out |= _field("disp", _last_rows(result.node_disp))
        reactions = _last_rows(result.node_reaction)
        if reactions.size:
            out["reaction_sum"] = _rounded(reactions.sum(axis=0))
        out |= _field("force", _last_rows(result.element_forces), per_column=False)
        out |= _field("shell", _last_rows(result.element_stresses))
    elif isinstance(result, PushoverResults):
        out["n_steps"] = int(result.n_steps)
        out["control_disp_final"] = _round(float(np.asarray(result.control_disp)[-1]))
        out["base_shear_max"] = _round(float(np.max(np.abs(result.base_shear))))
        out["base_shear_final"] = _round(float(np.asarray(result.base_shear)[-1]))
        out |= _field("disp", _last_rows(result.node_disp))
        out |= _field("force", _last_rows(result.element_forces), per_column=False)
    elif isinstance(result, ModalResults):
        out["solver"] = result.solver
        out["periods"] = _rounded(result.periods)
    elif isinstance(result, ResponseSpectrumResults):
        out["combination"] = result.combination
        out["periods"] = _rounded([m.period for m in result.modes])
        out |= _field("disp", _all_rows(result.combined_disp))
        out |= _field("reaction", _all_rows(result.node_reaction))
        out |= _field("force", _all_rows(result.element_forces), per_column=False)
    elif isinstance(result, TransientResults):
        out["n_steps"] = int(result.n_steps)
        out["n_steps_requested"] = int(result.n_steps_requested)
        import h5py

        with h5py.File(result.h5_path, "r") as f:
            out["time_final"] = _round(float(f["time"][-1])) if len(f["time"]) else 0.0
            disp = {int(k): f[f"nodes/{k}/disp"][:] for k in f["nodes"] if "disp" in f["nodes"][k]}
            forces = (
                {int(k): f[f"elements/{k}/forces"][:] for k in f["elements"]}
                if "elements" in f
                else {}
            )
        out |= _field("peak_disp", _all_rows(disp))
        out |= _field("final_disp", _last_rows(disp))
        out |= _field("peak_force", _all_rows(forces), per_column=False)
    return out


# ─────────────────────────── running ───────────────────────────
def run_project(path: Path) -> dict[str, Fingerprint]:
    """Every case of the project at ``path``, through the CLI: case id → fingerprint."""
    from opensees_studio.services import load_project
    from opensees_studio.services.result_store import load_manifest, load_results

    project = load_project(path)
    ids = [str(case.id) for case in project.analyses]
    if not ids:
        return {}
    with tempfile.TemporaryDirectory(prefix="snapshot_") as tmp:
        proc = subprocess.run(
            [
                sys.executable,
                "-u",
                "-m",
                "opensees_studio.run",
                "--project",
                str(path),
                "--cases",
                *ids,
                "--out",
                tmp,
            ],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        out: dict[str, Fingerprint] = {}
        if (Path(tmp) / "manifest.json").exists():
            for entry in load_manifest(tmp)["cases"]:
                out[str(entry["case_id"])] = fingerprint(load_results(entry, tmp))
        errors = [
            json.loads(line)
            for line in proc.stdout.splitlines()
            if line.startswith("{") and '"error"' in line
        ]
        for case_id in ids:
            if case_id not in out:
                message = next((e.get("message", "") for e in errors), "") or (
                    f"exit code {proc.returncode}"
                )
                out[case_id] = {"kind": "error", "message": str(message)[:200]}
    return out


def run_all(names: list[str] | None = None) -> dict[str, dict[str, Fingerprint]]:
    """Fingerprints of every example (or of ``names``), keyed by file stem."""
    paths = sorted(EXAMPLES.glob("*.osmodel"))
    if names:
        paths = [p for p in paths if p.stem in names]
    return {p.stem: run_project(p) for p in paths}


# ─────────────────────────── comparing ───────────────────────────
@dataclass(frozen=True)
class Change:
    example: str
    case: str
    quantity: str
    before: Any
    after: Any

    @property
    def relative(self) -> float | None:
        if isinstance(self.before, int | float) and isinstance(self.after, int | float):
            scale = abs(float(self.before)) or 1.0
            return abs(float(self.after) - float(self.before)) / scale
        return None


def _same(before: Any, after: Any) -> bool:
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return False
        finite = [abs(v) for v in before if isinstance(v, int | float) and math.isfinite(v)]
        floor = FLOOR * max(finite, default=0.0)
        return all(_close(a, b, floor) for a, b in zip(before, after, strict=True))
    if isinstance(before, float) or isinstance(after, float):
        return _close(before, after, 0.0)
    return bool(before == after)


def _close(before: Any, after: Any, floor: float) -> bool:
    if not isinstance(before, int | float) or not isinstance(after, int | float):
        return bool(before == after)
    b, a = float(before), float(after)
    if not (math.isfinite(a) and math.isfinite(b)):
        return a == b
    return abs(a - b) <= max(RTOL * abs(b), floor) or a == b


def compare(
    pinned: dict[str, dict[str, Fingerprint]], current: dict[str, dict[str, Fingerprint]]
) -> list[Change]:
    """Every quantity that differs between the pinned and the current snapshots."""
    changes: list[Change] = []
    for example in sorted(set(pinned) | set(current)):
        old_cases, new_cases = pinned.get(example, {}), current.get(example, {})
        for case in sorted(set(old_cases) | set(new_cases), key=lambda c: (len(c), c)):
            old, new = old_cases.get(case, {}), new_cases.get(case, {})
            if not old or not new:
                changes.append(Change(example, case, "(case)", bool(old), bool(new)))
                continue
            for key in sorted(set(old) | set(new)):
                if key not in old or key not in new or not _same(old[key], new[key]):
                    changes.append(Change(example, case, key, old.get(key), new.get(key)))
    return changes


# ─────────────────────────── files ───────────────────────────
def load_pinned() -> dict[str, dict[str, Fingerprint]]:
    if not SNAPSHOTS.exists():
        return {}
    data = json.loads(SNAPSHOTS.read_text(encoding="utf-8"))
    return dict(data["examples"])


def dump(current: dict[str, dict[str, Fingerprint]]) -> str:
    payload = {
        "about": "Pinned example results. Regenerate only with "
        "`python tools/results_snapshot.py --write --reason ...`.",
        "rtol": RTOL,
        "examples": current,
    }
    return json.dumps(payload, indent=1, sort_keys=True) + "\n"


def _show(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_show(v) for v in value) + "]"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def changes_entry(changes: list[Change], reason: str, today: str) -> str:
    """The Markdown block ``--write`` appends to ``docs/results-changes.md``."""
    lines = [f"## {today}: {reason}", "", "| Example | Case | Quantity | Before | After |"]
    lines.append("|---|---|---|---|---|")
    for c in changes:
        lines.append(
            f"| {c.example} | {c.case} | {c.quantity} | {_show(c.before)} | {_show(c.after)} |"
        )
    return "\n".join(lines) + "\n"


def _report(changes: list[Change]) -> str:
    rows = [
        f"  {c.example} case {c.case} {c.quantity}: {_show(c.before)} -> {_show(c.after)}"
        for c in changes
    ]
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="fail when a result changed")
    group.add_argument("--write", action="store_true", help="pin the current results")
    parser.add_argument("--reason", default="", help="why results changed (required by --write)")
    parser.add_argument("examples", nargs="*", help="only these example stems")
    args = parser.parse_args(argv)

    current = run_all(args.examples or None)
    pinned = load_pinned()
    scope = {k: v for k, v in pinned.items() if k in current} if args.examples else pinned
    changes = compare(scope, current)

    if args.write:
        # A new example has nothing to compare with: pinning it needs no reason.
        changes = [c for c in changes if c.example in pinned]
        if changes and not args.reason.strip():
            print("Results changed; pin them with --reason saying why:\n" + _report(changes))
            return 1
        merged = {**pinned, **current}
        SNAPSHOTS.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOTS.write_text(dump(merged), encoding="utf-8")
        if changes:
            today = _dt.date.today().isoformat()
            text = CHANGES.read_text(encoding="utf-8")
            CHANGES.write_text(
                text.rstrip("\n") + "\n\n" + changes_entry(changes, args.reason.strip(), today),
                encoding="utf-8",
            )
            print(f"Pinned {len(changes)} changed quantities; recorded in {CHANGES.name}.")
        else:
            print(f"Pinned {sum(len(v) for v in current.values())} cases.")
        return 0

    if changes:
        print(
            "Results changed against tests/data/results_snapshots.json:\n"
            + _report(changes)
            + "\n\nIf the change is intended, pin it with\n"
            '  python tools/results_snapshot.py --write --reason "what changed and why"\n'
            "and add a 'Results changed' entry to CHANGELOG.md."
        )
        return 1
    print(f"{sum(len(v) for v in current.values())} cases match their snapshots.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
