"""Save As into a sibling folder keeps a record-backed transient runnable."""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.services import load_project, save_project
from opensees_studio.services.opensees_runner import OpenSeesRunner
from tests.integration._record_files import copy_record_files


def test_record_backed_project_saved_to_a_sibling_folder_reopens_and_runs(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from examples.ex1a_canti2d_eq import build_ex1a_canti2d_eq

    original = tmp_path / "proj" / "ex1a.osmodel"
    save_project(build_ex1a_canti2d_eq(), original)
    copy_record_files(load_project(original), original.parent)

    # File > Save As: open from proj/, save into the sibling folder other/.
    project = load_project(original)
    moved = save_project(project, tmp_path / "other" / "ex1a.osmodel", previous_path=original)
    assert not (moved.parent / "data").exists()  # the record was not copied along

    reopened = load_project(moved)
    rec = reopened.ground_motions[0]
    assert rec.source_path == "../proj/data/A10000.txt"
    assert rec.status == "ok"
    assert rec.content_hash == project.ground_motions[0].content_hash
    reopened.validate_references()

    case = reopened.analyses[1].model_copy(update={"n_steps": 200})
    results_dir = tmp_path / "results"
    result = OpenSeesRunner(reopened).run(case, results_dir=results_dir)

    assert len(result.time()) == 200
    assert abs(result.node_disp_history(2)[:, 0]).max() > 0.0
