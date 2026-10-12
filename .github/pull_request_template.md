<!--
Feature and fix pull requests target `develop`, not `main`.
Large changes: please agree on the scope in an issue first (see CONTRIBUTING.md).
-->

## Summary

<!-- What does this change, and why? Two or three sentences. -->

## Linked issue

Closes #

## Scope and dependencies

<!--
- What is deliberately left out of this pull request?
- Does it depend on another pull request, or does another one depend on it?
- Based on `develop` at commit: ...
-->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor / cleanup
- [ ] Documentation
- [ ] CI / tooling

## Architectural checklist

- [ ] No `from PySide6` in `core/` or `services/`
- [ ] No `import openseespy` in `core/` or `views/`
- [ ] Public functions have type hints + docstrings
- [ ] Heavy work runs off the GUI thread

## Verification

<!--
Commands you ran and their result lines, for example:

    ruff check src tests                                          -> All checks passed!
    ruff format --check src tests                                 -> N files already formatted
    pytest tests/unit tests/integration tests/tools -m "not slow" -> N passed, N skipped
    pytest tests/gui -m "not slow"                                -> N passed (exit code 0)

Platform and Python version. For analysis changes, the reference values
(hand calculation, published result, or OpenSees script) the new tests
compare against.
-->

## Example model / screenshots

<!--
When relevant: an example `.osmodel` (or the script in `examples/` that
builds it) that exercises the change, and screenshots of UI changes.
-->
