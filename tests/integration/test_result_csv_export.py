"""CSV export of a real static run reads back the result object exactly."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import StaticCase
from opensees_studio.core.units import labels_for
from opensees_studio.services import load_project
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.result_tables import static_tables, write_csv

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _rows(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    return rows[0], rows[1:]


@pytest.mark.parametrize("example", ["basic_truss", "rc_frame_gravity"])
def test_static_export_matches_the_results_exactly(example: str, tmp_path: Path) -> None:
    project = load_project(EXAMPLES / f"{example}.osmodel")
    case = next(c for c in project.analyses if isinstance(c, StaticCase))
    results = OpenSeesRunner(project).run(case)
    disp, reactions, forces = static_tables(results, project)

    header, rows = _rows(write_csv(disp, tmp_path / "disp.csv"))
    assert header[1] == f"U1 [{labels_for(project.meta.units).length}]"
    assert len(rows) == len(results.node_disp)
    for row in rows:
        exported = np.array([float(v) for v in row[1:]])
        assert np.array_equal(exported, results.node_disp[int(row[0])][-1])

    _header, rows = _rows(write_csv(reactions, tmp_path / "reactions.csv"))
    for row in rows:
        exported = np.array([float(v) for v in row[1:]])
        assert np.array_equal(exported, results.node_reaction[int(row[0])][-1])

    _header, rows = _rows(write_csv(forces, tmp_path / "forces.csv"))
    assert {int(r[0]) for r in rows} == set(results.element_forces)
    for eid, recorded in results.element_forces.items():
        exported = np.array([float(r[4]) for r in rows if int(r[0]) == eid])
        assert np.array_equal(exported, recorded[-1])
