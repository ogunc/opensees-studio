"""Tests for the end-to-end synthetic benchmark tool."""

from __future__ import annotations

from tools import perf_bench


def test_tiny_benchmark_without_solver() -> None:
    report = perf_bench.run_bench(size="tiny", solver=False)
    assert report["size"] == "tiny"
    assert report["nodes"] == 4 * 4 * 2
    assert report["frames"] > 0
    assert report["load_patterns"] == 1
    assert report["render"]["build_ms"] > 0
    assert report["render"]["actors"] > 0
    assert report["save_ms"] > 0
    assert report["load_ms"] > 0
    assert report["save_load_nodes"] == report["nodes"]
    assert "solver_ms" not in report
