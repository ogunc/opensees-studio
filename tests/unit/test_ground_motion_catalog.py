"""Project ground-motion catalog: migration, hydration, sidecars, refusal.

The catalog rulings under test:

* records are referenced by relative path + content hash, never embedded
  in ``.osmodel``;
* legacy embedded series migrate only when their source is identified
  with certainty, and the re-read values must equal the embedded ones;
* an unresolvable legacy source keeps its values in memory
  (``pending_sidecar``) - loading never writes files, the first save
  writes the sidecar losslessly and never overwrites different content;
* a missing or changed record file flags the entry and analysis refuses
  to run the case, but the project still loads.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from opensees_studio.core import (
    GroundMotionRecord,
    PathTimeSeries,
    Project,
    UniformExcitationPattern,
    content_hash_of_file,
    import_record,
)
from opensees_studio.services.persistence import load_project, save_project

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

VALUES = [0.0, 0.1, -0.25, 0.3, -0.15, 0.05, -0.325, 0.2]
DT = 0.01


def _write_record_file(path: Path, values: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(repr(v) for v in values) + "\n")


def _legacy_project_payload(file_path: str | None) -> dict:
    """A minimal v1-style payload: embedded Path series + excitation pattern."""
    project = Project(
        time_series=[
            PathTimeSeries(id=1, name="Motion", dt=DT, values=VALUES, file_path=file_path)
        ],
        load_patterns=[UniformExcitationPattern(id=1, direction=1, accel_series_id=1)],
    )
    payload = project.model_dump(mode="json", by_alias=True)
    payload["schema_version"] = 1
    del payload["ground_motions"]
    del payload["time_series"][0]["record_id"]
    return payload


def _snapshot(tree: Path) -> set[Path]:
    return {p for p in tree.rglob("*") if p.is_file()}


# ─────────────────────── migration: certain source ───────────────────────
def test_legacy_series_with_resolvable_file_migrates(tmp_path) -> None:
    _write_record_file(tmp_path / "data" / "motion.txt", VALUES)
    src = tmp_path / "proj.osmodel"
    src.write_text(json.dumps(_legacy_project_payload("motion.txt")))

    notices: list[str] = []
    project = load_project(src, on_notice=notices.append)

    assert len(project.ground_motions) == 1
    rec = project.ground_motions[0]
    assert rec.source_path == "data/motion.txt"
    assert rec.status == "ok"
    assert rec.content_hash == content_hash_of_file(tmp_path / "data" / "motion.txt")
    assert rec.npts == len(VALUES)
    ts = project.time_series[0]
    assert ts.record_id == rec.id
    # Condition: values re-read from the identified source must equal the
    # previously embedded values within floating tolerance.
    assert np.allclose(ts.values, VALUES, rtol=1e-12, atol=0.0)
    assert any("migrated" in n.lower() for n in notices)


def test_example_osmodel_migrates_into_catalog(tmp_path) -> None:
    """A copy of a real example project (ex1a EQ + A10000 record) migrates."""
    example = EXAMPLES / "ex1a_canti2d_eq.osmodel"
    hydrated = load_project(example)  # valid in either schema form
    embedded_values = next(
        ts for ts in hydrated.time_series if isinstance(ts, PathTimeSeries)
    ).values
    assert embedded_values, "example record must hydrate from examples/data"

    # Downgrade to the v1 embedded form and reload from a copy.
    payload = hydrated.model_dump(mode="json", by_alias=True)
    payload["schema_version"] = 1
    payload.pop("ground_motions", None)
    for ts in payload["time_series"]:
        if ts["type"] == "Path":
            ts.pop("record_id", None)
            ts["file_path"] = "A10000.txt"
            ts["values"] = embedded_values
    (tmp_path / "data").mkdir()
    data = (EXAMPLES / "data" / "A10000.txt").read_bytes()
    (tmp_path / "data" / "A10000.txt").write_bytes(data)
    legacy = tmp_path / "legacy.osmodel"
    legacy.write_text(json.dumps(payload))

    project = load_project(legacy)
    assert len(project.ground_motions) == 1
    rec = project.ground_motions[0]
    assert rec.status == "ok"
    assert rec.source_path == "data/A10000.txt"
    assert rec.npts == 7990
    migrated_ts = next(t for t in project.time_series if isinstance(t, PathTimeSeries))
    assert migrated_ts.record_id == rec.id
    assert np.allclose(migrated_ts.values, embedded_values, rtol=1e-12, atol=0.0)


def test_generated_pseudo_path_stays_embedded(tmp_path) -> None:
    src = tmp_path / "proj.osmodel"
    src.write_text(json.dumps(_legacy_project_payload("generated:sine-wave")))

    project = load_project(src)
    assert project.ground_motions == []
    ts = project.time_series[0]
    assert ts.record_id is None
    assert ts.values == pytest.approx(VALUES)

    out = save_project(project, tmp_path / "resaved.osmodel")
    resaved = json.loads(out.read_text())
    assert resaved["time_series"][0]["values"] == pytest.approx(VALUES)


def test_value_mismatch_leaves_series_embedded(tmp_path) -> None:
    """A file that does not reproduce the embedded values is not the source."""
    _write_record_file(tmp_path / "motion.txt", [v * 2.0 for v in VALUES])
    src = tmp_path / "proj.osmodel"
    src.write_text(json.dumps(_legacy_project_payload("motion.txt")))

    notices: list[str] = []
    project = load_project(src, on_notice=notices.append)
    assert project.ground_motions == []
    assert project.time_series[0].record_id is None
    assert project.time_series[0].values == pytest.approx(VALUES)
    assert any("does not match" in n for n in notices)


def test_dt_disagreement_stops_migration(tmp_path) -> None:
    at2 = tmp_path / "motion.txt"
    body = "  ".join(repr(v) for v in VALUES)
    at2.write_text(f"{len(VALUES)} 0.02 NPTS, DT\n{body}\n")
    src = tmp_path / "proj.osmodel"
    src.write_text(json.dumps(_legacy_project_payload("motion.txt")))

    with pytest.raises(ValueError, match=r"dt=0\.01.*declares dt=0\.02"):
        load_project(src)


# ─────────────────────── new-form save/load round trip ───────────────────────
def test_save_drops_values_and_reload_restores(tmp_path) -> None:
    _write_record_file(tmp_path / "data" / "motion.txt", VALUES)
    rec, values = import_record(
        tmp_path / "data" / "motion.txt",
        base_dir=tmp_path,
        record_id=1,
        name="Motion",
        format="single_column",
        dt=DT,
    )
    project = Project(
        ground_motions=[rec],
        time_series=[PathTimeSeries(id=1, name="Motion", dt=DT, values=values, record_id=1)],
        load_patterns=[UniformExcitationPattern(id=1, direction=1, accel_series_id=1)],
    )

    out = save_project(project, tmp_path / "proj.osmodel")
    payload = json.loads(out.read_text())
    assert payload["schema_version"] == 2
    assert "values" not in payload["time_series"][0], "record values must not be embedded"
    assert payload["ground_motions"][0]["content_hash"] == rec.content_hash

    restored = load_project(out)
    assert restored.time_series[0].values == values
    assert restored.ground_motions[0].status == "ok"
    # Analysis pre-check passes for a healthy record.
    restored.check_ground_motion_records([1])


# ─────────────────────── missing / changed files ───────────────────────
def _record_backed_project(tmp_path: Path) -> Path:
    _write_record_file(tmp_path / "data" / "motion.txt", VALUES)
    rec, values = import_record(
        tmp_path / "data" / "motion.txt", base_dir=tmp_path, record_id=1, dt=DT
    )
    project = Project(
        ground_motions=[rec],
        time_series=[PathTimeSeries(id=1, dt=DT, values=values, record_id=1)],
        load_patterns=[UniformExcitationPattern(id=1, direction=1, accel_series_id=1)],
    )
    return save_project(project, tmp_path / "proj.osmodel")


def test_missing_file_warns_and_analysis_refuses(tmp_path) -> None:
    out = _record_backed_project(tmp_path)
    (tmp_path / "data" / "motion.txt").unlink()

    notices: list[str] = []
    project = load_project(out, on_notice=notices.append)  # loads, no crash
    rec = project.ground_motions[0]
    assert rec.status == "missing"
    assert project.time_series[0].values == []
    assert any("not found" in n for n in notices)

    with pytest.raises(ValueError, match="file not found") as exc:
        project.check_ground_motion_records([1])
    assert "motion" in str(exc.value)
    assert "data/motion.txt" in str(exc.value)


def test_hash_mismatch_warns_and_analysis_refuses(tmp_path) -> None:
    out = _record_backed_project(tmp_path)
    _write_record_file(tmp_path / "data" / "motion.txt", [v + 0.5 for v in VALUES])

    notices: list[str] = []
    project = load_project(out, on_notice=notices.append)
    assert project.ground_motions[0].status == "hash_mismatch"
    assert project.time_series[0].values == []
    assert any("hash mismatch" in n for n in notices)

    with pytest.raises(ValueError, match=r"changed on disk"):
        project.check_ground_motion_records([1])


# ─────────────────────── path separators ───────────────────────
def test_nested_record_path_is_stored_with_forward_slashes(tmp_path) -> None:
    record_file = tmp_path / "data" / "set 1" / "motion.txt"
    _write_record_file(record_file, VALUES)
    rec, _values = import_record(
        record_file, base_dir=tmp_path, record_id=1, format="single_column", dt=DT
    )
    assert rec.source_path == "data/set 1/motion.txt"


@pytest.mark.parametrize("producer", ["import", "migration"])
def test_windows_relpath_is_stored_with_forward_slashes(tmp_path, monkeypatch, producer) -> None:
    """``os.path.relpath`` returns backslashes on Windows; the catalog stores
    forward slashes whichever platform produced the path."""
    _write_record_file(tmp_path / "data" / "motion.txt", VALUES)
    real_relpath = os.path.relpath
    monkeypatch.setattr(
        os.path, "relpath", lambda p, start=None: real_relpath(p, start).replace("/", "\\")
    )
    if producer == "import":
        rec, _values = import_record(
            tmp_path / "data" / "motion.txt",
            base_dir=tmp_path,
            record_id=1,
            format="single_column",
            dt=DT,
        )
    else:
        src = tmp_path / "proj.osmodel"
        src.write_text(json.dumps(_legacy_project_payload("motion.txt")))
        rec = load_project(src).ground_motions[0]
    assert rec.source_path == "data/motion.txt"


def test_backslash_source_path_from_an_older_windows_save_loads(tmp_path) -> None:
    out = _record_backed_project(tmp_path)
    payload = json.loads(out.read_text())
    payload["ground_motions"][0]["source_path"] = "data\\motion.txt"
    out.write_text(json.dumps(payload))

    project = load_project(out)
    rec = project.ground_motions[0]
    assert rec.status == "ok"
    assert rec.source_path == "data/motion.txt"
    assert project.time_series[0].values == pytest.approx(VALUES)
    resaved = json.loads(save_project(project, out).read_text())
    assert resaved["ground_motions"][0]["source_path"] == "data/motion.txt"


def test_legacy_backslash_file_path_resolves_for_migration(tmp_path) -> None:
    _write_record_file(tmp_path / "data" / "motion.txt", VALUES)
    src = tmp_path / "proj.osmodel"
    src.write_text(json.dumps(_legacy_project_payload("data\\motion.txt")))

    rec = load_project(src).ground_motions[0]
    assert rec.status == "ok"
    assert rec.source_path == "data/motion.txt"


def test_record_model_accepts_either_separator() -> None:
    rec = GroundMotionRecord(
        id=1, source_path="data\\set\\x.AT2", format="peer_at2", dt=0.01, npts=10
    )
    assert rec.source_path == "data/set/x.AT2"
    rec.source_path = "..\\records\\y.AT2"  # assignment is validated too
    assert rec.source_path == "../records/y.AT2"


# ─────────────────────── pending sidecar ───────────────────────
def test_unresolvable_source_defers_to_sidecar_on_save(tmp_path) -> None:
    src = tmp_path / "proj.osmodel"
    src.write_text(json.dumps(_legacy_project_payload("lost-forever.txt")))
    before = _snapshot(tmp_path)

    notices: list[str] = []
    project = load_project(src, on_notice=notices.append)

    # Loading never writes files; the values stay in memory.
    assert _snapshot(tmp_path) == before
    rec = project.ground_motions[0]
    assert rec.status == "pending_sidecar"
    assert rec.content_hash == ""
    assert project.time_series[0].values == pytest.approx(VALUES)
    # Runnable: the legacy values are still in memory.
    project.check_ground_motion_records([1])

    # First save writes the sidecar and heals the entry.
    save_notices: list[str] = []
    out = save_project(project, src, on_notice=save_notices.append)
    sidecar = tmp_path / "proj.records" / "Motion.txt"
    assert sidecar.is_file()
    assert rec.status == "ok"
    assert rec.source_path == "proj.records/Motion.txt"
    assert rec.content_hash == content_hash_of_file(sidecar)
    assert any("proj.records" in n and "Motion.txt" in n for n in save_notices)

    payload = json.loads(out.read_text())
    assert "values" not in payload["time_series"][0]

    # Lossless round trip: reloaded values are bit-identical.
    restored = load_project(out)
    assert restored.time_series[0].values == project.time_series[0].values
    assert restored.time_series[0].values == VALUES


def test_sidecar_never_overwrites_different_content(tmp_path) -> None:
    src = tmp_path / "proj.osmodel"
    src.write_text(json.dumps(_legacy_project_payload("lost-forever.txt")))
    conflicting = tmp_path / "proj.records" / "Motion.txt"
    conflicting.parent.mkdir()
    conflicting.write_text("something else entirely\n")

    project = load_project(src)
    save_project(project, src)

    assert conflicting.read_text() == "something else entirely\n"
    numbered = tmp_path / "proj.records" / "Motion_2.txt"
    assert numbered.is_file()
    assert project.ground_motions[0].source_path == "proj.records/Motion_2.txt"


def test_sidecar_with_identical_content_is_reused(tmp_path) -> None:
    src = tmp_path / "proj.osmodel"
    src.write_text(json.dumps(_legacy_project_payload("lost-forever.txt")))
    existing = tmp_path / "proj.records" / "Motion.txt"
    existing.parent.mkdir()
    existing.write_text("\n".join(repr(v) for v in VALUES) + "\n")

    project = load_project(src)
    save_project(project, src)

    assert project.ground_motions[0].source_path == "proj.records/Motion.txt"
    assert not (tmp_path / "proj.records" / "Motion_2.txt").exists()


# ─────────────────────── model guards ───────────────────────
def test_plain_path_series_still_requires_values() -> None:
    with pytest.raises(ValueError, match="requires values"):
        PathTimeSeries(id=1, dt=0.01, values=[])


def test_series_referencing_unknown_record_fails_validation() -> None:
    project = Project(
        time_series=[PathTimeSeries(id=1, dt=0.01, values=[0.1], record_id=99)],
    )
    with pytest.raises(ValueError, match="missing ground-motion record 99"):
        project.validate_references()


def test_first_save_reanchors_absolute_record_path(tmp_path: Path) -> None:
    """An import into a never-saved project stores an absolute path; the
    first save makes it relative to the project file and the reload
    hydrates the series through that relative reference."""
    record_file = tmp_path / "records" / "pulse.txt"
    _write_record_file(record_file, VALUES)
    record, values = import_record(
        record_file, base_dir=None, record_id=1, name="Pulse", format="single_column", dt=DT
    )
    assert Path(record.source_path).is_absolute()
    project = Project(
        ground_motions=[record],
        time_series=[PathTimeSeries(id=1, dt=DT, values=values, record_id=1)],
        load_patterns=[UniformExcitationPattern(id=1, direction=1, accel_series_id=1)],
    )

    notices: list[str] = []
    out = save_project(project, tmp_path / "proj" / "model.osmodel", on_notice=notices.append)
    assert project.ground_motions[0].source_path == "../records/pulse.txt"
    payload = json.loads(out.read_text())
    assert payload["ground_motions"][0]["source_path"] == "../records/pulse.txt"
    assert "values" not in payload["time_series"][0]
    assert any("made relative" in n and "Pulse" in n for n in notices)

    restored = load_project(out)
    assert restored.ground_motions[0].status == "ok"
    assert restored.time_series[0].values == pytest.approx(VALUES)

    # a second save is a no-op for the path (already relative)
    save_project(restored, out, on_notice=notices.append)
    assert restored.ground_motions[0].source_path == "../records/pulse.txt"
    assert sum("made relative" in n for n in notices) == 1
