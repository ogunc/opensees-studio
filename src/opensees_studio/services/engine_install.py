"""Download OpenSeesPy from PyPI into a folder the application points at.

OpenSees Studio does not distribute OpenSeesPy (its own license: free for
research, education and internal use; commercial redistribution needs a license
from its authors). The user downloads it, after reading those terms, from the
place its authors publish it: PyPI.

Exactly two wheels per platform are fetched — the ``openseespy`` wrapper and the
platform package that carries the native library — at the URLs, sizes and
SHA256 digests pinned in :data:`WHEELS`. A file that differs in a single byte is
refused, so a compromised mirror or a truncated download never reaches the
disk as an engine. The wheels are unpacked (a wheel is a zip archive whose
members are the installed files) into ``<app data>/engines/openseespy-3.8.0.0``
through a ``.partial`` folder that is only renamed once everything is in place,
and :class:`~opensees_studio.services.engines.SolverSettings` then points there.

Pure Python, no Qt: the GUI runs :func:`install_opensees` in a worker thread and
passes ``progress`` and ``cancelled``.
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from opensees_studio.services.engines import OPENSEES_PY, SolverSettings
from opensees_studio.services.persistence import app_data_dir

OPENSEESPY_VERSION = "3.8.0.0"

#: Where its authors publish OpenSeesPy and its license.
LICENSE_URL = "https://pypi.org/project/openseespy/"

#: What the user accepts before downloading (the authors' terms, in short).
LICENSE_SUMMARY = (
    "OpenSeesPy is developed by its own authors and published under its own "
    "license, not OpenSees Studio's. In short: it is free for research, "
    "education and internal use; commercial redistribution of OpenSeesPy (for "
    "example an application or a cloud service that uses it) needs a license "
    "from its authors. Read the full terms before using it, and make sure your "
    "use fits them."
)

_CHUNK = 1 << 16


@dataclass(frozen=True)
class Wheel:
    filename: str
    url: str
    size: int
    sha256: str


_WRAPPER = Wheel(
    "openseespy-3.8.0.0-py3-none-any.whl",
    "https://files.pythonhosted.org/packages/5d/f0/7cf984fed2e96286427828a0b669d034f18b674ccc84042d20835a99d543/openseespy-3.8.0.0-py3-none-any.whl",
    2792,
    "ce6a43503b737025f763a87bebacb1cc2fbd82a156982647e9e014a11b85fdbd",
)

#: The wheels of each supported platform (``platform_key()``), pinned.
WHEELS: dict[str, tuple[Wheel, ...]] = {
    "linux-x86_64": (
        _WRAPPER,
        Wheel(
            "openseespylinux-3.8.0.0-py3-none-any.whl",
            "https://files.pythonhosted.org/packages/a4/77/83cd6946a4710916e0a85df9fcd5271db3c94ac018a59f113acfd5ee40e2/openseespylinux-3.8.0.0-py3-none-any.whl",
            86251016,
            "2307e40213f1d7128a5a5151d5c8beee8244b8b988528a58f5e44394a045ba64",
        ),
    ),
    "windows-amd64": (
        _WRAPPER,
        Wheel(
            "openseespywin-3.8.0.0-py3-none-win_amd64.whl",
            "https://files.pythonhosted.org/packages/fc/6f/7d77002684c8075e024001fbe82ba695dbd553cb30d5ee2335a677344faa/openseespywin-3.8.0.0-py3-none-win_amd64.whl",
            6787016,
            "ee0f48317582641cf06347fe0babd34a230823b56397603c9b5b2d3b96089b73",
        ),
    ),
    "macos-arm64": (
        _WRAPPER,
        Wheel(
            "openseespymac-3.8.0.0-py3-none-macosx_13_0_arm64.whl",
            "https://files.pythonhosted.org/packages/42/ca/4d8eff97f95ad415010fefe595738162fc052cb8536434d5124fb0b46e99/openseespymac-3.8.0.0-py3-none-macosx_13_0_arm64.whl",
            10115801,
            "c6ddd1a28ce528258ef41237dd7883c827b8aa6f1a2d9b62e65da1f1074779ef",
        ),
    ),
}


class InstallError(RuntimeError):
    """The download or the unpacking failed; the message is for the user."""


class InstallCancelledError(InstallError):
    """The user cancelled; nothing was left behind."""


def platform_key() -> str:
    """``linux-x86_64``, ``windows-amd64``, ``macos-arm64`` … for this machine."""
    machine = platform.machine().lower()
    if sys.platform.startswith("linux"):
        return f"linux-{machine}"
    if sys.platform == "win32":
        return f"windows-{'amd64' if machine in ('amd64', 'x86_64') else machine}"
    if sys.platform == "darwin":
        return f"macos-{machine}"
    return f"{sys.platform}-{machine}"


def wheels_for(key: str | None = None) -> tuple[Wheel, ...]:
    """The wheels to fetch here.

    Raises:
        InstallError: when OpenSeesPy publishes no build for this platform.
    """
    key = platform_key() if key is None else key
    if key not in WHEELS:
        raise InstallError(
            f"OpenSeesPy {OPENSEESPY_VERSION} publishes no build for {key}. Install it "
            "in a Python of your own and point to it in Options → Solver."
        )
    return WHEELS[key]


def install_dir(root: Path | None = None) -> Path:
    """The folder the engine is unpacked into."""
    root = app_data_dir() / "engines" if root is None else root
    return root / f"openseespy-{OPENSEESPY_VERSION}"


Opener = Callable[[str], BinaryIO]
Progress = Callable[[int, int], None]  # bytes so far, total bytes


def _open_url(url: str) -> BinaryIO:
    response: BinaryIO = urllib.request.urlopen(url, timeout=60)  # pinned https URLs
    return response


def _download(
    wheel: Wheel,
    target: Path,
    opener: Opener,
    progress: Callable[[int], None],
    cancelled: Callable[[], bool],
) -> None:
    digest = hashlib.sha256()
    size = 0
    try:
        with opener(wheel.url) as response, target.open("wb") as out:
            while chunk := response.read(_CHUNK):
                if cancelled():
                    raise InstallCancelledError("The download was cancelled.")
                out.write(chunk)
                digest.update(chunk)
                size += len(chunk)
                progress(len(chunk))
    except InstallError:
        raise
    except OSError as exc:  # URLError and friends
        raise InstallError(f"Could not download {wheel.filename}: {exc}") from exc
    if size != wheel.size or digest.hexdigest() != wheel.sha256:
        raise InstallError(
            f"{wheel.filename} is not the published file (size {size} instead of "
            f"{wheel.size}, or a different SHA256): it was not installed."
        )


def _unpack(wheel_file: Path, folder: Path) -> None:
    """Extract a wheel, refusing any member that would land outside ``folder``."""
    root = folder.resolve()
    with zipfile.ZipFile(wheel_file) as archive:
        for member in archive.infolist():
            destination = (folder / member.filename).resolve()
            if not destination.is_relative_to(root):
                raise InstallError(f"{wheel_file.name} holds an unsafe path: {member.filename}")
            archive.extract(member, folder)
            mode = (member.external_attr >> 16) & 0o777
            if mode and not member.is_dir():
                destination.chmod(mode | 0o400)


def install_opensees(
    root: Path | None = None,
    *,
    opener: Opener = _open_url,
    progress: Progress | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    key: str | None = None,
) -> SolverSettings:
    """Download, verify and unpack OpenSeesPy; return the settings that use it.

    An existing installation is replaced only once the new one is complete.

    Raises:
        InstallError: unsupported platform, network failure, a file that does
            not match its pinned digest, or an unsafe archive.
        InstallCancelledError: ``cancelled()`` became true; nothing is left behind.
    """
    wheels = wheels_for(key)
    final = install_dir(root)
    final.parent.mkdir(parents=True, exist_ok=True)
    partial = final.with_name(final.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    total = sum(w.size for w in wheels)
    done = 0

    def advance(n: int) -> None:
        nonlocal done
        done += n
        if progress is not None:
            progress(done, total)

    try:
        with tempfile.TemporaryDirectory(prefix="osstudio-engine-") as tmp:
            for wheel in wheels:
                target = Path(tmp) / wheel.filename
                _download(wheel, target, opener, advance, cancelled)
                _unpack(target, partial)
        if not (partial / "openseespy" / "__init__.py").is_file():
            raise InstallError("The downloaded files hold no openseespy package.")
        shutil.rmtree(final, ignore_errors=True)
        partial.rename(final)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return SolverSettings(engine=OPENSEES_PY, package_dir=str(final))
