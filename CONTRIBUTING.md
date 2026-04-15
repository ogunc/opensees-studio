# Contributing

Thanks for your interest. This project is in an early phase; the bar for
incoming changes is on architecture cleanliness rather than feature
breadth.

## Dev setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

## Before opening a PR

```bash
ruff check src tests
ruff format src tests
mypy src/opensees_studio/core src/opensees_studio/services
pytest -m "not slow"
```

## Architectural rules (enforced in review)

1. `core/` may not import Qt or `openseespy`. Period.
2. `services/` may not import Qt.
3. `views/` may not import `openseespy` directly — go through a service.
4. Public functions and methods need type hints and a docstring.
5. New domain entities go through Pydantic validation.
6. Long-running operations (>50 ms) run off the GUI thread.

## Commit style

Conventional Commits — `feat:`, `fix:`, `refactor:`, `docs:`, `test:`,
`chore:`, `ci:`.
