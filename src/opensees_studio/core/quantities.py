"""Reading the numbers out of the catalog's unit-carrying strings.

gidopensees stores a parameter as text with its unit — ``"4000 kN/m"``,
``"-20MPa"``, ``"0.05 m"`` — and the generated catalog keeps that form
(ADR-0001 deferred unit-aware types, so those fields are ``str`` with a
``# TODO: unit-aware type`` comment). This module reads the number back.

It deliberately does **not** convert between unit systems: OpenSees is
unit-agnostic and the application records the engineer's chosen system instead
of converting (see :mod:`opensees_studio.core.units`). A value that arrives
here is in whatever system the schema wrote it in, which is why the emitters
only ever use this to seed a default in the *user's* units, never to rewrite a
value the user typed.
"""

from __future__ import annotations

import re

#: A number at the start of the text, with an optional sign and exponent.
_NUMBER = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")

#: What separates the number from its unit in the schema's strings: a space,
#: or nothing at all ("-20MPa", "0.0ton/m^3").
_UNIT = re.compile(r"^\s*[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?\s*(.*)$")


class QuantityError(ValueError):
    """The text does not start with a number."""


def parse_quantity(value: str | int | float) -> float:
    """Return the number in ``value``, ignoring the unit.

    >>> parse_quantity("4000 kN/m")
    4000.0
    >>> parse_quantity("-20MPa")
    -20.0
    >>> parse_quantity(3)
    3.0
    """
    if isinstance(value, bool):  # bool is an int; a schema default is never a flag
        raise QuantityError(f"not a quantity: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER.match(value)
    if match is None:
        raise QuantityError(f"{value!r} does not start with a number")
    return float(match.group(1))


def split_quantity(value: str) -> tuple[float, str]:
    """Return ``(number, unit)``; the unit is ``""`` when the text has none.

    >>> split_quantity("0.05 m")
    (0.05, 'm')
    >>> split_quantity("500")
    (500.0, '')
    """
    number = parse_quantity(value)
    match = _UNIT.match(value)
    unit = (match.group(1) if match else "").strip()
    return number, unit
