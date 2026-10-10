"""
Tests for tools/gidopensees_import/codegen.py: the header stamp.

The stamp is derived from schemas.json and CODEGEN_VERSION, never from the
wall clock, so two runs over the same source must write identical files.
"""

from __future__ import annotations

import re
from pathlib import Path

from tools.gidopensees_import.codegen import CODEGEN_VERSION, _source_stamp, run_codegen

SCHEMAS = Path(__file__).resolve().parents[2] / "tools" / "gidopensees_import" / "schemas.json"


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*.py")}


def test_codegen_twice_writes_identical_output(tmp_path: Path) -> None:
    first = tmp_path / "run1" / "catalog" / "generated"
    second = tmp_path / "run2" / "catalog" / "generated"
    run_codegen(SCHEMAS, first)
    run_codegen(SCHEMAS, second)

    snap1 = _snapshot(tmp_path / "run1")
    snap2 = _snapshot(tmp_path / "run2")
    assert len(snap1) > 90  # 58 materials, 39 conditions, the package files
    assert snap1 == snap2

    # Regenerating over an existing tree is a no-op as well.
    run_codegen(SCHEMAS, first)
    assert _snapshot(tmp_path / "run1") == snap1


def test_generated_header_carries_source_stamp_and_no_clock(tmp_path: Path) -> None:
    out = tmp_path / "catalog" / "generated"
    run_codegen(SCHEMAS, out)

    stamp = _source_stamp(SCHEMAS)
    assert re.fullmatch(
        rf"from schemas\.json sha256:[0-9a-f]{{12}}, codegen v{CODEGEN_VERSION}", stamp
    )
    for rel, raw in _snapshot(tmp_path).items():
        if rel == "catalog/curated/__init__.py":
            continue  # empty placeholder, no header
        head = raw.decode("utf-8").splitlines()[:4]
        assert any(f"Generated {stamp}" in line for line in head), rel
        assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", "\n".join(head)), rel


def test_source_stamp_ignores_line_ending_style(tmp_path: Path) -> None:
    lf = tmp_path / "lf" / "schemas.json"
    crlf = tmp_path / "crlf" / "schemas.json"
    lf.parent.mkdir()
    crlf.parent.mkdir()
    lf.write_bytes(b'{\n  "a": 1\n}\n')
    crlf.write_bytes(b'{\r\n  "a": 1\r\n}\r\n')
    assert _source_stamp(lf) == _source_stamp(crlf)
