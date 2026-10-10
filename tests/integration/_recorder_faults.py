"""Fault injection for recorder tests: an ops wrapper that drops one recorder.

Imported by the integration tests and by the CLI subprocess they start,
so both inject the same fault.
"""

from __future__ import annotations

from typing import Any


class DropOneRecorder:
    """Forwards every call to the real ops module but skips the recorder of one file.

    That is how OpenSees behaves when it cannot open a recorder path: no
    file is written and no error is raised.
    """

    def __init__(self, ops: Any, file_name: str) -> None:
        self._ops = ops
        self._file_name = file_name

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ops, name)

    def recorder(self, *args: Any) -> Any:
        if any(isinstance(a, str) and a.endswith(self._file_name) for a in args):
            return 0
        return self._ops.recorder(*args)
