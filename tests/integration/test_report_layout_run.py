"""The report of a solved model: every chapter is listed and can be left out."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.persistence import load_project
from opensees_studio.services.report import build_report, report_sections, running_text
from opensees_studio.services.report_layout import ReportOptions

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_sections_of_a_designed_frame_can_be_left_out() -> None:
    project = load_project(EXAMPLES / "steel_frame_design.osmodel")
    results = {case.id: OpenSeesRunner(project).run(case) for case in project.analyses}
    sections = report_sections(project, results)
    keys = [s.key for s in sections]
    assert keys[:3] == ["model", "materials", "sections"]
    assert "steel-frame-check-aisc-360-16" in keys
    peaks = next(k for k in keys if k.endswith("/peak-displacements-final-step"))

    page = build_report(project, results)
    assert "Steel frame check — AISC 360-16" in page and "Contents</h2>" in page
    left_out = build_report(
        project,
        results,
        options=ReportOptions(excluded=frozenset({"steel-frame-check-aisc-360-16", peaks})),
    )
    assert "Steel frame check" not in left_out
    assert left_out.count("Peak displacements (final step)") < page.count(
        "Peak displacements (final step)"
    )


def test_running_text_names_the_project() -> None:
    project = load_project(EXAMPLES / "steel_frame_design.osmodel")
    text = running_text(project, skip_first_page=False)
    assert text.header_left == project.meta.name and not text.skip_first_page
    assert text.footer_left.startswith("OpenSees Studio ")
