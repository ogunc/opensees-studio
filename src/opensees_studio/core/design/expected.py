"""Expected-strength helpers shared by the AISC 341 and 358 layers.

The module is deliberately a leaf: no imports from the rest of the design
package, so both layers can use it without an import cycle.
"""

from __future__ import annotations


def cpr(fy: float, fu: float | None = None) -> float:
    """AISC 358: ``Cpr = (Fy + Fu)/(2 Fy) <= 1.2``; 1.2 without ``Fu``."""
    if fu is None or fy <= 0.0:
        return 1.2
    return min(1.2, (fy + fu) / (2.0 * fy))
