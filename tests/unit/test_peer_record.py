"""PEER record parser tests — NGA + old SMD headers + plain values."""

from __future__ import annotations

import textwrap

import pytest

from opensees_studio.services.peer_record import (
    parse_peer_record,
    parse_plain_values,
)


def _write(tmp_path, text: str, name: str = "rec.at2"):  # type: ignore[no-untyped-def]
    p = tmp_path / name
    p.write_text(text)
    return p


def test_parse_nga_format(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """New PEER NGA header: '3930 0.00500 NPTS, DT' on line 4."""
    content = textwrap.dedent("""\
        PACIFIC ENGINEERING AND ANALYSIS STRONG-MOTION DATA
        IMPERIAL VALLEY 10/15/79 2319, EL CENTRO ARRAY 6, 230
        ACCELERATION TIME HISTORY IN UNITS OF G
        5 0.01 NPTS, DT
        0.001  0.002  0.003
        0.004  0.005
    """)
    path = _write(tmp_path, content)
    dt, npts, vals = parse_peer_record(path)
    assert dt == pytest.approx(0.01)
    assert npts == 5
    assert vals == pytest.approx([0.001, 0.002, 0.003, 0.004, 0.005])


def test_parse_old_smd_format(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Old SMD header: 'NPTS=  3930, DT= .00500 SEC'."""
    content = textwrap.dedent("""\
        PACIFIC ENGINEERING
        IMPERIAL VALLEY
        ACCELERATION
        NPTS=  5, DT= .01000 SEC
        0.1 0.2 0.3
        0.4 0.5
    """)
    path = _write(tmp_path, content)
    dt, npts, vals = parse_peer_record(path)
    assert dt == pytest.approx(0.01)
    assert npts == 5
    assert vals == pytest.approx([0.1, 0.2, 0.3, 0.4, 0.5])


def test_parse_peer_with_no_header_raises(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = _write(tmp_path, "0.1 0.2 0.3 0.4 0.5")
    with pytest.raises(ValueError):
        parse_peer_record(path)


def test_parse_plain_values(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = _write(tmp_path, "0.1 0.2\n0.3 0.4\n0.5", "vals.txt")
    assert parse_plain_values(path) == pytest.approx([0.1, 0.2, 0.3, 0.4, 0.5])


def test_parse_plain_values_rejects_empty(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = _write(tmp_path, "# just a comment", "empty.txt")
    with pytest.raises(ValueError):
        parse_plain_values(path)
