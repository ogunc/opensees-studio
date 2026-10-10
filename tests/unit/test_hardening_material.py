"""Hardening uniaxial material: validation, file round trip and emitted command."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest
from pydantic import ValidationError

from opensees_studio.core import Hardening, Project
from opensees_studio.services.material_tester import SUPPORTED_MATERIALS, _emit_uniaxial
from opensees_studio.services.opensees_runner import OpenSeesRunner

# The Nonlinear Truss example (alpha 0.05): the parameters the campaign recorded.
SOURCE = {"E": 29000.0, "sigmaY": 36.0, "H_iso": 0.0, "H_kin": 1526.3157894736842}


def test_source_parameters_and_the_emitted_command() -> None:
    mat = Hardening(id=1, **SOURCE)
    assert mat.eta == 0.0
    ops = MagicMock()
    OpenSeesRunner(Project(ndm=2, ndf=2, materials=[mat]), ops_module=ops).build()
    assert ops.uniaxialMaterial.call_args_list == [
        call("Hardening", 1, 29000.0, 36.0, 0.0, 1526.3157894736842)
    ]


def test_eta_is_written_only_when_set() -> None:
    ops = MagicMock()
    _emit_uniaxial(ops, Hardening(id=2, **SOURCE, eta=0.5))
    assert ops.uniaxialMaterial.call_args == call(
        "Hardening", 2, 29000.0, 36.0, 0.0, 1526.3157894736842, 0.5
    )
    assert Hardening in SUPPORTED_MATERIALS


def test_round_trip_through_the_project_file() -> None:
    project = Project(ndm=2, ndf=2, materials=[Hardening(id=3, name="truss steel", **SOURCE)])
    again = Project.model_validate_json(project.model_dump_json(by_alias=True))
    assert again.materials == project.materials


@pytest.mark.parametrize(
    "bad",
    [
        {"E": 0.0},
        {"sigmaY": -36.0},
        {"H_iso": -1.0},
        {"H_kin": -1.0},
        {"eta": -0.1},
    ],
)
def test_validation(bad: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(ValidationError):
        Hardening(id=1, **{**SOURCE, **bad})
