# Contributing

Thanks for your interest. This project is in an early phase; the bar for
incoming changes is on architecture cleanliness rather than feature
breadth.

## Dev setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[gui,dev]"     # `[dev]` alone has no Qt: the app will not start
pre-commit install
```

Building the end-user bundle instead (or as well) needs the packaging extra:
`pip install -e ".[gui,dev,packaging]"`, then `python packaging/build.py`.
See [`packaging/README.md`](packaging/README.md).

## Before opening a PR

```bash
ruff check src tests
ruff format --check src tests
python tools/typecheck.py       # the same mypy ratchet CI enforces
lint-imports                    # the layering, also enforced in CI
pytest tests/unit tests/integration tests/tools
pytest tests/gui                # one process; check the exit code, not only the count
```

Fast loop while working on one area: `pytest -m "not slow"` skips the
tests that spawn extra interpreters (`tests/integration/test_cli_result_parity.py`).
CI does not skip them.

### The mypy ratchet

`[tool.mypy]` is strict, and the codebase has a backlog of errors, so the
check is a budget rather than a clean run: `tools/mypy-budget.txt` holds the
number of errors tolerated today and **may only go down**. Fixing errors and
lowering the number in the same commit is always welcome; raising it is not.

If a mypy or typeshed upgrade moves the count on its own, update the budget
in that commit and say so in the message. The budget is measured with the
mypy version pinned in `.github/workflows/ci.yml`.

## Architectural rules (enforced in review)

1. `core/` may not import Qt or `openseespy`. Period.
2. `services/` may not import Qt.
3. `views/` may not import `openseespy` directly — go through a service.
4. Public functions and methods need type hints and a docstring.
5. New domain entities go through Pydantic validation.
6. Long-running operations (>50 ms) run off the GUI thread.

`CLAUDE.md` collects the gotchas that are easy to break by accident (the
unsaved-changes prompt, the grid guard, how the analysis child is spawned,
the generated catalog, the eigen-determinism rule). Read it before touching
those areas.

## Commit style

Conventional Commits — `feat:`, `fix:`, `refactor:`, `docs:`, `test:`,
`chore:`, `ci:`.

## Releases

Tag `v*` on the branch that should ship. `.github/workflows/desktop.yml`
builds the Linux, Windows and macOS bundles, smoke-tests each one and
attaches the archives to the GitHub release.
