"""ImposedSupportMotionPattern — model validation + runner command emission.

The emission tests inject a ``MagicMock`` as the ops module (the
``test_runner_translation.py`` pattern); the physics itself is verified in
``tests/integration/test_runner_imposed_motion.py`` against a uniform-
excitation reference.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from opensees_studio.core import (
    ElasticUniaxial,
    ImposedSupportMotionPattern,
    Node,
    PathTimeSeries,
    Project,
    ZeroLengthElement,
)
from opensees_studio.services.opensees_runner import (
    _IMPOSED_VEL_TS_OFFSET,
    OpenSeesRunner,
)


def _project(**overrides) -> Project:  # type: ignore[no-untyped-def]
    """Grounded zeroLength + mass node, disp record on the support's X."""
    defaults = dict(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(
                id=2,
                coords=(0, 0, 0),
                restraint=(False, True, True, True, True, True),
                mass=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            ),
        ],
        materials=[ElasticUniaxial(id=1, E=100.0)],
        elements=[
            ZeroLengthElement(
                id=1,
                nodes=(1, 2),
                material_ids=(1,),
                dofs=(1,),
            )
        ],
        time_series=[
            PathTimeSeries(id=1, dt=0.1, values=[0.0, 1.0, 4.0, 9.0, 16.0]),
        ],
        load_patterns=[
            ImposedSupportMotionPattern(
                id=7,
                direction=1,
                disp_series_id=1,
                node_ids=[1],
            )
        ],
    )
    defaults.update(overrides)
    return Project(**defaults)


# ───────────────────────── model / references ─────────────────────────
def test_round_trip_preserves_pattern() -> None:
    project = _project()
    clone = Project.model_validate(project.model_dump())
    pat = clone.load_patterns[0]
    assert isinstance(pat, ImposedSupportMotionPattern)
    assert pat.direction == 1
    assert pat.disp_series_id == 1
    assert pat.node_ids == [1]


def test_validate_references_missing_series_and_node() -> None:
    project = _project()
    project.load_patterns[0].disp_series_id = 99
    with pytest.raises(ValueError, match="missing time series 99"):
        project.validate_references()

    project = _project()
    project.load_patterns[0].node_ids = [42]
    with pytest.raises(ValueError, match="drives missing node 42"):
        project.validate_references()


# ───────────────────────── emission ─────────────────────────
def _emit(project: Project) -> MagicMock:
    ops = MagicMock()
    runner = OpenSeesRunner(project, ops_module=ops)
    runner._emit_patterns_for_case([7])
    return ops


def test_emission_sequence() -> None:
    ops = _emit(_project())

    # Derived velocity series: central differences of the disp record.
    ts_calls = ops.timeSeries.call_args_list
    assert ts_calls[0].args[:2] == ("Path", 1)  # the disp record itself
    kind, tag, flag_dt, dt, flag_vals, *rest = ts_calls[1].args
    assert (kind, tag, flag_dt, dt, flag_vals) == (
        "Path",
        _IMPOSED_VEL_TS_OFFSET + 7,
        "-dt",
        0.1,
        "-values",
    )
    vel = rest[: rest.index("-factor")]
    expected = np.gradient(np.array([0.0, 1.0, 4.0, 9.0, 16.0]), 0.1)
    assert np.allclose(vel, expected)

    # The X fix is swapped for the imposed motion, then the pattern lands.
    ops.remove.assert_called_once_with("sp", 1, 1)
    ops.pattern.assert_called_once_with("MultipleSupport", 7)
    ops.groundMotion.assert_called_once_with(
        7,
        "Plain",
        "-disp",
        1,
        "-vel",
        _IMPOSED_VEL_TS_OFFSET + 7,
        "-fact",
        1.0,
    )
    ops.imposedMotion.assert_called_once_with(1, 1, 7)


def test_emission_order_fix_removed_before_pattern() -> None:
    ops = _emit(_project())
    names = [c[0] for c in ops.method_calls]
    assert names.index("remove") < names.index("pattern")
    assert names.index("pattern") < names.index("groundMotion")
    assert names.index("groundMotion") < names.index("imposedMotion")


def test_unrestrained_node_rejected() -> None:
    project = _project()
    project.nodes[0].restraint = (False, True, True, True, True, True)
    with pytest.raises(ValueError, match="must be restrained in direction 1"):
        _emit(project)


def test_non_dt_path_series_rejected() -> None:
    project = _project(
        time_series=[
            PathTimeSeries(
                id=1,
                times=[0.0, 0.1, 0.3],
                values=[0.0, 1.0, 4.0],
            )
        ]
    )
    with pytest.raises(ValueError, match="PathTimeSeries with uniform"):
        _emit(project)


def test_vel_tag_collision_rejected() -> None:
    project = _project()
    project.time_series.append(PathTimeSeries(id=_IMPOSED_VEL_TS_OFFSET + 7, dt=0.1, values=[0.0]))
    with pytest.raises(ValueError, match="collides with an existing time series"):
        _emit(project)


def test_direction_beyond_ndf_rejected() -> None:
    project = _project(
        ndm=2,
        ndf=2,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True, True, False, False, False, False)),
            Node(
                id=2,
                coords=(0, 0, 0),
                restraint=(False, True, False, False, False, False),
                mass=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            ),
        ],
        load_patterns=[
            ImposedSupportMotionPattern(
                id=7,
                direction=3,
                disp_series_id=1,
                node_ids=[1],
            )
        ],
    )
    with pytest.raises(ValueError, match="exceeds ndf=2"):
        _emit(project)
