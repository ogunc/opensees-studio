"""Safe evaluation of the basic arithmetic a user types into a numeric field.

A numeric field accepts ``2*3.5``, ``12/4 + 1``, ``-(2.5e3 - 100)/2``: the four
operations, parentheses, unary signs and numbers with scientific notation.
:func:`evaluate_arithmetic` parses that text with a small recursive-descent
parser; it never calls ``eval``, so no name, attribute, call or power operator
can run. A plain number evaluates to exactly ``float(text)``, so a typed
``0.1`` or ``1e-10`` keeps every digit.

Pure Python: no Qt, safe to use from a script or a headless backend.
"""

from __future__ import annotations

import math
import re

__all__ = ["ARITHMETIC_CHARACTERS", "evaluate_arithmetic", "may_become_arithmetic"]

MAX_LENGTH = 1000
"""Longest expression accepted, so a pasted wall of text cannot stall the GUI."""

_MAX_DEPTH = 100
"""Deepest parenthesis nesting accepted (the parser recurses once per level)."""

_NUMBER = re.compile(r"(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")
_BLANKS = re.compile(r"\s+")
_ALIASES = str.maketrans({"×": "*", "÷": "/", "\u2212": "-"})
"""Multiplication, division and minus signs pasted from a document."""

ARITHMETIC_CHARACTERS = frozenset("0123456789.eE+-*/() \t")
"""Every character an expression, complete or half typed, may contain."""


class _Parser:
    """``expr := term (("+"|"-") term)*``, ``term := unary (("*"|"/") unary)*``,
    ``unary := ("+"|"-")* primary``, ``primary := NUMBER | "(" expr ")"``."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0
        self._depth = 0

    def parse(self) -> float:
        value = self._expr()
        self._skip_blanks()
        if self._pos != len(self._text):
            raise ValueError(f"unexpected {self._text[self._pos]!r} at {self._pos + 1}")
        return value

    def _skip_blanks(self) -> None:
        match = _BLANKS.match(self._text, self._pos)
        if match:
            self._pos = match.end()

    def _peek(self) -> str:
        self._skip_blanks()
        return self._text[self._pos] if self._pos < len(self._text) else ""

    def _expr(self) -> float:
        value = self._term()
        while (op := self._peek()) in ("+", "-"):
            self._pos += 1
            right = self._term()
            value = _finite(value + right if op == "+" else value - right)
        return value

    def _term(self) -> float:
        value = self._unary()
        while (op := self._peek()) in ("*", "/"):
            self._pos += 1
            right = self._unary()
            if op == "*":
                value = _finite(value * right)
            elif right == 0.0:
                raise ValueError("division by zero")
            else:
                value = _finite(value / right)
        return value

    def _unary(self) -> float:
        sign = 1.0
        while (op := self._peek()) in ("+", "-"):
            self._pos += 1
            if op == "-":
                sign = -sign
        return sign * self._primary()

    def _primary(self) -> float:
        char = self._peek()
        if char == "(":
            self._depth += 1
            if self._depth > _MAX_DEPTH:
                raise ValueError("parentheses nested too deeply")
            self._pos += 1
            value = self._expr()
            if self._peek() != ")":
                raise ValueError("missing ')'")
            self._pos += 1
            self._depth -= 1
            return value
        match = _NUMBER.match(self._text, self._pos)
        if match is None:
            where = repr(char) if char else "end of input"
            raise ValueError(f"expected a number, found {where}")
        self._pos = match.end()
        return _finite(float(match.group(0)))


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("result is not a finite number")
    return value


def evaluate_arithmetic(text: str) -> float:
    """The value of ``text``: a number or a ``+ - * /`` expression with parentheses.

    Blanks are ignored. Raises :class:`ValueError` on anything else, on a
    division by zero and on a result that is not finite. A plain number reads
    back exactly as ``float`` reads it.
    """
    text = text.translate(_ALIASES).strip()
    if not text:
        raise ValueError("empty expression")
    if len(text) > MAX_LENGTH:
        raise ValueError("expression too long")
    return _Parser(text).parse()


def may_become_arithmetic(text: str) -> bool:
    """Whether ``text`` only holds characters an expression may contain.

    True for half-typed input such as ``2*``, ``(3+`` or ``1e-``, which a field
    keeps as intermediate while the user types; false for letters or symbols
    no expression can hold.
    """
    text = text.translate(_ALIASES)
    return len(text) <= MAX_LENGTH and all(c in ARITHMETIC_CHARACTERS for c in text)
