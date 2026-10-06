"""Published values versus command-built models solved by the production CLI."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

import numpy as np
import pytest

from opensees_studio.services import load_project, save_project
from opensees_studio.services.result_store import load_manifest, load_results
from opensees_studio.services.result_tables import (
    modal_tables,
    pushover_tables,
    static_history_table,
    static_tables,
    write_csv,
)
from opensees_studio.services.results import ModalResults, PushoverResults, StaticResults
from tests.unit.test_example_files import _builder_name

ROOT = Path(__file__).resolve().parents[2]
REFERENCES = sorted((ROOT / "tests/reference/official_structural").glob("0*.json"))


def _solve(path, out):
    case_ids = [str(c.id) for c in load_project(path).analyses]
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(path),
            "--cases",
            *case_ids,
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    manifest = load_manifest(out)
    assert all(not c["early_stop"] for c in manifest["cases"]), manifest
    return [load_results(entry, out) for entry in manifest["cases"]]


def _export(results, project, folder):
    folder.mkdir()
    exports = []
    for result in results:
        if isinstance(result, StaticResults):
            tables = [*static_tables(result, project), static_history_table(result, project)]
        elif isinstance(result, PushoverResults):
            tables = pushover_tables(result, project)
        else:
            tables = modal_tables(result)
        for index, table in enumerate(tables):
            exports.append(write_csv(table, folder / f"{result.case_id}_{index}.csv").read_bytes())
    return exports


def _compare(reference, results, module):
    final = results[-1]
    mapping = getattr(module, "NODE_TAG_MAP", {})
    linear = reference["example"] in ("01", "03")
    comparisons = []

    def compare(name, actual, expected, rel):
        actual = np.asarray(actual, dtype=float)
        expected = np.asarray(expected, dtype=float)
        assert actual.shape == expected.shape, (name, actual.shape, expected.shape)
        delta = np.abs(actual - expected)
        limit = np.maximum(1e-12, rel * np.abs(expected))
        nonzero = np.abs(expected) > 1e-12
        largest = (
            float(np.max(delta[nonzero] / np.abs(expected[nonzero]))) if np.any(nonzero) else 0.0
        )
        comparisons.append((name, largest))
        assert np.all(delta <= limit), (
            name,
            "largest relative difference",
            largest,
            "max tolerance ratio",
            float(np.max(delta / limit)),
        )

    for key, scalar in reference["scalars"].items():
        parts = key.split("/")
        if parts[0] == "node":
            tag = mapping.get(int(parts[1]), int(parts[1]))
            data = final.node_disp if parts[2] == "disp" else final.node_reaction
            value = data[tag][-1, int(parts[3]) - 1]
        elif parts[0] == "mode":
            modal = next(r for r in results if isinstance(r, ModalResults))
            value = modal.periods[int(parts[1]) - 1]
        else:
            # Example 03 element 1 is vertical: rotate local end forces to global.
            n1, v1, m1, n2, v2, m2 = final.element_forces[1][-1]
            value = (-v1, n1, m1, -v2, n2, m2)[int(parts[3]) - 1]
        compare(key, value, scalar["value"], 1e-8 if linear else 1e-5)

    for curve in reference["curves"]:
        points = curve["points"]
        expected = [[p["x"], p["y"]] for p in points]
        example = reference["example"]
        if example == "02":
            actual = np.column_stack((final.node_disp[4][:, 0], final.load_factors * 160))
        elif example == "04":
            actual = np.vstack(([0, 0], np.column_stack((final.control_disp, final.base_shear))))
        elif example == "06":
            gravity = results[0]
            initial = np.column_stack(
                (
                    gravity.node_disp[3][1:, 0],
                    -(gravity.node_reaction[1][1:, 0] + gravity.node_reaction[2][1:, 0]),
                )
            )
            actual = np.vstack(
                (initial, np.column_stack((final.control_disp[1:], final.base_shear[1:])))
            )
        elif curve["name"] == "gravity-load-displacement":
            gravity = results[0]
            actual = np.column_stack((gravity.node_disp[10][:, 1], gravity.load_factors * 5))
        elif curve["name"] == "base-shear-displacement":
            actual = np.column_stack((final.control_disp, final.base_shear))
            # The script initializes dataPush[0] to zero after applying gravity.
            actual[0] = 0
        else:
            # WFSection2d numbers the upper flange from its outer edge inward.
            # Rectangular patches enumerate ascending y: index 1 maps to 15-1-1.
            data = final.element_end_fibers[module.ELEMENT_TAG_MAP[102]][1:, 13]
            assert data[0, 0] == pytest.approx(8.3 / 2 - 1.5 * 0.685 / 15, abs=1e-14)
            actual = np.column_stack((data[:, 4], data[:, 3]))
        compare(curve["name"], actual, expected, 1e-5)
    return comparisons


@pytest.mark.parametrize("reference_path", REFERENCES, ids=lambda p: p.stem)
def test_official_structural_example(reference_path, tmp_path):
    reference = json.loads(reference_path.read_text())
    module = importlib.import_module("examples.official." + reference_path.stem)
    builder = getattr(module, _builder_name(Path(module.__file__)))
    project = builder()
    path = save_project(project, tmp_path / "built.osmodel")
    first = _solve(path, tmp_path / "first")
    reopened = load_project(path)
    second_path = save_project(reopened, tmp_path / "reopened.osmodel")
    assert path.read_bytes() == second_path.read_bytes()
    second = _solve(second_path, tmp_path / "second")
    assert _export(first, project, tmp_path / "export1") == _export(
        second, reopened, tmp_path / "export2"
    )
    for r1, r2 in zip(first, second, strict=True):
        for field in fields(r1):
            v1, v2 = getattr(r1, field.name), getattr(r2, field.name)
            if isinstance(v1, dict) and v1 and isinstance(next(iter(v1.values())), np.ndarray):
                assert v1.keys() == v2.keys()
                for key in v1:
                    np.testing.assert_array_equal(v1[key], v2[key])
            elif isinstance(v1, np.ndarray):
                np.testing.assert_array_equal(v1, v2)
    comparisons = _compare(reference, first, module)
    _compare(reference, second, module)
    evidence = {
        "example": reference_path.stem,
        "comparisons": comparisons,
        "largest_relative_difference": max(v for _, v in comparisons),
    }
    (tmp_path / "comparison.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence))
