"""Opt-in window placement measurements for the Linux CI investigation."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from functools import cache

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget


@cache
def _window_manager() -> str:
    xprop = shutil.which("xprop")
    if xprop is None:
        return "xprop unavailable"
    try:
        root = subprocess.run(
            [xprop, "-root", "_NET_SUPPORTING_WM_CHECK"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        ).stdout
        match = re.search(r"0x[0-9a-fA-F]+", root)
        if match is None:
            return root.strip()
        return subprocess.run(
            [xprop, "-id", match[0], "_NET_WM_NAME", "WM_NAME"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return type(exc).__name__


def window_diagnostic(widget: QWidget, stage: str, **details: object) -> None:
    if os.environ.get("OSV_WINDOW_DIAG") != "1":
        return
    screen = widget.screen()
    handle = widget.windowHandle()
    data = {
        "stage": stage,
        "widget": f"{type(widget).__name__}:{id(widget):x}",
        "time": time.monotonic(),
        "geometry": widget.geometry().getRect(),
        "frameGeometry": widget.frameGeometry().getRect(),
        "windowState": widget.windowState().value,
        "maximized": widget.isMaximized(),
        "visible": widget.isVisible(),
        "exposed": handle.isExposed() if handle else None,
        "screenAvailable": screen.availableGeometry().getRect(),
        "screenGeometry": screen.geometry().getRect(),
        "devicePixelRatio": widget.devicePixelRatioF(),
        "platform": QGuiApplication.platformName(),
        "windowManager": _window_manager(),
        "minimumSize": (widget.minimumWidth(), widget.minimumHeight()),
        **details,
    }
    line = "OSV_WINDOW_DIAG " + json.dumps(data, ensure_ascii=True)
    lines = getattr(widget, "_window_diag_lines", None)
    if lines is None:
        widget._window_diag_lines = lines = []
    lines.append(line)
    print(line, file=sys.stderr, flush=True)


def collected_window_diagnostics(widget: QWidget) -> str:
    return "\n".join(getattr(widget, "_window_diag_lines", []))
