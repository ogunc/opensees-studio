# Contributing

Thanks for your interest. This project is in an early phase; the bar for
incoming changes is on architecture cleanliness rather than feature
breadth.

## Branches and pull request target

- `develop` is the active development branch. Ordinary feature and fix
  pull requests target `develop`.
- `main` holds released versions and is updated from `develop` by the
  maintainer. `main` is usually behind `develop`, so do not base work on
  it or open feature pull requests against it.

Start every change from an up-to-date `develop`. In a fork, with this
repository added as the `upstream` remote:

```bash
git fetch upstream
git switch -c fix/short-name upstream/develop
```

Before you ask for review, bring in the latest `develop` (merge it, or
rebase your own branch on it) so the pull request shows only your change.

## Scope: discuss first, then keep pull requests focused

- For anything larger than a bug fix or a small, self-contained feature
  (a new element family, a new dialog or workflow, a file format change,
  packaging or CI), open an issue first and agree on the scope before
  writing a lot of code.
- One pull request does one thing. Split independent changes into
  separate pull requests, and say in the description when one depends on
  another (for example "needs #12 first").
- Keep unrelated files out of the pull request: local models, scratch
  scripts, personal notes, and version bumps or release notes (the
  maintainer cuts releases).
- A pull request that is hard to review in one sitting will be asked to
  split. That is not a judgement on the work; small pull requests get
  merged sooner.

## Dev setup

Python 3.12 is required (the README explains why). The desktop app and
the GUI tests need the `gui` extra, so install both extras:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[gui,dev]"
pre-commit install
```

`pip install -e .` alone installs the headless tier (core and services,
no Qt). It is enough for scripts, not for the app or `tests/gui`.

## Before opening a PR

These are the checks CI runs (`.github/workflows/ci.yml`). CI pins
ruff 0.16.8, the version `.pre-commit-config.yaml` also uses.

```bash
ruff check src tests
ruff format --check src tests
pytest tests/unit tests/integration tests/tools -m "not slow"
pytest tests/gui -m "not slow"
```

- CI sets `QT_QPA_PLATFORM=offscreen` for the non-GUI suites. On Linux
  without a display, run the GUI suite under a virtual display, for
  example `xvfb-run -a pytest tests/gui -m "not slow"`.
- Run `tests/gui` in one pytest process and check the exit code, not only
  the pass count (see "Test structure" in `CLAUDE.md`).
- mypy is not a CI gate yet, and the code base still has known mypy
  errors. Run
  `mypy src/opensees_studio/core src/opensees_studio/services src/opensees_studio/viewmodels`
  before and after your change and do not add new errors.
- Put the commands you ran and their result lines (passed, failed,
  skipped counts) in the pull request description.

## Architectural rules (enforced in review)

1. `core/` may not import Qt or `openseespy`. Period.
2. `services/` may not import Qt.
3. `views/` may not import `openseespy` directly — go through a service.
4. Public functions and methods need type hints and a docstring.
5. New domain entities go through Pydantic validation.
6. Long-running operations (>50 ms) run off the GUI thread.

The long form is in [`docs/architecture.md`](docs/architecture.md); the
non-obvious conventions are in [`CLAUDE.md`](CLAUDE.md).

## Commit style

Conventional Commits — `feat:`, `fix:`, `refactor:`, `docs:`, `test:`,
`chore:`, `ci:`.
