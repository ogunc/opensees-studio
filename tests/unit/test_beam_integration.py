"""Beam integration rule on force/displacement beam-columns: model, file and emission."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call

import pytest
from pydantic import ValidationError

from opensees_studio.core import (
    BEAM_INTEGRATION_RULES,
    DispBeamColumn,
    ElasticSection,
    ForceBeamColumn,
    Node,
    Project,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.persistence import _project_json


def _project(*elements) -> Project:  # type: ignore[no-untyped-def]
    return Project(
        ndm=2,
        ndf=3,
        nodes=[Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6), Node(id=2, coords=(0, 3, 0))],
        sections=[ElasticSection(id=7, E=2e8, A=0.01, Iz=1e-4)],
        elements=list(elements),
    )


def test_default_rule_is_lobatto_and_is_not_written() -> None:
    el = ForceBeamColumn(id=1, nodes=(1, 2), section_id=7)
    assert el.integration == "Lobatto"
    assert "integration" not in el.model_dump()
    assert "integration" not in json.loads(_project_json(_project(el)))["elements"][0]


@pytest.mark.parametrize("cls", [ForceBeamColumn, DispBeamColumn])
def test_other_rules_round_trip_through_the_file(cls) -> None:  # type: ignore[no-untyped-def]
    el = cls(id=1, nodes=(1, 2), section_id=7, integration="Legendre", integration_points=4)
    saved = json.loads(_project_json(_project(el)))["elements"][0]
    assert saved["integration"] == "Legendre"
    assert Project.model_validate(json.loads(_project_json(_project(el)))).elements[0] == el


def test_offered_rules() -> None:
    assert BEAM_INTEGRATION_RULES == (
        "Lobatto",
        "Legendre",
        "NewtonCotes",
        "Radau",
        "Trapezoidal",
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"integration": "CompositeSimpson", "integration_points": 5},
        {"integration": "Lobatto", "integration_points": 11},
        {"integration": "Lobatto", "integration_points": 1},
        {"integration": "HingeRadau"},
    ],
)
def test_rules_and_counts_the_build_gets_wrong_are_refused(fields: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(ValidationError):
        ForceBeamColumn(id=1, nodes=(1, 2), section_id=7, **fields)


def test_lobatto_4_emits_the_expected_integration_and_element_arguments() -> None:
    ops = MagicMock()
    project = _project(
        ForceBeamColumn(id=3, nodes=(1, 2), section_id=7, integration_points=4),
        DispBeamColumn(id=4, nodes=(1, 2), section_id=7, integration="Radau", integration_points=3),
    )
    OpenSeesRunner(project, ops_module=ops).build()
    assert ops.beamIntegration.call_args_list == [
        call("Lobatto", 3, 7, 4),
        call("Radau", 4, 7, 3),
    ]
    assert ops.element.call_args_list == [
        call("forceBeamColumn", 3, 1, 2, 1, 3, "-iter", 10, 1e-12),
        call("dispBeamColumn", 4, 1, 2, 1, 4),
    ]
