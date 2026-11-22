"""Basic arithmetic in numeric input: the four operations, parentheses, no eval."""

from __future__ import annotations

import pytest

from opensees_studio.core.arithmetic import (
    MAX_LENGTH,
    evaluate_arithmetic,
    may_become_arithmetic,
)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("2*3.5", 7.0),
        ("12/4 + 1", 4.0),
        ("10 - 2 - 3", 5.0),
        ("8 / 2 / 2", 2.0),
        ("2 + 3 * 4", 14.0),
        ("(2 + 3) * 4", 20.0),
        ("-(2.5e3 - 100)/2", -1200.0),
        ("--3", 3.0),
        ("+-3", -3.0),
        ("2*-3", -6.0),
        ("1e-3*2", 0.002),
        ("2e-3-1", 2e-3 - 1),
        (".5 + 1.", 1.5),
        ("((1))", 1.0),
        (" 6 × 2 ÷ 4 \u2212 1 ", 2.0),
    ],
)
def test_expressions_evaluate(text: str, value: float) -> None:
    assert evaluate_arithmetic(text) == pytest.approx(value, rel=0, abs=1e-15)


@pytest.mark.parametrize("text", ["0.1", "1e-10", "1E-10", "0.123456789012345", "29000", "-0.0"])
def test_a_plain_number_reads_back_exactly(text: str) -> None:
    assert evaluate_arithmetic(text) == float(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "  ",
        "2*",
        "(3+",
        "3)",
        "1e-",
        "2 3",
        "1/0",
        "1/(2-2)",
        "1e308*10",
        "nan",
        "inf",
        "2**3",
        "__import__('os')",
        "abs(-1)",
        "1,5",
    ],
)
def test_anything_else_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        evaluate_arithmetic(text)


def test_deep_nesting_and_long_text_are_refused_not_crashed() -> None:
    with pytest.raises(ValueError):
        evaluate_arithmetic("(" * 500 + "1" + ")" * 500)
    with pytest.raises(ValueError):
        evaluate_arithmetic("1+" * MAX_LENGTH + "1")


@pytest.mark.parametrize("text", ["-", "2*", "(3+", "1e-", "1.", "(2+3)/"])
def test_half_typed_input_may_become_an_expression(text: str) -> None:
    assert may_become_arithmetic(text)


@pytest.mark.parametrize("text", ["abc", "2^3", "1,5", "x+1", "2%"])
def test_foreign_characters_never_become_one(text: str) -> None:
    assert not may_become_arithmetic(text)
