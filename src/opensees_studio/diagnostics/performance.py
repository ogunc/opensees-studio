"""Opt-in timing, counter and memory instrumentation.

The application is large enough that a slow action can live in any of several
layers: the S2K parser, Pydantic validation, the Qt model tree, the renderer, the
analysis child process, or results parsing. This module gives every layer one
cheap way to report what it cost, without changing normal behaviour.

Usage::

    from opensees_studio.diagnostics.performance import perf

    with perf.span("s2k.frames"):
        translator.build_frames(...)
    perf.gauge("project.nodes", len(project.nodes))

The monitor is disabled by default. Enable it with::

    python -m opensees_studio --profile
    OPENSEES_STUDIO_PERF=1 python -m opensees_studio

``--perf-json PATH`` also enables it and writes a snapshot on exit. The Help
menu's **Performance monitor** can enable it at runtime and browse the metrics.
"""

from __future__ import annotations

import atexit
import cProfile
import io
import json
import math
import os
import platform
import pstats
import sys
import threading
import time
import tracemalloc
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_TRUTHY = {"1", "true", "yes", "on"}
_ENV_FLAG = "OPENSEES_STUDIO_PERF"


def _environment_enabled() -> bool:
    return os.environ.get(_ENV_FLAG, "").strip().lower() in _TRUTHY


@dataclass
class MetricSnapshot:
    """One row of the performance table."""

    name: str
    count: int
    last_ms: float
    total_ms: float
    min_ms: float
    max_ms: float
    p95_ms: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "last_ms": round(self.last_ms, 3),
            "total_ms": round(self.total_ms, 3),
            "min_ms": round(self.min_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
        }


@dataclass
class _Metric:
    count: int = 0
    total_ms: float = 0.0
    last_ms: float = 0.0
    min_ms: float = math.inf
    max_ms: float = 0.0
    samples: deque[float] = field(default_factory=lambda: deque(maxlen=512))

    def add(self, duration_ms: float) -> None:
        self.count += 1
        self.total_ms += duration_ms
        self.last_ms = duration_ms
        self.min_ms = min(self.min_ms, duration_ms)
        self.max_ms = max(self.max_ms, duration_ms)
        self.samples.append(duration_ms)

    def snapshot(self, name: str) -> MetricSnapshot:
        if self.count == 0:
            return MetricSnapshot(name, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
        ordered = sorted(self.samples)
        index = min(len(ordered) - 1, max(0, math.ceil(0.95 * len(ordered)) - 1))
        return MetricSnapshot(
            name=name,
            count=self.count,
            last_ms=self.last_ms,
            total_ms=self.total_ms,
            min_ms=self.min_ms,
            max_ms=self.max_ms,
            p95_ms=ordered[index],
        )


class PerformanceMonitor:
    """Thread-safe, opt-in collector of spans, counters, gauges and events."""

    def __init__(self, *, enabled: bool | None = None, max_events: int = 1000) -> None:
        self._lock = threading.RLock()
        self._enabled = _environment_enabled() if enabled is None else enabled
        self._metrics: dict[str, _Metric] = {}
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._started = time.perf_counter()
        self._json_path: Path | None = None
        self._atexit_registered = False
        self._profile_next = False
        self._last_profile = ""
        self._profile_generation = 0

    # ── configuration ──────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        """Start collecting timings, counters and events."""
        with self._lock:
            if self._enabled:
                return
            self._enabled = True
            self._started = time.perf_counter()
        self.event("performance.enabled")

    def start_memory_tracing(self) -> None:
        """Also track Python allocations (``tracemalloc`` adds measurable cost)."""
        self._start_memory_tracing()

    def disable(self) -> None:
        with self._lock:
            if not self._enabled:
                return
            self.event("performance.disabled")
            self._enabled = False
        if tracemalloc.is_tracing():
            tracemalloc.stop()

    def configure(
        self, *, enabled: bool | None = None, json_path: str | Path | None = None
    ) -> None:
        """Apply command-line options after the monitor was created."""
        if json_path is not None:
            self.set_json_path(json_path)
        if enabled is True:
            self.enable()
        elif enabled is False:
            self.disable()

    def set_json_path(self, path: str | Path) -> None:
        with self._lock:
            self._json_path = Path(path)
            if not self._atexit_registered:
                atexit.register(self._write_at_exit)
                self._atexit_registered = True

    def reset(self) -> None:
        """Forget every metric, counter, gauge and event."""
        with self._lock:
            self._metrics.clear()
            self._counters.clear()
            self._gauges.clear()
            self._events.clear()
            self._started = time.perf_counter()
            self._last_profile = ""
            self._profile_generation += 1
        if tracemalloc.is_tracing():
            tracemalloc.reset_peak()

    # ── collection ─────────────────────────────────────────────────────
    @contextmanager
    def span(self, name: str, **fields: Any) -> Iterator[None]:
        """Measure the block as ``name``; nested spans are allowed.

        The monitor is disabled most of the time, so this must stay cheap:
        when off it is one boolean check and a generator frame.
        """
        if not self._enabled:
            yield
            return
        profile = self._take_profile()
        started = time.perf_counter()
        error = False
        try:
            yield
        except BaseException:
            error = True
            raise
        finally:
            elapsed = (time.perf_counter() - started) * 1000.0
            event_fields = dict(fields)
            if error:
                event_fields["error"] = True
            self.record(name, elapsed, **event_fields)
            if profile is not None:
                profile.disable()
                self._store_profile(profile, name)

    def record(self, name: str, duration_ms: float, **fields: Any) -> None:
        """Add one measured duration (for callbacks that cannot use ``span``)."""
        if not self._enabled:
            return
        with self._lock:
            self._metrics.setdefault(name, _Metric()).add(float(duration_ms))
            if fields:
                event = {
                    "time": round(time.time(), 3),
                    "name": name,
                    "ms": round(float(duration_ms), 3),
                    **fields,
                }
                self._events.append(event)

    def count(self, name: str, amount: float = 1.0) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._counters[name] = self._counters.get(name, 0.0) + float(amount)

    def gauge(self, name: str, value: float) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._gauges[name] = float(value)

    def event(self, name: str, **fields: Any) -> None:
        """Record a one-off event (a UI stall, an enabled/disabled transition)."""
        if not self._enabled:
            return
        with self._lock:
            self._events.append(
                {
                    "time": round(time.time(), 3),
                    "name": name,
                    **fields,
                }
            )

    # ── cProfile for the next action ───────────────────────────────────
    def request_profile_next(self) -> None:
        """Profile the next top-level ``span`` (for example the next command)."""
        with self._lock:
            self._profile_next = True

    @property
    def profile_generation(self) -> int:
        return self._profile_generation

    def last_profile_text(self) -> str:
        return self._last_profile

    def _take_profile(self) -> cProfile.Profile | None:
        if not self._profile_next:
            return None
        with self._lock:
            if not self._profile_next:
                return None
            self._profile_next = False
        profile = cProfile.Profile()
        profile.enable()
        return profile

    def _store_profile(self, profile: cProfile.Profile, name: str) -> None:
        stream = io.StringIO()
        pstats.Stats(profile, stream=stream).sort_stats("cumulative").print_stats(30)
        text = f"Profile of {name}\n{stream.getvalue()}"
        with self._lock:
            self._last_profile = text
            self._profile_generation += 1

    # ── snapshots ──────────────────────────────────────────────────────
    def snapshot(self) -> dict[str, Any]:
        """A JSON-serialisable view of everything collected so far."""
        with self._lock:
            metrics = {
                name: metric.snapshot(name).as_dict() for name, metric in self._metrics.items()
            }
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            events = list(self._events)
            started = self._started
            last_profile = self._last_profile
            uptime = time.perf_counter() - started
        try:
            from opensees_studio import __version__
        except Exception:  # pragma: no cover - only during a broken import
            __version__ = "unknown"
        memory: dict[str, Any] = {}
        if tracemalloc.is_tracing():
            current, peak = tracemalloc.get_traced_memory()
            memory["python_current_mb"] = round(current / (1024 * 1024), 2)
            memory["python_peak_mb"] = round(peak / (1024 * 1024), 2)
        try:
            import psutil  # type: ignore[import-untyped]

            memory["rss_mb"] = round(psutil.Process().memory_info().rss / (1024 * 1024), 2)
        except Exception:
            # psutil is optional: the report still has Python memory (when
            # enabled) and every timing without it.
            pass
        return {
            "version": __version__,
            "enabled": self._enabled,
            "uptime_s": round(uptime, 3),
            "platform": {
                "python": platform.python_version(),
                "system": platform.system(),
                "machine": platform.machine(),
                "pid": os.getpid(),
            },
            "memory": memory,
            "metrics": metrics,
            "counters": counters,
            "gauges": gauges,
            "events": events,
            "profile": last_profile,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.snapshot(), indent=indent, ensure_ascii=False)

    def write_json(self, path: str | Path, *, indent: int = 2) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(indent=indent) + "\n", encoding="utf-8")
        return target

    def _start_memory_tracing(self) -> None:
        try:
            if not tracemalloc.is_tracing():
                tracemalloc.start(25)
        except Exception:
            # Embedded/frozen runtimes may not provide tracemalloc; timing is
            # still useful without Python allocation tracking.
            pass

    def _write_at_exit(self) -> None:
        with self._lock:
            target = self._json_path
            enabled = self._enabled
        if target is None or not enabled:
            return
        try:
            self.write_json(target)
        except Exception as exc:  # pragma: no cover - shutdown must never fail
            print(f"performance report not written: {exc}", file=sys.stderr)


def configure_from_argv(argv: list[str]) -> list[str]:
    """Consume ``--profile`` and ``--perf-json PATH``; return the rest.

    Qt and the analysis CLI should not see these options. The global monitor is
    configured here, before the GUI or a child analysis starts.
    """
    enabled = perf.enabled
    json_path: str | None = None
    cleaned: list[str] = []
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--profile":
            enabled = True
        elif argument == "--perf-json" and index + 1 < len(argv):
            json_path = argv[index + 1]
            enabled = True
            index += 1
        elif argument.startswith("--perf-json="):
            json_path = argument.split("=", 1)[1]
            enabled = True
        else:
            cleaned.append(argument)
        index += 1
    perf.configure(enabled=enabled, json_path=json_path)
    return cleaned


#: The application-wide monitor. Import this, not another instance, from
#: instrumented code so the dialog and the JSON report see the same numbers.
perf = PerformanceMonitor()

__all__ = ["MetricSnapshot", "PerformanceMonitor", "configure_from_argv", "perf"]
