"""tools/glibc_floor.py: the newest glibc a bundle asks for, and the gate on it."""

from __future__ import annotations

from pathlib import Path

import pytest
from tools.glibc_floor import parse_version, required_glibc

from tools import glibc_floor

OBJDUMP = """
libexample.so:     file format elf64-x86-64

DYNAMIC SYMBOL TABLE:
0000000000000000      DF *UND*  0000000000000000 (GLIBC_2.2.5) free
0000000000000000      DF *UND*  0000000000000000 (GLIBC_2.34) __libc_start_main
0000000000000000      DF *UND*  0000000000000000 (GLIBC_2.17) clock_gettime
0000000000000000      DF *UND*  0000000000000000 (GLIBCXX_3.4.30) _ZNSt6chrono3_V212system_clock3nowEv
"""


def test_the_newest_glibc_version_is_found_and_glibcxx_ignored() -> None:
    assert required_glibc(OBJDUMP) == (2, 34, 0)
    assert required_glibc("no versions here") is None


def test_versions_compare_numerically() -> None:
    assert parse_version("2.35") == (2, 35, 0)
    assert parse_version("2.2.5") < parse_version("2.17") < parse_version("2.35")


def test_the_gate_fails_above_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "old.so").write_bytes(glibc_floor.ELF_MAGIC + b"rest")
    (tmp_path / "new.so").write_bytes(glibc_floor.ELF_MAGIC + b"rest")
    (tmp_path / "notes.txt").write_text("not an ELF file")
    needs = {"old.so": "(GLIBC_2.17)", "new.so": "(GLIBC_2.38)"}

    class Proc:
        def __init__(self, path: str) -> None:
            self.stdout = needs[Path(path).name]

    monkeypatch.setattr(glibc_floor.subprocess, "run", lambda cmd, **_kw: Proc(cmd[-1]))
    assert glibc_floor.main([str(tmp_path), "--max", "2.38"]) == 0
    assert "needs glibc 2.38 or newer" in capsys.readouterr().out
    assert glibc_floor.main([str(tmp_path), "--max", "2.35"]) == 1
    assert "1 file(s) need glibc newer than 2.35" in capsys.readouterr().out
