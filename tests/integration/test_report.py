"""The report page built from a solved model."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.persistence import load_project
from opensees_studio.services.report import MAX_ROWS, build_report

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_report_of_a_solved_frame(tmp_path: Path) -> None:
    project = load_project(EXAMPLES / "building_3storey_diaphragm.osmodel")
    runner = OpenSeesRunner(project)
    results = [runner.run(case, results_dir=tmp_path / str(case.id)) for case in project.analyses]
    page = build_report(project, results, now=dt.datetime(2026, 1, 2, 3, 4))
    assert page.startswith("<!doctype html>") and page.endswith("</body></html>")
    assert "2026-01-02 03:04" in page
    assert project.meta.name in page
    assert "Results — " in page and "Peak displacements" in page
    assert "(supports)" in page and ">Sum<" in page


def test_report_without_results_says_so() -> None:
    project = load_project(EXAMPLES / "building_3storey_diaphragm.osmodel")
    assert "No results for the model as it is now" in build_report(project)
    assert MAX_ROWS > 0


def test_report_carries_the_steel_check_when_the_project_has_design_settings() -> None:
    project = load_project(EXAMPLES / "steel_frame_design.osmodel")
    assert project.design is not None
    results = {case.id: OpenSeesRunner(project).run(case) for case in project.analyses}
    page = build_report(project, results)
    assert "Steel frame check — AISC 360-16" in page
    assert "10 member(s) checked, 0 over the limit" in page
    assert '<td class="text">W16X31</td>' in page
    assert "Combination 1.2D+1.0W+L" in page


def test_report_leaves_the_design_out_without_settings() -> None:
    project = load_project(EXAMPLES / "building_3storey_diaphragm.osmodel")
    assert project.design is None
    assert "Steel frame check" not in build_report(project)
