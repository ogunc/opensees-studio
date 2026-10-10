"""Legacy entry points for PEER strong-motion files.

Parsing lives in :mod:`opensees_studio.core.ground_motion` since GM-1
(:func:`~opensees_studio.core.read_peer_at2` and
:func:`~opensees_studio.core.read_plain_values`). This module only keeps
the older tuple-returning signatures used by the Path time-series
dialog and the example scripts, so there is one AT2 parser in the code
base.
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core.ground_motion import read_peer_at2, read_plain_values


def parse_peer_record(path: str | Path) -> tuple[float, int, list[float]]:
    """Return ``(dt, n_pts, values)`` parsed from a PEER AT2 / NGA record.

    Accepts both the new NGA header (``3930 0.00500 NPTS, DT``) and the
    old SMD header (``NPTS=  3930, DT= .00500 SEC``). Values are
    dimensionless (normally g); the caller applies the unit factor.

    Raises ``ValueError`` when no ``NPTS, DT`` header is found (import
    the file as plain values instead), when no data follows the header,
    or when fewer values than ``NPTS`` follow it.
    """
    dt, values, fields = read_peer_at2(path)
    return dt, int(fields["npts"]), values.tolist()


def parse_plain_values(path: str | Path) -> list[float]:
    """Return every numeric value in ``path`` (no header; caller supplies dt).

    Raises ``ValueError`` when the file holds no values or a non-numeric
    token.
    """
    return read_plain_values(path)
