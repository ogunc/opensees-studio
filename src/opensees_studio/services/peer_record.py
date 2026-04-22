"""Parser for PEER strong-motion ground-motion files.

Mirrors the OpenSees ``ReadRecord.tcl`` procedure: accepts both the
*new* NGA-format header (``NPTS, DT`` on the last header line, values
first) and the *old* SMD format (``NPTS=  3930, DT= .00500 SEC``).

Returns (dt, npts, values). Values are dimensionless (normally g for
acceleration records); the caller applies the unit factor when
building the PathTimeSeries.
"""

from __future__ import annotations

import re
from pathlib import Path


def parse_peer_record(path: str | Path) -> tuple[float, int, list[float]]:
    """Return ``(dt, n_pts, values)`` parsed from a PEER-format record.

    Raises ``ValueError`` if neither NGA nor old-SMD header pattern
    matches; falls back to treating the file as a plain list of
    whitespace-separated values (dt/npts unknown → caller supplies).
    """
    text = Path(path).read_text()
    lines = text.splitlines()

    dt: float | None = None
    npts: int | None = None
    data_start: int | None = None

    # Look at the first ~5 header lines.
    for i, line in enumerate(lines[:10]):
        stripped = line.strip()
        if not stripped:
            continue
        # Old SMD format: "NPTS=  3930, DT= .00500 SEC"
        m_old = re.search(
            r"NPTS\s*=\s*(\d+)[\s,]+DT\s*=\s*([0-9.eE+\-]+)",
            stripped,
        )
        if m_old:
            npts = int(m_old.group(1))
            dt = float(m_old.group(2))
            data_start = i + 1
            break
        # New NGA format: "3930 0.00500 NPTS, DT"
        m_new = re.match(
            r"^(\d+)\s+([0-9.eE+\-]+)\s+NPTS\s*,\s*DT", stripped,
        )
        if m_new:
            npts = int(m_new.group(1))
            dt = float(m_new.group(2))
            data_start = i + 1
            break

    if dt is None or npts is None or data_start is None:
        raise ValueError(
            "Could not find 'NPTS ... DT' header in file. "
            "Use 'Load as plain values' import for raw number lists.",
        )

    values: list[float] = []
    for line in lines[data_start:]:
        for tok in line.split():
            try:
                values.append(float(tok))
            except ValueError:
                pass   # skip stray tokens
    if not values:
        raise ValueError("Header parsed but no numeric data lines found.")
    return dt, npts, values


def parse_plain_values(path: str | Path) -> list[float]:
    """Return every whitespace-separated float in ``path``.

    Used when the user imports a naked number list (no PEER header) —
    the caller asks for dt separately.
    """
    text = Path(path).read_text()
    vals: list[float] = []
    for line in text.splitlines():
        for tok in line.split():
            try:
                vals.append(float(tok))
            except ValueError:
                pass
    if not vals:
        raise ValueError(f"{path} contains no numeric values.")
    return vals
