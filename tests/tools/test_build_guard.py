"""The Linux bundle must not carry a private libstdc++ (Mesa GLX regression)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _build_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "oss_packaging_build", ROOT / "packaging" / "build.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_bundle_with_a_private_libstdcxx_fails_the_build(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    module = _build_module()
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module, "DIST", tmp_path)
    bundle = tmp_path / module.APP_NAME
    (bundle / "_internal" / "PySide6").mkdir(parents=True)
    (bundle / "_internal" / "libstdc++.so.6").write_bytes(b"")
    (bundle / "_internal" / "PySide6" / "libstdc++.so.6.0.30").write_bytes(b"")

    with pytest.raises(SystemExit, match="libstdc\\+\\+"):
        module.check_no_bundled_libstdcxx()


def test_a_bundle_that_uses_the_host_runtime_passes(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    module = _build_module()
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module, "DIST", tmp_path)
    bundle = tmp_path / module.APP_NAME
    bundle.mkdir()
    (bundle / "libQt6Core.so.6").write_bytes(b"")

    module.check_no_bundled_libstdcxx()

    assert "no private libstdc++" in capsys.readouterr().out
