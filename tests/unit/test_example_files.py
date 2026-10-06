"""The committed example projects are current and regenerate identically.

Each example script builds its project with a ``build_*`` function and saves
it next to itself. The committed ``.osmodel`` must be at the current schema
and must be exactly what the builder produces, on every platform: values the
scripts compute with sin, cos or exp are rounded in the script, because those
C library functions differ in the last digit between platforms.
"""

from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

import pytest

from opensees_studio.services import save_project
from opensees_studio.services.persistence import SCHEMA_VERSION

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"
EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("*.osmodel")) + sorted(
    (EXAMPLES_DIR / "official").glob("0*.osmodel")
)


def _builder_name(script: Path) -> str:
    """The ``build_*`` function the script's ``main()`` calls."""
    tree = ast.parse(script.read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    (name,) = {
        n.func.id
        for n in ast.walk(main)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id.startswith("build")
    }
    return name


def _text(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def test_every_example_has_a_committed_file() -> None:
    scripts = {p.stem for p in EXAMPLES_DIR.glob("*.py") if not p.stem.startswith("_")}
    scripts.update(p.stem for p in (EXAMPLES_DIR / "official").glob("0*.py"))
    assert {p.stem for p in EXAMPLE_FILES} == scripts


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.stem)
def test_example_file_is_at_the_current_schema_version(path: Path) -> None:
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == SCHEMA_VERSION


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.stem)
def test_regenerating_an_example_twice_gives_the_committed_bytes(
    path: Path, tmp_path: Path
) -> None:
    module = importlib.import_module(
        "examples." + ".".join(path.relative_to(EXAMPLES_DIR).with_suffix("").parts)
    )
    build = getattr(module, _builder_name(path.with_suffix(".py")))

    first = save_project(build(), tmp_path / "first" / path.name)
    second = save_project(build(), tmp_path / "second" / path.name)

    assert _text(first) == _text(second)
    assert _text(first) == _text(path)
