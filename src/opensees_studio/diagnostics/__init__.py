"""Opt-in diagnostics for performance work on large models.

The public entry point is :data:`perf` from
:mod:`opensees_studio.diagnostics.performance`. It is disabled unless the
application is started with ``--profile`` (or ``OPENSEES_STUDIO_PERF=1``), so a
normal run pays only for one boolean check per instrumented boundary.
"""

from __future__ import annotations

from opensees_studio.diagnostics.performance import (
    MetricSnapshot,
    PerformanceMonitor,
    perf,
)

__all__ = ["MetricSnapshot", "PerformanceMonitor", "perf"]
