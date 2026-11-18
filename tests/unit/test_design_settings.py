"""``Project.design``: absent until used, round-trips, and never makes results stale."""

from __future__ import annotations

import json
from pathlib import Path

from opensees_studio.core import Project
from opensees_studio.core.combinations import model_fingerprint
from opensees_studio.core.design.settings import (
    DesignLoadSet,
    DesignSettings,
    SteelMemberDesign,
)
from opensees_studio.services import load_project, save_project


def test_a_project_without_design_saves_without_the_field(tmp_path: Path) -> None:
    path = save_project(Project(), tmp_path / "plain.osmodel")
    assert "design" not in json.loads(path.read_text(encoding="utf-8"))


def test_defaults_are_left_out_and_values_round_trip(tmp_path: Path) -> None:
    project = Project()
    project.design = DesignSettings()
    path = save_project(project, tmp_path / "empty.osmodel")
    assert json.loads(path.read_text(encoding="utf-8"))["design"] == {"code": "AISC 360-16"}

    project.design = DesignSettings(
        method="ASD",
        fy=345e6,
        load_sets=[DesignLoadSet(source="case", ref_id=1)],
        members=[SteelMemberDesign(element_id=3, shape="W14X90", length_ltb=2.0, cb=1.0)],
        drift_limit=0.015,
    )
    path = save_project(project, tmp_path / "full.osmodel")
    member = json.loads(path.read_text(encoding="utf-8"))["design"]["members"][0]
    assert member == {"element_id": 3, "shape": "W14X90", "length_ltb": 2.0, "cb": 1.0}
    assert load_project(path).design == project.design


def test_member_lookup_falls_back_to_defaults() -> None:
    settings = DesignSettings(members=[SteelMemberDesign(element_id=2, k_major=2.0)])
    assert settings.member(2).k_major == 2.0
    assert settings.member(9) == SteelMemberDesign(element_id=9)


def test_design_settings_do_not_change_the_model_fingerprint() -> None:
    project = Project()
    before = model_fingerprint(project)
    project.design = DesignSettings(fy=250e6)
    assert model_fingerprint(project) == before
