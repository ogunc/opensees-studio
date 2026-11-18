"""Project information: the report cover data and its round-trip."""

from __future__ import annotations

import json
from pathlib import Path

from opensees_studio.core import Project
from opensees_studio.core.project import ProjectMeta, Revision
from opensees_studio.services import load_project, save_project
from opensees_studio.services.report import build_report


def test_project_information_round_trips(tmp_path: Path) -> None:
    project = Project()
    project.meta = ProjectMeta(
        name="Steel tower",
        description="Ten-storey braced frame",
        author="A. Engineer",
        company="ACME Structures",
        date="2026-11-05",
        revisions=[
            Revision(code="A", date="2026-11-01", by="A. Engineer", description="Issued"),
            Revision(code="B", date="2026-11-05", by="B. Checker", description="Panel zone"),
        ],
    )
    path = save_project(project, tmp_path / "info.osmodel")
    saved = json.loads(path.read_text(encoding="utf-8"))["meta"]
    assert saved["company"] == "ACME Structures"
    assert saved["revisions"][1]["code"] == "B"
    assert load_project(path).meta == project.meta


def test_a_plain_project_saves_no_cover_fields(tmp_path: Path) -> None:
    path = save_project(Project(), tmp_path / "plain.osmodel")
    meta = json.loads(path.read_text(encoding="utf-8"))["meta"]
    assert "company" not in meta
    assert "date" not in meta
    assert "revisions" not in meta


def test_the_report_cover_carries_the_information() -> None:
    project = Project()
    project.meta = ProjectMeta(
        name="Steel tower",
        author="A. Engineer",
        company="ACME Structures",
        date="2026-11-05",
        revisions=[Revision(code="A", date="2026-11-01", by="AE", description="Issued")],
    )
    page = build_report(project)
    assert "ACME Structures" in page
    assert "2026-11-05" in page
    assert "Issued" in page
