"""On-disk transport for analysis results.

The analysis CLI (``python -m opensees_studio.run``) runs in a child
process and cannot hand result objects back to the GUI directly, so every
result kind is written to the output directory and rebuilt from it:

- ``StaticResults``, ``PushoverResults``, ``ModalResults`` and
  ``ResponseSpectrumResults`` go to ``case_<id>.results.h5`` (float64
  datasets, so the round trip is exact) plus scalar metadata in the
  manifest entry.
- ``TransientResults`` already keeps its history in ``case_<id>.h5``
  written by the runner; the manifest entry only records the scalars.

``manifest.json`` lists one entry per case with the result type, the
files, the completed steps, the early-stop flag and warnings.

Qt-free: safe to import from the CLI and from tests without a display.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from opensees_studio.services.results import (
    ModalResults,
    PushoverResults,
    ResponseSpectrumResults,
    StaticResults,
    TransientResults,
)
from opensees_studio.services.spectrum import ModeContribution

MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA = 1

AnyResults = (
    StaticResults | PushoverResults | ModalResults | ResponseSpectrumResults | TransientResults
)


def results_file_name(case_id: int) -> str:
    """Name of the array file of a non-transient case."""
    return f"case_{case_id}.results.h5"


# ─────────────────────── helpers ───────────────────────
def _write_int_dict(group: Any, name: str, data: dict[int, np.ndarray]) -> None:
    sub = group.create_group(name)
    for key, arr in data.items():
        sub.create_dataset(str(key), data=np.asarray(arr, dtype=float))


def _read_int_dict(group: Any, name: str) -> dict[int, np.ndarray]:
    if name not in group:
        return {}
    sub = group[name]
    return {int(k): sub[k][()] for k in sorted(sub.keys(), key=int)}


def _mode_scalars(mode: ModeContribution) -> dict[str, Any]:
    scalars = asdict(mode)
    scalars.pop("modal_peak_disp", None)
    return {k: (float(v) if isinstance(v, float | np.floating) else v) for k, v in scalars.items()}


# ─────────────────────── write ───────────────────────
def write_results(results: AnyResults, out_dir: str | Path) -> dict[str, Any]:
    """Write ``results`` under ``out_dir`` and return its manifest entry.

    The entry carries everything ``load_results`` needs; file paths are
    relative to ``out_dir``.
    """
    import h5py

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    entry: dict[str, Any] = {
        "case_id": results.case_id,
        "case_name": results.case_name,
        "result_type": type(results).__name__,
        "files": [],
        "completed_steps": None,
        "early_stop": False,
        "warnings": [],
    }

    if isinstance(results, TransientResults):
        h5 = Path(results.h5_path)
        try:
            rel = h5.relative_to(out)
        except ValueError:
            rel = h5.resolve()
        entry["files"] = [rel.as_posix()]
        entry["completed_steps"] = results.n_steps
        entry["early_stop"] = results.early_stop
        entry["dt"] = results.dt
        entry["n_steps_requested"] = results.n_steps_requested
        if results.early_stop:
            entry["warnings"].append(f"Transient run stopped early: {results.steps_summary()}.")
        return entry

    name = results_file_name(results.case_id)
    entry["files"] = [name]
    with h5py.File(out / name, "w") as f:
        if isinstance(results, StaticResults):
            entry["completed_steps"] = results.n_steps
            _write_int_dict(f, "node_disp", results.node_disp)
            _write_int_dict(f, "node_reaction", results.node_reaction)
            _write_int_dict(f, "element_forces", results.element_forces)
        elif isinstance(results, PushoverResults):
            entry["completed_steps"] = results.n_steps
            entry["control_node"] = results.control_node
            entry["control_dof"] = results.control_dof
            f.create_dataset("control_disp", data=np.asarray(results.control_disp, dtype=float))
            f.create_dataset("base_shear", data=np.asarray(results.base_shear, dtype=float))
            _write_int_dict(f, "node_disp", results.node_disp)
            _write_int_dict(f, "element_forces", results.element_forces)
        elif isinstance(results, ModalResults):
            entry["completed_steps"] = len(results.eigenvalues)
            entry["solver"] = results.solver
            entry["n_free_dof"] = int(results.n_free_dof)
            f.create_dataset("eigenvalues", data=np.asarray(results.eigenvalues, dtype=float))
            shapes = f.create_group("mode_shapes")
            for mode, vectors in results.mode_shapes.items():
                _write_int_dict(shapes, str(mode), vectors)
        elif isinstance(results, ResponseSpectrumResults):
            entry["completed_steps"] = len(results.modes)
            entry["direction"] = results.direction
            entry["combination"] = results.combination
            entry["solver"] = results.solver
            entry["damping_ratio"] = results.damping_ratio
            entry["warnings"] = list(results.warnings)
            entry["modes"] = [_mode_scalars(m) for m in results.modes]
            _write_int_dict(f, "combined_disp", results.combined_disp)
            modes = f.create_group("modes")
            for i, mode in enumerate(results.modes):
                _write_int_dict(modes, str(i), mode.modal_peak_disp)
        else:  # pragma: no cover - guarded by the AnyResults union
            raise TypeError(f"Unsupported result type: {type(results).__name__}")
    return entry


def write_manifest(out_dir: str | Path, entries: list[dict[str, Any]], project: str) -> Path:
    """Write ``manifest.json`` under ``out_dir``."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": MANIFEST_SCHEMA, "project": project, "cases": entries}
    target = out / MANIFEST_NAME
    target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return target


# ─────────────────────── read ───────────────────────
def load_manifest(out_dir: str | Path) -> dict[str, Any]:
    """Read ``manifest.json`` from ``out_dir``."""
    return json.loads((Path(out_dir) / MANIFEST_NAME).read_text(encoding="utf-8"))


def load_results(entry: dict[str, Any], out_dir: str | Path) -> AnyResults:
    """Rebuild the result object described by a manifest ``entry``."""
    import h5py

    out = Path(out_dir)
    kind = entry["result_type"]
    case_id = int(entry["case_id"])
    case_name = str(entry["case_name"])
    path = out / entry["files"][0]

    if kind == "TransientResults":
        return TransientResults(
            case_id=case_id,
            case_name=case_name,
            h5_path=path,
            n_steps=int(entry["completed_steps"]),
            dt=float(entry["dt"]),
            n_steps_requested=int(entry["n_steps_requested"]),
        )

    with h5py.File(path, "r") as f:
        if kind == "StaticResults":
            return StaticResults(
                case_id=case_id,
                case_name=case_name,
                n_steps=int(entry["completed_steps"]),
                node_disp=_read_int_dict(f, "node_disp"),
                node_reaction=_read_int_dict(f, "node_reaction"),
                element_forces=_read_int_dict(f, "element_forces"),
            )
        if kind == "PushoverResults":
            return PushoverResults(
                case_id=case_id,
                case_name=case_name,
                n_steps=int(entry["completed_steps"]),
                control_node=int(entry["control_node"]),
                control_dof=int(entry["control_dof"]),
                control_disp=f["control_disp"][()],
                base_shear=f["base_shear"][()],
                node_disp=_read_int_dict(f, "node_disp"),
                element_forces=_read_int_dict(f, "element_forces"),
            )
        if kind == "ModalResults":
            shapes = f["mode_shapes"]
            return ModalResults(
                case_id=case_id,
                case_name=case_name,
                eigenvalues=f["eigenvalues"][()],
                mode_shapes={
                    int(m): _read_int_dict(shapes, m) for m in sorted(shapes.keys(), key=int)
                },
                solver=str(entry.get("solver", "")),
                n_free_dof=int(entry.get("n_free_dof", 0)),
            )
        if kind == "ResponseSpectrumResults":
            mode_groups = f["modes"]
            modes = [
                ModeContribution(
                    **scalars,
                    modal_peak_disp=_read_int_dict(mode_groups, str(i)),
                )
                for i, scalars in enumerate(entry["modes"])
            ]
            return ResponseSpectrumResults(
                case_id=case_id,
                case_name=case_name,
                direction=int(entry["direction"]),
                combination=str(entry["combination"]),
                combined_disp=_read_int_dict(f, "combined_disp"),
                modes=modes,
                solver=str(entry.get("solver", "")),
                damping_ratio=(
                    None if entry.get("damping_ratio") is None else float(entry["damping_ratio"])
                ),
                warnings=[str(w) for w in entry.get("warnings", [])],
            )
    raise ValueError(f"Unknown result type in manifest: {kind}")
