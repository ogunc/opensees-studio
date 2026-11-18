"""The stability benchmark builds reproducible frame and truss families."""

from __future__ import annotations

from tools.stability_bench import run_case


def test_a_small_frame_family_is_stable_and_reports_its_size() -> None:
    row = run_case("frame", 4)
    assert row["nodes"] == 16
    assert row["elements"] == 24
    assert row["n_equations"] > 0
    assert row["nnz"] > 0
    assert row["completion"] == "complete"
    assert row["stable"] is True


def test_the_truss_mechanism_variant_is_unstable() -> None:
    row = run_case("truss", 4, mechanism=True)
    assert row["completion"] == "complete"
    assert row["n_mechanisms"] > 0
    assert row["stable"] is False
