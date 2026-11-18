"""The stability report: what the dialog and the log say, and the CLI round trip."""

from __future__ import annotations

from opensees_studio.services.stability import Mechanism, Mover, StabilityReport


def _report() -> StabilityReport:
    return StabilityReport(
        n_equations=5,
        rank=4,
        mechanisms=[
            Mechanism(
                movers=[Mover(node=4, dof="Ux", amplitude=1.0), Mover(3, "Ux", 1.0)],
                singular_value=0.0,
            )
        ],
        n_mechanisms=1,
        condition=12.5,
    )


def test_a_full_rank_model_is_stable() -> None:
    report = StabilityReport(n_equations=6, rank=6)
    assert report.stable
    assert "statically stable" in report.summary()
    assert report.nodes == []


def test_a_mechanism_names_its_joints_and_dofs() -> None:
    report = _report()
    assert not report.stable
    summary = report.summary()
    assert "1 mechanism(s)" in summary and "rank 4" in summary
    assert "N4 Ux (+1.00), N3 Ux (+1.00)" in summary
    assert report.nodes == [4, 3]


def test_an_unstiffened_dof_alone_makes_the_model_unstable() -> None:
    report = StabilityReport(n_equations=3, rank=3, uncovered=["Node 2, DOF Ry: no element"])
    assert not report.stable
    assert "Node 2, DOF Ry" in report.summary()


def test_more_mechanisms_than_listed_are_counted() -> None:
    report = _report()
    report.n_mechanisms = 9
    assert "… and 8 more." in report.summary()


def test_the_report_survives_the_cli_json() -> None:
    report = _report()
    assert StabilityReport.from_dict(report.to_dict()) == report


def test_a_partial_or_negative_report_is_never_stable() -> None:
    partial = StabilityReport(
        n_equations=6,
        rank=None,
        completion="partial",
        classification="no_mechanisms",
        warnings=["only the lowest modes were checked"],
    )
    assert not partial.stable
    assert "partial" in partial.summary()

    negative = StabilityReport(
        n_equations=6,
        rank=6,
        classification="negative_stiffness",
        completion="complete",
    )
    assert not negative.stable
    assert "negative" in negative.summary()


def test_a_fully_restrained_model_is_a_distinct_success() -> None:
    report = StabilityReport(
        n_equations=0,
        rank=0,
        completion="complete",
        classification="no_free_equations",
    )
    assert report.stable
    assert "fully restrained" in report.summary()


def test_the_new_report_fields_round_trip() -> None:
    report = StabilityReport(
        n_equations=8,
        rank=None,
        mechanisms=[],
        n_mechanisms=0,
        condition=None,
        completion="partial",
        classification="no_mechanisms",
        analysis_state="initial",
        nnz=42,
        method="python_sparse_csr+sparse_eigsh_shift_invert",
        backend="PythonSparse+scipy",
        versions={"scipy": "1.0", "numpy": "2.0"},
        scaling={"kind": "diagonal", "applied": True},
        tolerances={"relative": 1e-10},
        count_kind="estimate",
        warnings=["only the lowest modes were checked"],
        timings={"extract_ms": 1.5},
        memory={"csr_bytes": 100, "estimated": True},
        model_fingerprint="abc",
    )
    restored = StabilityReport.from_dict(report.to_dict())
    assert restored == report
