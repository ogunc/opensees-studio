"""Ground-motion record model, readers, format detection, content hash."""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core import (
    GroundMotionRecord,
    content_hash_of_bytes,
    content_hash_of_file,
    detect_format,
    read_peer_at2,
    read_record,
    read_single_column,
    read_two_column,
)

DT = 0.01
N = 400


def _sine(n: int = N, dt: float = DT, amp: float = 0.25, freq: float = 2.0) -> np.ndarray:
    t = np.arange(n) * dt
    return amp * np.sin(2.0 * np.pi * freq * t)


def _write_at2(path, values, dt, wrap: int = 5, old_header: bool = False) -> None:
    lines = [
        "PEER NGA STRONG MOTION DATABASE RECORD",
        "Imperial Valley-02, 5/19/1940, El Centro Array #9, 180",
        "ACCELERATION TIME SERIES IN UNITS OF G",
    ]
    if old_header:
        lines.append(f"NPTS= {len(values)}, DT= {dt} SEC")
    else:
        lines.append(f"{len(values)}    {dt}    NPTS, DT")
    for i in range(0, len(values), wrap):
        lines.append("  ".join(f"{v: .7E}" for v in values[i : i + wrap]))
    path.write_text("\n".join(lines) + "\n")


# ──────────────────────────── AT2 ────────────────────────────
@pytest.mark.parametrize("old_header", [False, True], ids=["nga_header", "smd_header"])
def test_at2_round_trips_a_sine(tmp_path, old_header) -> None:
    values = _sine()
    path = tmp_path / "record.AT2"
    _write_at2(path, values, DT, old_header=old_header)

    dt, accel, fields = read_peer_at2(path)
    assert dt == pytest.approx(DT)
    assert accel == pytest.approx(values, abs=1e-7)
    assert fields["npts"] == N
    assert fields["dt"] == pytest.approx(DT)


def test_at2_header_fields_parsed(tmp_path) -> None:
    path = tmp_path / "record.AT2"
    _write_at2(path, _sine(), DT)
    _dt, _accel, fields = read_peer_at2(path)
    assert fields["units"] == "G"
    assert "El Centro" in fields["event"]


def test_at2_truncates_to_npts(tmp_path) -> None:
    """Trailing values beyond the announced NPTS are dropped, not kept."""
    values = _sine(20)
    path = tmp_path / "record.AT2"
    lines = [f"16 {DT} NPTS, DT", "  ".join(str(v) for v in values)]
    path.write_text("\n".join(lines))
    _dt, accel, _fields = read_peer_at2(path)
    assert len(accel) == 16


def test_at2_rejects_headerless_file(tmp_path) -> None:
    path = tmp_path / "plain.txt"
    path.write_text("0.1 0.2 0.3\n")
    with pytest.raises(ValueError, match="NPTS, DT"):
        read_peer_at2(path)


def test_at2_rejects_short_data(tmp_path) -> None:
    path = tmp_path / "short.AT2"
    path.write_text(f"10 {DT} NPTS, DT\n0.1 0.2 0.3\n")
    with pytest.raises(ValueError, match="NPTS=10 but only 3"):
        read_peer_at2(path)


# ──────────────────────────── two-column ────────────────────────────
@pytest.mark.parametrize("sep", [" ", ", "], ids=["whitespace", "comma"])
def test_two_column_round_trips_a_sine(tmp_path, sep) -> None:
    values = _sine()
    t = np.arange(N) * DT
    path = tmp_path / "record.txt"
    path.write_text("\n".join(f"{ti:.6f}{sep}{vi:.9f}" for ti, vi in zip(t, values, strict=True)))

    dt, accel, _fields = read_two_column(path)
    assert dt == pytest.approx(DT, rel=1e-6)
    assert accel == pytest.approx(values, abs=1e-8)


def test_two_column_rejects_non_uniform_dt(tmp_path) -> None:
    path = tmp_path / "bad.txt"
    path.write_text("0.00 0.1\n0.01 0.2\n0.03 0.3\n0.04 0.4\n")
    with pytest.raises(ValueError, match="non-uniform time step"):
        read_two_column(path)


def test_two_column_rejects_wrong_column_count(tmp_path) -> None:
    path = tmp_path / "bad.txt"
    path.write_text("0.00 0.1\n0.01 0.2 0.9\n")
    with pytest.raises(ValueError, match="expected 2 columns"):
        read_two_column(path)


# ──────────────────────────── single column ────────────────────────────
def test_single_column_round_trips_a_sine(tmp_path) -> None:
    values = _sine()
    path = tmp_path / "record.txt"
    path.write_text("\n".join(f"{v:.9f}" for v in values))
    dt, accel, _fields = read_single_column(path, DT)
    assert dt == DT
    assert accel == pytest.approx(values, abs=1e-8)


def test_single_column_reads_wrapped_rows_row_wise(tmp_path) -> None:
    """PEER-style 5-per-line wrapping (like examples/data/A10000.txt)."""
    values = _sine(25)
    path = tmp_path / "record.txt"
    path.write_text(
        "\n".join("  ".join(f"{v:.9f}" for v in values[i : i + 5]) for i in range(0, 25, 5))
    )
    _dt, accel, _fields = read_single_column(path, DT)
    assert accel == pytest.approx(values, abs=1e-8)


def test_single_column_requires_positive_dt(tmp_path) -> None:
    path = tmp_path / "record.txt"
    path.write_text("0.1\n0.2\n")
    with pytest.raises(ValueError, match="dt must be positive"):
        read_single_column(path, 0.0)


# ──────────────────────────── detection and dispatch ────────────────────────────
def test_detect_format(tmp_path) -> None:
    at2 = tmp_path / "r.AT2"
    _write_at2(at2, _sine(20), DT)
    two = tmp_path / "two.txt"
    two.write_text("0.00 0.1\n0.01 0.2\n0.02 0.3\n")
    one = tmp_path / "one.txt"
    one.write_text("0.1 0.2 0.3\n0.4 0.5 0.6\n")

    assert detect_format(at2) == "peer_at2"
    assert detect_format(two) == "two_column"
    assert detect_format(one) == "single_column"


def test_detect_format_wrapped_pairs_are_not_two_column(tmp_path) -> None:
    """Two values per line but a non-increasing first column is data, not time."""
    path = tmp_path / "pairs.txt"
    path.write_text("0.5 0.1\n0.3 0.2\n")
    assert detect_format(path) == "single_column"


def test_detect_format_rejects_prose(tmp_path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("this is not a record\n")
    with pytest.raises(ValueError, match="unrecognised"):
        detect_format(path)


def test_read_record_dispatch_and_override(tmp_path) -> None:
    """An explicit format override wins over what detection would say."""
    one = tmp_path / "one.txt"
    one.write_text("0.1\n0.2\n0.3\n")
    dt, accel, _f = read_record(one, "single_column", dt=0.02)
    assert dt == 0.02
    assert len(accel) == 3
    with pytest.raises(ValueError, match="requires an explicit dt"):
        read_record(one, "single_column")


# ──────────────────────────── hashing ────────────────────────────
def test_content_hash_stable_across_crlf_lf(tmp_path) -> None:
    lf = tmp_path / "lf.txt"
    crlf = tmp_path / "crlf.txt"
    lf.write_bytes(b"0.1 0.2\n0.3 0.4\n")
    crlf.write_bytes(b"0.1 0.2\r\n0.3 0.4\r\n")
    assert content_hash_of_file(lf) == content_hash_of_file(crlf)
    assert content_hash_of_file(lf) == content_hash_of_bytes(b"0.1 0.2\n0.3 0.4\n")


def test_content_hash_differs_for_different_content() -> None:
    assert content_hash_of_bytes(b"a") != content_hash_of_bytes(b"b")


# ──────────────────────────── model ────────────────────────────
def test_ground_motion_record_model_basics() -> None:
    rec = GroundMotionRecord(
        id=1,
        name="ElCentro-180",
        source_path="data/elcentro.AT2",
        content_hash="ab" * 32,
        format="peer_at2",
        dt=0.02,
        npts=1559,
        accel_units="g",
        source_note="Imperial Valley 1940, El Centro Array #9, 180",
        total_duration=1558 * 0.02,
    )
    assert rec.status == "ok"
    assert rec.total_duration == pytest.approx(31.16)


def test_ground_motion_record_rejects_bad_values() -> None:
    with pytest.raises(ValueError):
        GroundMotionRecord(id=1, source_path="x", format="peer_at2", dt=-0.01, npts=10)
    with pytest.raises(ValueError):
        GroundMotionRecord(id=1, source_path="x", format="not_a_format", dt=0.01, npts=10)
