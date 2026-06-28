"""Translation tests for OpenSeesRunner.

These tests inject a ``Mock()`` as the ``ops`` module and assert that
the runner emits the correct command sequence — no real OpenSees
needed. The companion ``test_runner_static.py`` etc. exercise the
solver with a real ``ops`` for analytical verification.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticIsotropic,
    ElasticSection,
    EqualDOFConstraint,
    HystereticSM,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    Steel01,
    TrussElement,
    ZeroLengthElement,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner, _dof_indices


# ───────────────────────── helpers ─────────────────────────
def _truss_2d() -> Project:
    return Project(
        ndm=2, ndf=2,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True, True, False, False, False, False)),
            Node(id=2, coords=(4, 0, 0), restraint=(False, True, False, False, False, False)),
            Node(id=3, coords=(2, 3, 0)),
        ],
        materials=[Steel01(id=1, Fy=420e6, E0=200e9, b=0.01)],
        elements=[
            TrussElement(id=1, nodes=(1, 3), area=1e-3, material_id=1),
            TrussElement(id=2, nodes=(2, 3), area=1e-3, material_id=1),
        ],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1, time_series_id=1,
                nodal_loads=[NodalLoad(node_id=3, forces=(0, -1000, 0, 0, 0, 0))],
            )
        ],
    )


def _portal_3d() -> Project:
    return Project(
        ndm=3, ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(id=2, coords=(0, 0, 3)),
        ],
        materials=[ElasticIsotropic(id=1, E=200e9, nu=0.3)],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-4, Iy=1e-4, G=80e9, J=1e-6)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
    )


def _isolator_3d() -> Project:
    """A grounded HystereticSM isolator (zeroLength) under a -cMass frame —
    the wire-rope benchmark's building block in miniature."""
    return Project(
        ndm=3, ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),  # grounded
            Node(id=2, coords=(0, 0, 0)),                          # coincident
            Node(id=3, coords=(0, 0, 3)),
        ],
        materials=[
            HystereticSM(
                id=1, name="axial",
                pos_env=[(1.57, 0.00207), (69.1, 0.0399)],
                neg_env=[(-1.4, -0.00057), (-15.31, -0.0483)],
            ),
            HystereticSM(id=2, name="shear", pos_env=[(0.12, 0.00067), (9.21, 0.0804)]),
        ],
        sections=[
            ElasticSection(id=1, E=2.1e8, A=9.13e-4, Iz=7.373e-7, Iy=7.373e-7, G=8.08e7, J=2.494e-8),
        ],
        elements=[
            ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1, 2), dofs=(3, 1)),
            ElasticBeamColumn(
                id=2, nodes=(2, 3), section_id=1, rho=0.00717, consistent_mass=True,
            ),
        ],
    )


def _shear_frame_2d() -> Project:
    return Project(
        ndm=2, ndf=3,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True, True, False, False, False, True)),
            Node(id=2, coords=(4, 0, 0), restraint=(True, True, False, False, False, True)),
            Node(id=3, coords=(0, 3, 0)),
            Node(id=4, coords=(4, 3, 0)),
        ],
        mp_constraints=[EqualDOFConstraint(retained_node=3, constrained_node=4, dofs=(2, 3))],
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-4)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 3), section_id=1)],
    )


# ───────────────────────── _dof_indices ─────────────────────────
class TestDofIndices:
    @pytest.mark.parametrize(
        ("ndm", "ndf", "expected"),
        [(2, 2, (0, 1)), (2, 3, (0, 1, 5)), (3, 3, (0, 1, 2)), (3, 6, (0, 1, 2, 3, 4, 5))],
    )
    def test_valid_combinations(self, ndm: int, ndf: int, expected: tuple[int, ...]) -> None:
        assert _dof_indices(ndm, ndf) == expected

    def test_invalid_combination_raises(self) -> None:
        with pytest.raises(ValueError):
            _dof_indices(2, 6)


# ───────────────────────── command order ─────────────────────────
class TestBuildCommandOrder:
    def test_wipe_first_then_model(self) -> None:
        ops = MagicMock()
        OpenSeesRunner(_truss_2d(), ops_module=ops).build()
        names = [c[0] for c in ops.method_calls]
        assert names[0] == "wipe"
        assert names[1] == "model"

    def test_nodes_before_fixes(self) -> None:
        ops = MagicMock()
        OpenSeesRunner(_truss_2d(), ops_module=ops).build()
        names = [c[0] for c in ops.method_calls]
        assert names.index("node") < names.index("fix")
        if "equalDOF" in names:
            assert names.index("fix") < names.index("equalDOF")

    def test_materials_before_elements(self) -> None:
        ops = MagicMock()
        OpenSeesRunner(_truss_2d(), ops_module=ops).build()
        names = [c[0] for c in ops.method_calls]
        assert names.index("uniaxialMaterial") < names.index("element")

    def test_geom_transf_before_frame_element(self) -> None:
        ops = MagicMock()
        OpenSeesRunner(_portal_3d(), ops_module=ops).build()
        names = [c[0] for c in ops.method_calls]
        assert "geomTransf" in names
        assert names.index("geomTransf") < names.index("element")


# ───────────────────────── per-command emission ─────────────────────────
class TestNodeEmission:
    def test_2d_truss_passes_only_two_coords(self) -> None:
        ops = MagicMock()
        OpenSeesRunner(_truss_2d(), ops_module=ops).build()
        node_calls = [c for c in ops.method_calls if c[0] == "node"]
        # Each: (1, 0, 0) or (4, 0, 0) or (2, 3, 0); only first two coords go in.
        assert node_calls[0] == call.node(1, 0.0, 0.0)
        assert node_calls[1] == call.node(2, 4.0, 0.0)
        assert node_calls[2] == call.node(3, 2.0, 3.0)

    def test_3d_passes_all_three_coords(self) -> None:
        ops = MagicMock()
        OpenSeesRunner(_portal_3d(), ops_module=ops).build()
        node_calls = [c for c in ops.method_calls if c[0] == "node"]
        assert node_calls[0] == call.node(1, 0.0, 0.0, 0.0)
        assert node_calls[1] == call.node(2, 0.0, 0.0, 3.0)


class TestFixEmission:
    def test_2d_truss_fix_count_matches_ndf(self) -> None:
        ops = MagicMock()
        OpenSeesRunner(_truss_2d(), ops_module=ops).build()
        fix_calls = [c for c in ops.method_calls if c[0] == "fix"]
        for c in fix_calls:
            args = c.args
            # tag + ndf flags
            assert len(args) == 1 + 2

    def test_3d_pin_passes_six_flags(self) -> None:
        ops = MagicMock()
        OpenSeesRunner(_portal_3d(), ops_module=ops).build()
        fix_calls = [c for c in ops.method_calls if c[0] == "fix"]
        assert fix_calls[0] == call.fix(1, 1, 1, 1, 1, 1, 1)

    def test_equal_dof_constraint_emits(self) -> None:
        ops = MagicMock()
        OpenSeesRunner(_shear_frame_2d(), ops_module=ops).build()
        ops.equalDOF.assert_called_with(3, 4, 2, 3)


class TestMaterialEmission:
    def test_steel01_basic(self) -> None:
        ops = MagicMock()
        OpenSeesRunner(_truss_2d(), ops_module=ops).build()
        ops.uniaxialMaterial.assert_any_call("Steel01", 1, 420e6, 200e9, 0.01)

    def test_hystereticsm_pos_and_neg_envelopes(self) -> None:
        ops = MagicMock()
        OpenSeesRunner(_isolator_3d(), ops_module=ops).build()
        # Pairs are flattened in (force, deformation) command order, both envelopes.
        ops.uniaxialMaterial.assert_any_call(
            "HystereticSM", 1,
            "-posEnv", 1.57, 0.00207, 69.1, 0.0399,
            "-negEnv", -1.4, -0.00057, -15.31, -0.0483,
        )

    def test_hystereticsm_symmetric_omits_neg_envelope(self) -> None:
        ops = MagicMock()
        OpenSeesRunner(_isolator_3d(), ops_module=ops).build()
        # No neg_env ⇒ only -posEnv is emitted (OpenSees mirrors it).
        ops.uniaxialMaterial.assert_any_call(
            "HystereticSM", 2, "-posEnv", 0.12, 0.00067, 9.21, 0.0804,
        )


class TestElementEmission:
    def test_truss_2d(self) -> None:
        ops = MagicMock()
        OpenSeesRunner(_truss_2d(), ops_module=ops).build()
        ops.element.assert_any_call("truss", 1, 1, 3, 1e-3, 1, "-rho", 0.0)

    def test_elastic_beam_column_uses_allocated_transf_tag(self) -> None:
        ops = MagicMock()
        OpenSeesRunner(_portal_3d(), ops_module=ops).build()
        # geomTransf tag 1 was allocated for "Linear"; element should use it.
        ops.element.assert_any_call(
            "elasticBeamColumn", 1, 1, 2, 1, 1, "-mass", 0.0
        )

    def test_elastic_beam_column_cmass_appends_flag(self) -> None:
        ops = MagicMock()
        OpenSeesRunner(_isolator_3d(), ops_module=ops).build()
        # cMass=True ⇒ the consistent-mass flag trails the -mass density.
        ops.element.assert_any_call(
            "elasticBeamColumn", 2, 2, 3, 1, 1, "-mass", 0.00717, "-cMass"
        )

    def test_zero_length_emits_mat_and_dir_lists(self) -> None:
        ops = MagicMock()
        OpenSeesRunner(_isolator_3d(), ops_module=ops).build()
        ops.element.assert_any_call(
            "zeroLength", 1, 1, 2, "-mat", 1, 2, "-dir", 3, 1
        )


class TestPatternEmission:
    def test_plain_pattern_emits_nested_loads(self) -> None:
        """The full run path emits patterns; build() does not."""
        ops = MagicMock()
        runner = OpenSeesRunner(_truss_2d(), ops_module=ops)
        runner.build()
        runner._emit_patterns_for_case([1])
        ops.timeSeries.assert_called_with("Linear", 1, "-factor", 1.0)
        ops.pattern.assert_called_with("Plain", 1, 1)
        # Nodal load on node 3, force vector sliced to (Fx, Fy) for 2D-2DOF
        ops.load.assert_called_with(3, 0.0, -1000.0)


# ───────────────────────── reference validation ─────────────────────────
def test_build_calls_validate_references() -> None:
    p = _truss_2d()
    # break a reference
    p.elements[0].nodes = (1, 99)
    ops = MagicMock()
    with pytest.raises(ValueError, match="missing node 99"):
        OpenSeesRunner(p, ops_module=ops).build()
    # No commands should have reached ops after validation failed.
    ops.element.assert_not_called()
