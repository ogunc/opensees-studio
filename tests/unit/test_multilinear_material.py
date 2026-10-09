"""MultiLinear uniaxial material: validation, file round trip and emitted command."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest
from pydantic import ValidationError

from opensees_studio.core import MultiLinear, Project
from opensees_studio.services.opensees_runner import OpenSeesRunner

POINTS = [(0.001, 1.0), (0.002, 1.5), (0.004, 2.0)]


def test_the_emitted_command_has_strain_first() -> None:
    ops = MagicMock()
    OpenSeesRunner(
        Project(ndm=2, ndf=2, materials=[MultiLinear(id=4, points=POINTS)]), ops_module=ops
    ).build()
    assert ops.uniaxialMaterial.call_args_list == [
        call("MultiLinear", 4, 0.001, 1.0, 0.002, 1.5, 0.004, 2.0)
    ]


def test_round_trip_through_the_project_file() -> None:
    project = Project(ndm=2, ndf=2, materials=[MultiLinear(id=3, name="shear", points=POINTS)])
    text = project.model_dump_json(by_alias=True)
    assert '"type":"MultiLinear"' in text
    again = Project.model_validate_json(text)
    assert again.materials == project.materials
    assert isinstance(again.materials[0], MultiLinear)


@pytest.mark.parametrize(
    "points",
    [
        [],
        [(0.001, 1.0)],
        [(0.0, 1.0), (0.002, 1.5)],
        [(-0.001, 1.0), (0.002, 1.5)],
        [(0.002, 1.0), (0.002, 1.5)],
        [(0.002, 1.0), (0.001, 1.5)],
        [(0.001, 0.0), (0.002, 1.5)],
        [(0.001, 1.0), (0.002, -1.5)],
    ],
    ids=["empty", "one", "zero", "negative", "equal", "falling", "zero_stress", "neg_stress"],
)
def test_validation(points: list[tuple[float, float]]) -> None:
    with pytest.raises(ValidationError):
        MultiLinear(id=1, points=points)
