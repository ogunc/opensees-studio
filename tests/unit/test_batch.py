"""Batch planning, summary and stored-results lookup (services.batch); no solver."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from opensees_studio import batch as batch_cli
from opensees_studio.child_cli import analysis_cli_command
from opensees_studio.core import (
    ElasticSection,
    LinearTimeSeries,
    ModalCase,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
)
from opensees_studio.services import batch, engines, save_project
from opensees_studio.services.result_store import write_manifest
from opensees_studio.services.results_db import database_path


def _project() -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=[Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6)],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=8.333e-6)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[PlainLoadPattern(id=1, time_series_id=1)],
        analyses=[
            StaticCase(id=1, name="Dead", pattern_ids=[1]),
            ModalCase(id=2, name="Modal", n_modes=1),
            StaticCase(id=5, name="Live", pattern_ids=[1]),
        ],
    )


def _save(path: Path, project: Project | None = None) -> Path:
    return save_project(project or _project(), path)


# ── inputs ───────────────────────────────────────────────────────────
def test_a_folder_adds_its_projects_but_not_snapshots_or_subfolders(tmp_path: Path) -> None:
    _save(tmp_path / "b.osmodel")
    _save(tmp_path / "a.osmodel")
    (tmp_path / "a.run-snapshot.osmodel").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    _save(tmp_path / "sub" / "c.osmodel")

    found = batch.expand_inputs([tmp_path])

    assert [p.name for p in found] == ["a.osmodel", "b.osmodel"]


def test_a_file_named_twice_runs_once_in_first_order(tmp_path: Path) -> None:
    a = _save(tmp_path / "a.osmodel")
    b = _save(tmp_path / "b.osmodel")

    assert batch.expand_inputs([b, tmp_path, a]) == [b, tmp_path / "a.osmodel"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("all", None), ("", None), ("ALL", None), ("Dead, Modal", ["Dead", "Modal"]), ("3,", ["3"])],
)
def test_case_selector(text: str, expected: list[str] | None) -> None:
    assert batch.parse_case_selector(text) == expected


def test_cases_match_by_name_ignoring_case_or_by_id_in_project_order() -> None:
    cases = _project().analyses
    picked = batch.select_cases(cases, ["live", " DEAD ", "2"])
    assert [c.id for c in picked] == [1, 2, 5]
    assert batch.select_cases(cases, None) == list(cases)


# ── planning ─────────────────────────────────────────────────────────
def test_plan_job_resolves_the_cases_and_fingerprints_the_model(tmp_path: Path) -> None:
    path = _save(tmp_path / "m.osmodel")

    job = batch.plan_job(path, ["Live", "Dead"])

    assert job.error == ""
    assert job.case_ids == [1, 5]
    assert job.case_names == ["Dead", "Live"]
    assert len(job.fingerprint) == 64
    assert job.out_dir == tmp_path / "m_batch_results"
    assert job.db_path == database_path(path)


def test_plan_job_reports_what_cannot_run(tmp_path: Path) -> None:
    broken = tmp_path / "broken.osmodel"
    broken.write_text("not json", encoding="utf-8")
    path = _save(tmp_path / "m.osmodel")

    assert batch.plan_job(tmp_path / "missing.osmodel", None).error == "File not found."
    assert batch.plan_job(broken, None).error.startswith("Cannot read the project")
    assert batch.plan_job(path, ["Wind"]).error == "No case named Wind."
    empty = _save(tmp_path / "e.osmodel", _project().model_copy(update={"analyses": []}))
    assert batch.plan_job(empty, None).error == "The project has no analysis case."


def test_the_child_is_spawned_through_child_cli_and_records_the_database(tmp_path: Path) -> None:
    job = batch.plan_job(_save(tmp_path / "m.osmodel"), None)

    command = batch.job_command(job)

    prefix = analysis_cli_command()
    assert command[: len(prefix)] == prefix
    args = command[len(prefix) :]
    assert args[args.index("--cases") + 1 : args.index("--out")] == ["1", "2", "5"]
    assert args[args.index("--out") + 1] == str(job.out_dir)
    assert args[args.index("--record-db") + 1] == str(job.db_path)


# ── summary ──────────────────────────────────────────────────────────
def _outcomes() -> list[batch.BatchOutcome]:
    return [
        batch.BatchOutcome("a.osmodel", batch.OK, 1.5, ["Dead", "Modal"], 0, "", "a_batch_results"),
        batch.BatchOutcome("b.osmodel", batch.FAILED, 0.4, ["Dead"], 2, "Singular, matrix", ""),
        batch.BatchOutcome("c.osmodel", batch.SKIPPED, message="File not found."),
    ]


def test_summary_counts_every_status() -> None:
    assert batch.summary_counts(_outcomes()) == {
        batch.OK: 1,
        batch.FAILED: 1,
        batch.SKIPPED: 1,
        batch.CANCELLED: 0,
    }


def test_summary_is_written_as_json_and_csv(tmp_path: Path) -> None:
    json_path, csv_path = batch.write_summary(_outcomes(), tmp_path / "out" / "summary.json")

    assert (json_path.name, csv_path.name) == ("summary.json", "summary.csv")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["counts"]["ok"] == 1
    assert payload["jobs"][1]["message"] == "Singular, matrix"
    assert payload["jobs"][0]["cases"] == ["Dead", "Modal"]
    with csv_path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0]) == list(batch.SUMMARY_FIELDS)
    assert rows[0]["cases"] == "Dead; Modal"
    assert rows[1]["message"] == "Singular, matrix"
    assert rows[2]["status"] == "skipped"
    assert rows[2]["exit_code"] == ""


def test_failure_message_prefers_the_error_line_then_the_stderr_tail() -> None:
    assert batch.failure_message(2, "No case 9", "noise") == "No case 9"
    assert batch.failure_message(None, "") == "The analysis process could not be started."
    message = batch.failure_message(255, "", "a\nWARNING last words\n\n")
    assert "exit code 255" in message
    assert message.endswith("WARNING last words")


def test_protocol_lines_parse_and_noise_does_not() -> None:
    assert batch.parse_line('{"type": "log", "message": "x"}\n') == {"type": "log", "message": "x"}
    assert batch.parse_line("WARNING: native output") is None
    assert batch.parse_line("[1, 2]") is None
    assert batch.parse_line("   ") is None


# ── stored results ───────────────────────────────────────────────────
def _stored(tmp_path: Path) -> tuple[Path, batch.BatchJob]:
    path = _save(tmp_path / "m.osmodel")
    job = batch.plan_job(path, None)
    batch.prepare_out_dir(job)
    entry = {"case_id": 1, "case_name": "Dead", "result_type": "static", "files": ["x.h5"]}
    write_manifest(job.out_dir, [entry], str(path))
    batch.mark_stored(job, engine="openseespy")
    return path, job


def test_stored_results_are_found_while_the_model_is_unchanged(tmp_path: Path) -> None:
    from opensees_studio.services import load_project

    path, job = _stored(tmp_path)

    stored = batch.stored_results(path, load_project(path))

    assert stored is not None
    assert stored.out_dir == job.out_dir
    assert [e["case_id"] for e in stored.entries] == [1]
    marker = json.loads((job.out_dir / batch.STORED_NAME).read_text(encoding="utf-8"))
    assert marker["engine"] == "openseespy"
    assert marker["cases"] == [1, 2, 5]


def test_stored_results_of_another_model_are_not_offered(tmp_path: Path) -> None:
    from opensees_studio.services import load_project

    path, _job = _stored(tmp_path)
    edited = load_project(path)
    edited.nodes.append(Node(id=2, coords=(1.0, 0.0, 0.0)))

    assert batch.stored_results(path, edited) is None
    assert batch.stored_results(None, edited) is None


def test_a_new_run_retires_the_previous_marker_first(tmp_path: Path) -> None:
    from opensees_studio.services import load_project

    path, job = _stored(tmp_path)

    batch.prepare_out_dir(job)

    assert not (job.out_dir / batch.STORED_NAME).exists()
    assert batch.stored_results(path, load_project(path)) is None


# ── CLI parent ───────────────────────────────────────────────────────
def test_the_children_get_the_chosen_engine_and_its_folder(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = engines.SolverSettings(engine=engines.PYNITE, package_dir=str(tmp_path))
    monkeypatch.setattr(engines, "load_settings", lambda: settings)

    chosen = batch_cli._child_env(None)
    overridden = batch_cli._child_env(engines.OPENSEES_PY)

    assert chosen is not None and overridden is not None
    assert chosen[engines.ENGINE_KEY_ENV] == engines.PYNITE
    assert overridden[engines.ENGINE_KEY_ENV] == engines.OPENSEES_PY
    assert overridden[engines.ENGINE_PATH_ENV] == str(tmp_path)
    assert batch_cli._child_env("no-such-engine") is None


def test_an_unknown_engine_is_a_usage_error(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    code = batch_cli.main([str(tmp_path), "--engine", "no-such-engine"])
    assert code == batch_cli.EXIT_USAGE
    assert "Unknown engine" in capsys.readouterr().err


def test_only_unrunnable_files_are_skipped_without_spawning(tmp_path: Path) -> None:
    broken = tmp_path / "broken.osmodel"
    broken.write_text("{", encoding="utf-8")

    code = batch_cli.main([str(broken), "--summary", str(tmp_path / "s")])

    assert code == batch_cli.EXIT_SOME_FAILED
    payload = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert payload["counts"]["skipped"] == 1


def test_an_exit_0_is_done_even_when_cancel_came_at_the_same_moment(tmp_path: Path) -> None:
    job = batch.plan_job(_save(tmp_path / "m.osmodel"), None)
    batch.prepare_out_dir(job)
    (job.out_dir / batch.STDERR_LOG).write_text("boom\n", encoding="utf-8")

    assert batch.finish_job(job, 0, "", cancelled=True) == (batch.OK, "")
    assert (job.out_dir / batch.STORED_NAME).is_file()
    batch.prepare_out_dir(job)
    assert batch.finish_job(job, 255, "", cancelled=True) == (batch.CANCELLED, "")
    status, message = batch.finish_job(job, 255, "", cancelled=False)
    assert status == batch.FAILED
    assert message.endswith("Last output: boom")
    assert not (job.out_dir / batch.STORED_NAME).exists()


def test_cli_cancel_kills_the_running_child(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    import sys
    import threading
    import time

    job = batch.plan_job(_save(tmp_path / "m.osmodel"), None)
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    monkeypatch.setattr(batch, "job_command", lambda _job: sleeper)
    runner = batch_cli._Batch({})
    result: list[batch.BatchOutcome] = []
    worker = threading.Thread(target=lambda: result.append(runner.run_job(job)))
    worker.start()
    deadline = time.monotonic() + 10
    while not runner._live and time.monotonic() < deadline:
        time.sleep(0.05)

    runner.cancel()
    worker.join(timeout=10)

    assert not worker.is_alive()
    assert result[0].status == batch.CANCELLED
    assert runner.run_job(job).status == batch.CANCELLED  # queued after cancel: never spawned
