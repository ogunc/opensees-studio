"""The snapshot comparison: noise passes, a real change is named with before and after."""

from __future__ import annotations

from tools import results_snapshot as snap


def _pinned() -> dict[str, dict[str, snap.Fingerprint]]:
    return {
        "frame": {
            "1": {"kind": "StaticResults", "n_steps": 1, "disp_max": [0.01, 0.0, 1e-17]},
            "2": {"kind": "ModalResults", "periods": [0.5, 0.2]},
        }
    }


def test_noise_is_not_a_change() -> None:
    current = _pinned()
    current["frame"]["1"]["disp_max"] = [0.01 * (1 + 1e-9), 0.0, 3e-15]
    assert snap.compare(_pinned(), current) == []


def test_a_real_change_is_reported_with_before_and_after() -> None:
    current = _pinned()
    current["frame"]["2"]["periods"] = [0.5, 0.21]
    current["frame"]["1"]["n_steps"] = 2
    changes = snap.compare(_pinned(), current)
    assert [(c.case, c.quantity) for c in changes] == [("1", "n_steps"), ("2", "periods")]
    entry = snap.changes_entry(changes, "fixed X", "2026-11-13")
    assert "| frame | 2 | periods | [0.5, 0.2] | [0.5, 0.21] |" in entry
    assert entry.startswith("## 2026-11-13: fixed X")


def test_a_missing_case_is_a_change() -> None:
    current = _pinned()
    del current["frame"]["2"]
    assert [c.quantity for c in snap.compare(_pinned(), current)] == ["(case)"]


def test_fingerprint_rounding_keeps_ten_digits() -> None:
    assert snap._round(1.234567890123) == 1.23456789
