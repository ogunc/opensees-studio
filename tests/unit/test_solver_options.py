"""Numberer and system of the stepped analysis cases: model, file, emission."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest
from pydantic import ValidationError

from opensees_studio.core import (
    NUMBERERS,
    SYSTEM_ARGS,
    SYSTEM_NOTES,
    SYSTEMS,
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    PushoverCase,
    StaticCase,
    TransientCase,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.persistence import _project_json, load_project


def _project(case) -> Project:  # type: ignore[no-untyped-def]
    return Project(
        ndm=2,
        ndf=3,
        nodes=[Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6), Node(id=2, coords=(0, 3, 0))],
        sections=[ElasticSection(id=1, E=2e8, A=0.01, Iz=1e-4)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(1.0, 0, 0, 0, 0, 0))],
            )
        ],
        analyses=[case],
    )


def _run(case) -> MagicMock:  # type: ignore[no-untyped-def]
    ops = MagicMock()
    ops.analyze.return_value = 0
    ops.nodeDisp.return_value = 0.0
    ops.nodeReaction.return_value = 0.0
    ops.eleResponse.return_value = [0.0] * 6
    OpenSeesRunner(_project(case), ops_module=ops).run(case)
    return ops


def test_offered_options() -> None:
    assert NUMBERERS == ("Plain", "RCM", "AMD")
    assert SYSTEMS == (
        "BandGeneral",
        "BandSPD",
        "ProfileSPD",
        "SparseGeneral",
        "UmfPack",
        "FullGeneral",
    )
    # -piv is not offered: the build ignores it and always pivots
    assert SYSTEM_ARGS == {}
    assert SYSTEM_NOTES == {"SparseGeneral": "partial pivoting is always on in this build"}


def test_default_case_is_unchanged_in_the_file_and_in_the_commands() -> None:
    case = StaticCase(id=1, pattern_ids=[1])
    assert (case.numberer, case.system, case.system_args) == ("RCM", "BandGeneral", ())
    saved = json.loads(_project_json(_project(case)))["analyses"][0]
    assert "numberer" not in saved and "system_args" not in saved
    ops = _run(case)
    assert ops.system.call_args_list == [call("BandGeneral")]
    assert ops.numberer.call_args_list == [call("RCM")]


def test_plain_and_sparse_general_emit_exactly_those_commands() -> None:
    case = StaticCase(id=1, pattern_ids=[1], numberer="Plain", system="SparseGeneral")
    ops = _run(case)
    assert ops.system.call_args_list == [call("SparseGeneral")]
    assert ops.numberer.call_args_list == [call("Plain")]
    saved = json.loads(_project_json(_project(case)))["analyses"][0]
    assert saved["numberer"] == "Plain" and "system_args" not in saved
    assert Project.model_validate(json.loads(_project_json(_project(case)))).analyses[0] == case


def test_a_saved_piv_loads_with_a_notice_and_runs_without_it(tmp_path: Path) -> None:
    case = StaticCase(id=7, pattern_ids=[1], numberer="Plain", system="SparseGeneral")
    payload = json.loads(_project_json(_project(case)))
    payload["analyses"][0]["system_args"] = ["-piv"]
    path = tmp_path / "piv.osmodel"
    path.write_text(json.dumps(payload), encoding="utf-8")

    notices: list[str] = []
    loaded = load_project(path, on_notice=notices.append).analyses[0]
    assert loaded == case and loaded.system_args == ()
    assert notices == [
        "Analysis case 7: system SparseGeneral -piv is not offered (partial pivoting is "
        "always on in this build); running without -piv."
    ]
    ops = _run(loaded)
    assert ops.system.call_args_list == [call("SparseGeneral")]


def test_pushover_and_transient_cases_emit_their_numberer_and_system() -> None:
    push = PushoverCase(
        id=1,
        pattern_ids=[1],
        control_node=2,
        control_dof=1,
        target_disp=0.002,
        step_size=0.001,
        numberer="AMD",
        system="UmfPack",
    )
    ops = _run(push)
    assert (
        call("AMD") in ops.numberer.call_args_list and call("UmfPack") in ops.system.call_args_list
    )
    transient = TransientCase(
        id=1, pattern_ids=[1], dt=0.01, n_steps=2, numberer="Plain", system="FullGeneral"
    )
    assert TransientCase.model_validate(transient.model_dump()) == transient
    ops = MagicMock()
    OpenSeesRunner(_project(transient), ops_module=ops)._setup_analysis(transient)
    assert ops.numberer.call_args_list == [call("Plain")]
    assert ops.system.call_args_list == [call("FullGeneral")]


@pytest.mark.parametrize(
    "fields",
    [
        {"numberer": "Bogus"},
        {"system": "BandGeneral", "system_args": ("-piv",)},
        {"system": "SparseGeneral", "system_args": ("-foo",)},
        pytest.param(
            {"system": "SparseGeneral", "system_args": ("-piv", "-foo")},
            marks=pytest.mark.filterwarnings("ignore:Analysis case 1"),  # -piv dropped first
        ),
    ],
)
def test_options_the_build_would_ignore_or_refuse_are_refused(fields: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(ValidationError):
        StaticCase(id=1, pattern_ids=[1], **fields)
