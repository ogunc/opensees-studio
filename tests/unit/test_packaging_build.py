"""The bundle's archive name has to follow the platform it was built on.

A macOS build once produced `OpenSeesStudio-linux.zip`, because the name came
from `os.name`, which is `"posix"` on both Linux and macOS. The macOS job then
attached that file to the same release as the Linux job and overwrote it: the
asset published as Linux was a Mach-O bundle no Linux machine can run.

`packaging/build.py` is loaded by path on purpose. The directory `packaging/`
shadows the PyPI `packaging` distribution that mypy and hatchling import, so
`import packaging.build` is not something a test can rely on.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

BUILD_PY = Path(__file__).resolve().parents[2] / "packaging" / "build.py"
SPEC = Path(__file__).resolve().parents[2] / "packaging" / "opensees-studio.spec"
DATA_DIR = Path(__file__).resolve().parents[2] / "src" / "opensees_studio" / "data"

#: Package data nothing imports: the AISC shape table the section picker reads
#: at runtime, with its provenance note and licence.
AISC_DATA = ("aisc_v16.csv", "README.md", "LICENSE-steelpy.txt")


def _load_build_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("osstudio_packaging_build", BUILD_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build_module() -> ModuleType:
    return _load_build_module()


@pytest.mark.parametrize(
    ("platform", "expected"),
    [("linux", "linux"), ("darwin", "macos"), ("win32", "windows")],
)
def test_the_archive_name_follows_the_platform(
    build_module: ModuleType, monkeypatch: pytest.MonkeyPatch, platform: str, expected: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)

    assert build_module.platform_suffix() == expected


@pytest.mark.parametrize(
    ("platform", "name"),
    [("linux", "OpenSeesStudio"), ("darwin", "OpenSeesStudio"), ("win32", "OpenSeesStudio.exe")],
)
def test_the_executable_name_follows_the_platform(
    build_module: ModuleType, monkeypatch: pytest.MonkeyPatch, platform: str, name: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)

    assert build_module.executable_path().name == name


def test_macos_is_not_reported_as_linux(
    build_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`os.name` is "posix" on both; the bug was asking it instead of sys.platform."""
    monkeypatch.setattr(sys, "platform", "darwin")

    assert build_module.platform_suffix() != "linux"


def test_the_frozen_bundle_ships_the_aisc_shape_table() -> None:
    """Without the spec's ``datas`` entry the picker fails on a missing CSV.

    The wheel gets these files for free (they are inside the package directory,
    verified by building one); PyInstaller only collects what a module imports,
    so the spec has to list them by hand.
    """
    spec = SPEC.read_text(encoding="utf-8")
    for name in AISC_DATA:
        assert (DATA_DIR / name).is_file(), f"{name} is missing from the package data"
        assert name in spec, f"{name} is not listed in the PyInstaller datas"
