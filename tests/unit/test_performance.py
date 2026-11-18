"""Tests for the opt-in performance monitor (no Qt)."""

from __future__ import annotations

import json
import time

from opensees_studio.diagnostics.performance import (
    PerformanceMonitor,
    configure_from_argv,
    perf,
)


def test_disabled_monitor_records_nothing() -> None:
    monitor = PerformanceMonitor(enabled=False)
    with monitor.span("ignored"):
        time.sleep(0.001)
    monitor.count("calls", 3)
    monitor.gauge("nodes", 10)
    monitor.event("something")

    snapshot = monitor.snapshot()
    assert snapshot["enabled"] is False
    assert snapshot["metrics"] == {}
    assert snapshot["counters"] == {}
    assert snapshot["gauges"] == {}
    assert snapshot["events"] == []


def test_spans_counters_gauges_and_events() -> None:
    monitor = PerformanceMonitor(enabled=True)
    with monitor.span("import"):
        time.sleep(0.002)
    with monitor.span("import"):
        time.sleep(0.001)
    monitor.count("frames", 2)
    monitor.gauge("nodes", 8)
    monitor.event("loaded", source="unit")

    snapshot = monitor.snapshot()
    metric = snapshot["metrics"]["import"]
    assert metric["count"] == 2
    assert metric["total_ms"] >= metric["last_ms"] > 0
    assert metric["p95_ms"] > 0
    assert snapshot["counters"] == {"frames": 2.0}
    assert snapshot["gauges"] == {"nodes": 8.0}
    assert snapshot["events"][-1]["name"] == "loaded"
    assert snapshot["events"][-1]["source"] == "unit"


def test_error_spans_are_recorded_as_events() -> None:
    monitor = PerformanceMonitor(enabled=True)
    try:
        with monitor.span("bad"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    snapshot = monitor.snapshot()
    assert snapshot["metrics"]["bad"]["count"] == 1
    event = snapshot["events"][-1]
    assert event["name"] == "bad"
    assert event["error"] is True


def test_reset_clears_everything() -> None:
    monitor = PerformanceMonitor(enabled=True)
    with monitor.span("x"):
        pass
    monitor.count("c", 1)
    monitor.gauge("g", 1)
    monitor.event("e")
    monitor.reset()
    snapshot = monitor.snapshot()
    assert snapshot["metrics"] == {}
    assert snapshot["counters"] == {}
    assert snapshot["gauges"] == {}
    assert snapshot["events"] == []


def test_json_report_has_version_and_extensible_payload(tmp_path) -> None:
    monitor = PerformanceMonitor(enabled=True)
    with monitor.span("render"):
        pass
    target = monitor.write_json(tmp_path / "report.json")
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["version"]
    assert "render" in payload["metrics"]
    assert payload["platform"]["python"]
    assert "memory" in payload
    assert json.loads(monitor.to_json())["enabled"] is True


def test_profile_next_action_records_a_cprofile_text() -> None:
    monitor = PerformanceMonitor(enabled=True)
    monitor.request_profile_next()
    with monitor.span("profiled.action"):
        sum(range(10_000))
    text = monitor.last_profile_text()
    assert text.startswith("Profile of profiled.action")
    assert "cumulative" in text
    assert monitor.profile_generation == 1


def test_configure_from_argv_consumes_only_the_diagnostic_flags() -> None:
    was_enabled = perf.enabled
    try:
        cleaned = configure_from_argv(["OpenSeesStudio.exe", "--profile", "--foo"])
        assert cleaned == ["OpenSeesStudio.exe", "--foo"]
        assert perf.enabled
    finally:
        # Do not leak the enabled state to other tests.
        perf.reset()
        perf.disable()
        if was_enabled:
            perf.enable()
