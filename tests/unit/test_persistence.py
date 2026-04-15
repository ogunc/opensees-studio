"""Unit tests for the persistence service — JSON round-trip."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from opensees_studio.core import (
    Concrete02,
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    Steel01,
    TrussElement,
    UnitSystem,
)
from opensees_studio.services import PROJECT_FILE_SUFFIX, load_project, save_project


def _sample_project() -> Project:
    return Project(
        meta=ProjectMeta(name="Sample", author="Ozan", units=UnitSystem.SI_M_N),
        ndm=3, ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(id=2, coords=(0, 0, 3.0)),
        ],
        materials=[
            Steel01(id=1, Fy=420e6, E0=200e9, b=0.01),
            Concrete02(
                id=2, fpc=-30e6, epsc0=-0.002, fpcu=-15e6, epsU=-0.005,
                ft=3e6, Ets=2e9, **{"lambda": 0.1},
            ),
        ],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=8.33e-6, Iy=8.33e-6, G=80e9, J=1e-6)],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1, geom_transf="PDelta"),
            TrussElement(id=2, nodes=(1, 2), area=1e-3, material_id=1),
        ],
        time_series=[LinearTimeSeries(id=1, factor=1.0)],
        load_patterns=[
            PlainLoadPattern(
                id=1, time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(0, 0, -10e3, 0, 0, 0))],
            )
        ],
    )


def test_round_trip_preserves_everything(tmp_path: Path) -> None:
    original = _sample_project()
    target = save_project(original, tmp_path / "model")
    assert target.suffix == PROJECT_FILE_SUFFIX
    assert target.exists()

    restored = load_project(target)
    assert restored.model_dump(by_alias=True) == original.model_dump(by_alias=True)


def test_save_appends_suffix_when_missing(tmp_path: Path) -> None:
    p = Project()
    out = save_project(p, tmp_path / "no_extension")
    assert out.suffix == PROJECT_FILE_SUFFIX


def test_save_keeps_existing_suffix(tmp_path: Path) -> None:
    p = Project()
    out = save_project(p, tmp_path / "with_ext.osmodel")
    assert out.name == "with_ext.osmodel"


def test_load_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_project("/no/such/path/x.osmodel")


def test_load_corrupt_file_raises_validation_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.osmodel"
    bad.write_text('{"ndm": 2, "ndf": 6}', encoding="utf-8")  # invalid combo
    with pytest.raises(ValidationError):
        load_project(bad)


def test_polymorphic_collection_dispatches_correctly(tmp_path: Path) -> None:
    """Materials list must restore as Steel01 + Concrete02 — not generic Entity."""
    original = _sample_project()
    out = save_project(original, tmp_path / "x")
    restored = load_project(out)
    assert isinstance(restored.materials[0], Steel01)
    assert isinstance(restored.materials[1], Concrete02)
    assert isinstance(restored.elements[0], ElasticBeamColumn)
    assert isinstance(restored.elements[1], TrussElement)
