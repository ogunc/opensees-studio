"""The OpenSeesPy installer: pinned wheels, verification, safe unpacking, cancelling."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from opensees_studio.services import engine_install as ei


def _wheel_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def _fake(monkeypatch: pytest.MonkeyPatch, payloads: list[bytes]) -> ei.Opener:
    """Pin WHEELS to ``payloads`` and serve them from memory, as PyPI would."""
    wheels = tuple(
        ei.Wheel(f"w{i}.whl", f"https://example/w{i}.whl", len(p), hashlib.sha256(p).hexdigest())
        for i, p in enumerate(payloads)
    )
    monkeypatch.setitem(ei.WHEELS, "test-arch", wheels)
    by_url = {w.url: p for w, p in zip(wheels, payloads, strict=True)}
    return lambda url: io.BytesIO(by_url[url])  # type: ignore[return-value]


GOOD = [
    _wheel_bytes({"openseespy/__init__.py": "", "openseespy-3.8.0.0.dist-info/METADATA": "x"}),
    _wheel_bytes({"openseespylinux/__init__.py": "", "openseespylinux/opensees.so": "lib"}),
]


def test_every_platform_has_the_wrapper_and_one_native_wheel() -> None:
    for key, wheels in ei.WHEELS.items():
        if key == "test-arch":
            continue
        assert wheels[0].filename.startswith("openseespy-3.8.0.0")
        assert len(wheels) == 2 and all(len(w.sha256) == 64 for w in wheels)
        assert all(w.url.startswith("https://files.pythonhosted.org/") for w in wheels)


def test_an_unsupported_platform_says_what_to_do() -> None:
    with pytest.raises(ei.InstallError, match="Options → Solver"):
        ei.wheels_for("plan9-mips")


def test_install_verifies_unpacks_and_points_at_the_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opener = _fake(monkeypatch, GOOD)
    seen: list[tuple[int, int]] = []
    settings = ei.install_opensees(
        tmp_path, opener=opener, key="test-arch", progress=lambda d, t: seen.append((d, t))
    )
    folder = tmp_path / "openseespy-3.8.0.0"
    assert settings.package_dir == str(folder)
    assert (folder / "openseespy" / "__init__.py").is_file()
    assert (folder / "openseespylinux" / "opensees.so").read_text() == "lib"
    assert seen[-1] == (sum(map(len, GOOD)), sum(map(len, GOOD)))
    assert not (tmp_path / "openseespy-3.8.0.0.partial").exists()


def test_a_tampered_file_is_refused_and_nothing_is_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opener = _fake(monkeypatch, GOOD)

    def tampered(url: str):  # type: ignore[no-untyped-def]
        if url.endswith("w1.whl"):
            return io.BytesIO(GOOD[1][:-1] + b"!")
        return opener(url)

    with pytest.raises(ei.InstallError, match="not the published file"):
        ei.install_opensees(tmp_path, opener=tampered, key="test-arch")
    assert list(tmp_path.iterdir()) == []


def test_cancelling_leaves_nothing_and_keeps_an_earlier_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opener = _fake(monkeypatch, GOOD)
    ei.install_opensees(tmp_path, opener=opener, key="test-arch")
    with pytest.raises(ei.InstallCancelledError):
        ei.install_opensees(tmp_path, opener=opener, key="test-arch", cancelled=lambda: True)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["openseespy-3.8.0.0"]


def test_an_archive_that_escapes_its_folder_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opener = _fake(monkeypatch, [_wheel_bytes({"../evil.py": "x"})])
    with pytest.raises(ei.InstallError, match="unsafe path"):
        ei.install_opensees(tmp_path / "root", opener=opener, key="test-arch")
    assert not (tmp_path / "evil.py").exists()


def test_files_without_the_package_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opener = _fake(monkeypatch, [_wheel_bytes({"something/__init__.py": ""})])
    with pytest.raises(ei.InstallError, match="no openseespy package"):
        ei.install_opensees(tmp_path, opener=opener, key="test-arch")


def test_a_network_failure_is_an_install_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake(monkeypatch, GOOD)

    def offline(url: str):  # type: ignore[no-untyped-def]
        raise OSError("network unreachable")

    with pytest.raises(ei.InstallError, match="Could not download"):
        ei.install_opensees(tmp_path, opener=offline, key="test-arch")
