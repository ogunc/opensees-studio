"""ASCII-safe staging for the files OpenSees reads and writes.

OpenSeesPy hands file names to the C++ runtime as narrow strings. On
Windows such a name is opened through the ANSI code page, so a path
with characters that do not survive that round trip (a user profile
such as ``C:\\Users\\Öğünç``) opens nothing: a recorder then writes no
file and reports no error.

The rule: OpenSees never receives a project or user path. Its file
I/O goes to a per-run staging directory whose path is pure ASCII, and
Python, which is Unicode-safe, copies the results to their destination.
Inputs never go through files: time series reach OpenSees as
``-values`` lists built from the values the runner already holds.

The only OpenSees file commands the runner issues are the transient
``recorder Node/Element -file`` calls (see
:meth:`~opensees_studio.services.opensees_runner.OpenSeesRunner._run_transient`).

A staging directory is removed when its run ends. A run that never
reaches that point (a cancelled or crashed analysis process) leaves
its directory behind with its owner's process id in ``owner.pid``; the
next run sweeps every directory whose owner is no longer alive.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np

#: Prefix of every per-run staging directory.
STAGING_PREFIX = "opensees-studio-run-"

#: File in each staging directory holding the owning process id.
OWNER_FILE = "owner.pid"

#: A staging directory without a readable owner file is only swept once it is
#: this old (it may be one that another process is creating right now).
UNMARKED_STAGE_GRACE_S = 3600.0


class RecorderOutputError(RuntimeError):
    """OpenSees committed analysis steps but a recorder file is missing, empty or short."""


def is_ascii_path(path: str | os.PathLike[str]) -> bool:
    """True when every character of ``path`` is ASCII."""
    return os.fspath(path).isascii()


def fallback_staging_root() -> Path:
    """Fixed ASCII root used when the temp directory is not ASCII.

    ``%SystemDrive%\\ProgramData\\OpenSeesStudio\\runs`` on Windows (the
    system drive letter is always ASCII; ProgramData is writable by
    every user), ``/tmp/opensees-studio-<uid>/runs`` elsewhere.
    """
    if os.name == "nt":
        drive = os.environ.get("SYSTEMDRIVE", "C:")
        if not (is_ascii_path(drive) and len(drive) == 2 and drive.endswith(":")):
            drive = "C:"
        return Path(f"{drive}\\") / "ProgramData" / "OpenSeesStudio" / "runs"
    return Path("/tmp") / f"opensees-studio-{os.getuid()}" / "runs"


def staging_root(temp_dir: str | os.PathLike[str] | None = None) -> Path:
    """Directory that holds the per-run staging folders; always an ASCII path.

    ``temp_dir`` defaults to :func:`tempfile.gettempdir` (on Windows usually
    the 8.3 short form of the user's temp folder, which is ASCII even under
    a non-ASCII user name). When it is not ASCII, the fixed
    :func:`fallback_staging_root` is used instead.
    """
    base = Path(temp_dir) if temp_dir is not None else Path(tempfile.gettempdir())
    if is_ascii_path(base):
        return base
    fallback = fallback_staging_root()
    if not is_ascii_path(fallback):  # pragma: no cover - drive letters and /tmp are ASCII
        raise RuntimeError(f"No ASCII-safe staging directory available (tried {fallback}).")
    return fallback


def _ensure_root(root: Path) -> None:
    """Create ``root``; the POSIX fallback under the shared /tmp must be private."""
    if os.name == "nt" or root != fallback_staging_root():
        root.mkdir(parents=True, exist_ok=True)
        return
    private = root.parent  # /tmp/opensees-studio-<uid>
    private.mkdir(mode=0o700, exist_ok=True)
    st = os.lstat(private)
    if (
        not stat.S_ISDIR(st.st_mode)
        or st.st_uid != os.getuid()
        or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise RuntimeError(
            f"Refusing to stage OpenSees output in {private}: it is not a private "
            "directory owned by the current user."
        )
    root.mkdir(mode=0o700, exist_ok=True)


def _pid_alive(pid: int) -> bool:
    """Whether process ``pid`` still runs (an unknown answer counts as alive)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        process_query_limited_information = 0x1000
        still_active = 259
        error_invalid_parameter = 87  # no process with this id
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return ctypes.get_last_error() != error_invalid_parameter
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def sweep_stale_stages(root: Path) -> list[Path]:
    """Remove staging directories under ``root`` whose owner process is gone.

    Returns the directories removed. Directories of live processes (another
    running analysis, another application instance) are left alone.
    """
    removed: list[Path] = []
    try:
        candidates = [p for p in root.glob(f"{STAGING_PREFIX}*") if p.is_dir()]
    except OSError:
        return removed
    for stage in candidates:
        try:
            pid: int | None = int((stage / OWNER_FILE).read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            pid = None
        if pid is not None:
            if _pid_alive(pid):
                continue
        else:
            try:
                age = time.time() - stage.stat().st_mtime
            except OSError:
                continue
            if age < UNMARKED_STAGE_GRACE_S:
                continue
        shutil.rmtree(stage, ignore_errors=True)
        if not stage.exists():
            removed.append(stage)
    return removed


@contextmanager
def staging_dir(temp_dir: str | os.PathLike[str] | None = None) -> Iterator[Path]:
    """A fresh per-run ASCII directory for OpenSees file I/O, removed on exit.

    The root is created on demand and swept of directories left by dead
    runs first. The caller copies whatever it needs out of the directory
    before the ``with`` block ends.
    """
    root = staging_root(temp_dir)
    _ensure_root(root)
    sweep_stale_stages(root)
    run_dir = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=root))
    try:
        (run_dir / OWNER_FILE).write_text(str(os.getpid()), encoding="ascii")
        yield run_dir
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def check_recorder_output(files: Iterable[Path], steps_completed: int) -> None:
    """Raise :class:`RecorderOutputError` when a recorder file is missing or empty.

    Only meaningful after the recorders were flushed (``remove recorders``)
    and at least one step was committed: every recorder then has written
    one row per step.
    """
    files = list(files)
    bad = [p for p in files if not p.is_file() or p.stat().st_size == 0]
    if not bad:
        return
    shown = ", ".join(p.name for p in bad[:5])
    more = f" and {len(bad) - 5} more" if len(bad) > 5 else ""
    raise RecorderOutputError(
        f"OpenSees wrote no recorder output to {shown}{more} ({len(bad)} of {len(files)} "
        f"file(s) missing or empty after {steps_completed} committed step(s)). "
        "The results would be incomplete, so the case failed."
    )


def load_recorder_table(path: Path, rows: int, columns: int) -> np.ndarray:
    """Read a recorder file as a ``rows x columns`` table or raise, naming the file.

    A recorder writes one row per committed step, so a shorter or ragged
    file (for example cut off by a full disk) is an error, not a result.
    """
    try:
        data = np.loadtxt(path, ndmin=2)
    except ValueError as exc:
        raise RecorderOutputError(
            f"Recorder file {path.name} is unreadable ({exc}); the case failed."
        ) from exc
    if data.shape != (rows, columns):
        raise RecorderOutputError(
            f"Recorder file {path.name} holds {data.shape[0]} row(s) x {data.shape[1]} "
            f"column(s), expected {rows} x {columns} after {rows} committed step(s); "
            "the case failed."
        )
    return data


def place_files(files: Iterable[Path], destination: Path) -> list[Path]:
    """Copy ``files`` into ``destination`` (created if needed); returns the new paths.

    Each file is copied next to its target and then swapped in with
    :func:`os.replace`, so a target that cannot be replaced keeps its old
    content, and the new file is created in the destination (it inherits
    the destination's permissions, not the private staging directory's).
    Python file operations are Unicode-safe, so the destination may be any
    path.
    """
    destination.mkdir(parents=True, exist_ok=True)
    placed = []
    for src in files:
        dst = destination / src.name
        tmp = destination / f"{src.name}.{os.getpid()}.tmp"
        shutil.copyfile(src, tmp)
        try:
            os.replace(tmp, dst)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise
        placed.append(dst)
    return placed
