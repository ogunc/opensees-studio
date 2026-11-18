"""The results database: schema, rows and the append-only history."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from opensees_studio.services.results import (
    CombinationResults,
    ModalResults,
    PushoverResults,
    ResponseSpectrumResults,
    StaticResults,
    TransientResults,
)
from opensees_studio.services.results_db import (
    database_path,
    read_runs,
    record_results,
)


def _static(case_id: int = 1, steps: int = 2) -> StaticResults:
    return StaticResults(
        case_id=case_id,
        case_name="Static push",
        n_steps=steps,
        node_disp={
            1: np.array([[0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [1.0, 0.0, -2.0, 0.0, 0.0, 0.0]][:steps]),
            2: np.zeros((steps, 6)),
        },
        node_reaction={1: np.array([[10.0, 0.0, 5.0, 0.0, 0.0, 0.0]][:steps] * steps)[:steps]},
        element_forces={7: np.arange(steps * 12, dtype=float).reshape(steps, 12)},
        element_stresses={7: np.ones((steps, 8))},
        storey_shear={1: np.zeros((steps, 3))},
        section_cut_forces={2: np.zeros((steps, 6))},
    )


def test_a_static_run_lands_in_the_expected_tables(tmp_path: Path) -> None:
    db = tmp_path / "results.sqlite"

    run_id = record_results(_static(), db_path=db)

    assert run_id == 1
    runs = read_runs(db)
    assert len(runs) == 1
    assert runs[0]["kind"] == "static"
    assert runs[0]["n_steps"] == 2

    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM node_disp").fetchone()[0] == 4
        assert con.execute("SELECT COUNT(*) FROM node_reaction").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM element_forces").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM element_stresses").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM storey_shear").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM section_cut_forces").fetchone()[0] == 2
        ux = con.execute(
            "SELECT ux FROM node_disp WHERE run_id = ? AND node_id = 1 AND step = 1",
            (run_id,),
        ).fetchone()[0]
        assert ux == pytest.approx(1.0)


def test_re_running_a_case_replaces_its_rows(tmp_path: Path) -> None:
    """A case keeps one run: running it again overwrites, it does not accumulate."""
    db = tmp_path / "results.sqlite"

    record_results(_static(case_id=1), db_path=db)
    record_results(_static(case_id=1), db_path=db)

    assert len(read_runs(db)) == 1
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM node_disp").fetchone()[0] == 4


def test_different_cases_coexist(tmp_path: Path) -> None:
    db = tmp_path / "results.sqlite"

    record_results(_static(case_id=1), db_path=db)
    record_results(_static(case_id=2), db_path=db)

    assert [r["case_id"] for r in read_runs(db)] == [1, 2]
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM node_disp").fetchone()[0] == 8


def test_deleting_every_result_removes_the_file(tmp_path: Path) -> None:
    from opensees_studio.services.results_db import delete_all_results

    db = tmp_path / "results.sqlite"
    assert delete_all_results(db) is False  # nothing there yet

    record_results(_static(), db_path=db)
    assert db.exists()

    assert delete_all_results(db) is True
    assert not db.exists()


def test_a_modal_run_stores_modes_and_shapes(tmp_path: Path) -> None:
    db = tmp_path / "results.sqlite"
    results = ModalResults(
        case_id=3,
        case_name="Modes",
        eigenvalues=np.array([4.0, 9.0]),
        mode_shapes={
            1: {1: np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0]), 2: np.zeros(6)},
            2: {1: np.array([0.0, 1.0, 0.0, 0.0, 0.0, 0.0])},
        },
        solver="fullGenLapack",
        n_free_dof=12,
    )

    record_results(results, db_path=db)

    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM modal").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM mode_shapes").fetchone()[0] == 3
        period = con.execute("SELECT period FROM modal WHERE mode = 1").fetchone()[0]
        assert period == pytest.approx(2 * np.pi / 2.0)
        assert "fullGenLapack" in (read_runs(db)[0]["notes"] or "")


def test_a_combination_records_both_bounds(tmp_path: Path) -> None:
    db = tmp_path / "results.sqlite"
    combined = CombinationResults(
        combination_id=1,
        combination_name="1.4D + 1.7L",
        combination_type="linear_add",
        max=_static(case_id=10),
        min=_static(case_id=10),
        single_valued=True,
    )

    record_results(combined, db_path=db)

    kinds = [r["kind"] for r in read_runs(db)]
    assert kinds == ["combination:max", "combination:min"]


def test_a_pushover_keeps_the_t0_row(tmp_path: Path) -> None:
    db = tmp_path / "results.sqlite"
    results = PushoverResults(
        case_id=4,
        case_name="Push",
        n_steps=2,
        control_node=1,
        control_dof=1,
        control_disp=np.zeros(3),
        base_shear=np.zeros(3),
        node_disp={1: np.zeros((3, 6))},
    )

    record_results(results, db_path=db)

    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM node_disp").fetchone()[0] == 3


def test_a_response_spectrum_is_one_peak_row_per_node(tmp_path: Path) -> None:
    db = tmp_path / "results.sqlite"
    results = ResponseSpectrumResults(
        case_id=5,
        case_name="RS",
        direction=1,
        combination="CQC",
        combined_disp={1: np.array([0.1, 0.0, 0.2]), 2: np.array([0.3, 0.0, 0.0])},
        node_reaction={1: np.array([1.0, 0.0, 2.0, 0.0, 0.0, 0.0])},
        element_forces={3: np.ones(12)},
    )

    record_results(results, db_path=db)

    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM node_disp").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM element_forces").fetchone()[0] == 1


def test_a_transient_run_indexes_its_displacement_history(tmp_path: Path) -> None:
    db = tmp_path / "results.sqlite"

    class _FakeTransient(TransientResults):
        def steps_summary(self) -> str:
            return "2 steps"

        def node_disp_history(self, node_id: int) -> np.ndarray:
            return np.zeros((2, 6))

    results = _FakeTransient(
        case_id=6,
        case_name="TH",
        h5_path=tmp_path / "case_6.h5",
        n_steps=2,
        dt=0.01,
        n_steps_requested=2,
    )

    class _Node:
        def __init__(self, node_id: int) -> None:
            self.id = node_id

    class _Project:
        def __init__(self) -> None:
            self.nodes = [_Node(1), _Node(2)]

    record_results(results, db_path=db, project=_Project())

    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM node_disp").fetchone()[0] == 4
    run = read_runs(db)[0]
    assert run["kind"] == "transient"
    assert run["dt"] == pytest.approx(0.01)
    assert run["h5_path"].endswith("case_6.h5")


def test_an_unknown_result_kind_is_ignored(tmp_path: Path) -> None:
    db = tmp_path / "results.sqlite"

    assert record_results(object(), db_path=db) is None


def test_the_database_sits_beside_the_project(tmp_path: Path) -> None:
    project = tmp_path / "tower.osmodel"

    assert database_path(project) == tmp_path / "tower_results.sqlite"

    unsaved = database_path(None)
    assert unsaved.name == "untitled_results.sqlite"
