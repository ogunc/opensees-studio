"""Unit tests for the OpenSees script exporter.

The exporter is not a second translator: it runs the real
:class:`OpenSeesRunner` with a recorder standing in for OpenSeesPy. These
tests pin what reaches the script — the model, the analysis block when a case
is asked for, and none of the result-reading calls — and
``tests/integration/test_script_parity.py`` proves the script runs and gives
the same numbers.
"""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    TransientCase,
)
from opensees_studio.services.opensees_script import _literal, export_script


def _cantilever() -> Project:
    """A 2D cantilever with a static case, built in code so the test is self-contained."""
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, True, True, True, True, True)),
            Node(id=2, coords=(3.0, 0.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=8.333e-6)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(0.0, -1000.0, 0.0, 0.0, 0.0, 0.0))],
            )
        ],
        analyses=[StaticCase(id=1, name="Tip", n_steps=2, pattern_ids=[1])],
    )


# ─────────────────────── the model ───────────────────────
def test_the_script_builds_the_model_the_runner_builds() -> None:
    source = export_script(_cantilever(), version="1.2.3", filename="c.py")

    assert "import openseespy.opensees as ops" in source
    assert "ops.wipe()" in source
    assert "ops.model('basic', '-ndm', 2, '-ndf', 3)" in source
    assert "ops.node(1, 0.0, 0.0)" in source  # ndm=2: two coordinates
    assert "ops.element('elasticBeamColumn', 1, 1, 2, 1, 1" in source


def test_the_header_names_what_was_exported() -> None:
    source = export_script(_cantilever(), version="1.2.3", filename="c.py")

    assert "OpenSees Studio 1.2.3" in source
    assert "2 nodes, 1 elements" in source
    assert "model only" in source
    assert "python c.py" in source


def test_a_model_only_export_has_no_analysis() -> None:
    source = export_script(_cantilever())

    assert "ops.analysis(" not in source
    assert "ops.analyze(" not in source
    assert "Analysis:" not in source


# ─────────────────────── the analysis block ───────────────────────
def test_a_case_adds_its_setup_and_its_step_protocol() -> None:
    project = _cantilever()
    case = project.analyses[0]

    source = export_script(project, case)

    assert "# --- Analysis: case #1 Static 'Tip' ---" in source
    for command in ("ops.system(", "ops.numberer(", "ops.constraints(", "ops.test("):
        assert command in source, command
    assert "ops.analysis('Static')" in source
    # Two steps, one analyze call each — the runner's own protocol.
    assert source.count("ops.analyze(1)") == 2


def test_result_readers_never_reach_the_script() -> None:
    source = export_script(_cantilever(), _cantilever().analyses[0])

    for reader in ("nodeDisp", "nodeReaction", "eleForce", "eleResponse", "nodeEigenvector"):
        assert reader not in source, reader


# ─────────────────────── literal formatting ───────────────────────
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, "1"),
        (1.5, "1.5"),
        ("Path", "'Path'"),
        (np.float64(2.5), "2.5"),
        (np.int64(3), "3"),
        ((1.0, 2.0), "[1.0, 2.0]"),
        ([1, 2], "[1, 2]"),
        (np.array([1.0, 2.0]), "[1.0, 2.0]"),
    ],
)
def test_literals_are_python_source(value: object, expected: str) -> None:
    """NumPy scalars and arrays have to come out as plain Python."""
    assert _literal(value) == expected


# ─────────────────────── transient ───────────────────────
def test_a_transient_case_carries_its_timestep() -> None:
    """A regression guard: ``analyze(1)`` is rejected by OpenSees for a
    transient analysis ("insufficient args: analyze numIncr deltaT ..."), so the
    exported loop has to pass the step, exactly as the runner does."""
    project = _cantilever()
    project = project.model_copy(
        update={"analyses": [TransientCase(id=2, name="EQ", dt=0.01, n_steps=3, pattern_ids=[1])]}
    )
    case = project.analyses[0]

    source = export_script(project, case)

    assert "for _step in range(3):" in source
    assert "ops.analyze(1, 0.01)" in source


# ─────────────────────── encodable everywhere ───────────────────────
def test_the_exported_script_is_pure_ascii() -> None:
    """A downloaded script must not depend on the writer's default encoding.

    The analysis-parity test writes the script to disk. On Windows that used to
    be cp1252, and a box-drawing rule in the analysis banner made the write
    raise `UnicodeEncodeError` — CI, Windows, 2026-10-10. Plain ASCII cannot
    fail that way, in any editor or on any console.
    """
    source = export_script(_cantilever(), _cantilever().analyses[0])
    offenders = sorted({ch for ch in source if ord(ch) > 127})
    assert offenders == []
    assert source.isascii()
