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


def test_report_carries_the_scbf_capacity_design() -> None:
    from opensees_studio.core import ElasticBeamColumn
    from opensees_studio.core.design.settings import DesignSettings
    from tests.integration.test_steel_design_run import _portal, _results

    project = _portal()
    project.elements.append(ElasticBeamColumn(id=5, nodes=(1, 3), section_id=2))
    project.analyses[0].name = "EQ"
    project.design = DesignSettings(seismic_system="SCBF")
    page = build_report(project, _results(project))
    assert "SCBF capacity design (AISC 341-22 F2.3)" in page
    assert "SCBF capacity" in page


def test_report_carries_the_scbf_beam_column_joint() -> None:
    from opensees_studio.core import ElasticBeamColumn
    from opensees_studio.core.design.settings import DesignSettings
    from tests.integration.test_steel_design_run import _portal, _results

    project = _portal()
    project.elements.append(ElasticBeamColumn(id=5, nodes=(1, 3), section_id=2))
    project.design = DesignSettings(seismic_system="SCBF")
    page = build_report(project, _results(project))
    assert "SCBF beam-to-column connections (AISC 341-22 F2.6b)" in page
    assert "simple / not checked" in page


def test_report_carries_the_column_splices() -> None:
    from opensees_studio.core import ElasticBeamColumn, Node
    from opensees_studio.core.design.column_splice_model import ColumnSplice
    from opensees_studio.core.design.settings import DesignSettings
    from tests.integration.test_steel_design_run import _portal, _results

    project = _portal()
    project.nodes.append(Node(id=5, coords=(0.0, 0.0, 288.0)))
    project.elements.append(ElasticBeamColumn(id=6, nodes=(2, 5), section_id=1))
    project.column_splices = [
        ColumnSplice(
            id=1,
            node_id=2,
            top_element_id=6,
            bottom_element_id=1,
            clear_height=144.0,
        )
    ]
    project.design = DesignSettings(seismic_system="SCBF")
    page = build_report(project, _results(project))
    assert "SCBF column splices (AISC 341-22 F2.6d)" in page
    assert "W14X99" in page


def test_report_carries_the_rbs_beam_checks() -> None:
    from opensees_studio.core.design.connections import RbsConnection
    from opensees_studio.core.design.settings import DesignSettings
    from tests.integration.test_steel_design_run import _portal, _results

    project = _portal()
    project.connections = [
        RbsConnection(id=1, beam_element_id=2, column_element_id=1, a=4.5, b=13.0, c=1.0)
    ]
    project.design = DesignSettings(seismic_system="SMF")
    page = build_report(project, _results(project))
    assert "RBS beam checks (AISC 358-22 5.7 steps 1 and 9)" in page
    assert "Vh / phi Vn" in page


def test_report_carries_the_rbs_web_connection() -> None:
    from opensees_studio.core.design.connections import RbsConnection
    from opensees_studio.core.design.settings import DesignSettings
    from tests.integration.test_steel_design_run import _portal, _results

    project = _portal()
    project.connections = [
        RbsConnection(
            id=1,
            beam_element_id=2,
            column_element_id=1,
            a=4.5,
            b=13.0,
            c=1.0,
            web_connection_type="bolted",
            web_plate_thickness=0.5,
            web_plate_height=12.0,
            web_bolt_count=4,
            web_bolt_diameter=0.75,
            web_weld_leg=0.375,
        )
    ]
    project.design = DesignSettings(seismic_system="SMF")
    page = build_report(project, _results(project))
    assert "RBS web connection (AISC 358-22 5.5)" in page
    assert "Web plate shear yielding" in page


def test_report_carries_the_chapter_j_checks() -> None:
    from opensees_studio.core.design.chapter_j_model import ChapterJCheck
    from opensees_studio.core.design.settings import DesignSettings
    from tests.integration.test_steel_design_run import _portal, _results

    project = _portal()
    project.chapter_j_checks = [
        ChapterJCheck(
            id=1,
            name="Fillet weld",
            check_type="fillet_weld",
            demand=40.0,
            fexx=70.0,
            weld_leg=0.25,
            weld_length=10.0,
        )
    ]
    project.design = DesignSettings()
    page = build_report(project, _results(project))
    assert "Connection checks (AISC 360 Chapter J)" in page
    assert "Fillet weld" in page
