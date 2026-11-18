# Security Policy

## Supported versions

OpenSees Studio is pre-alpha (`0.0.x`). Only the latest released `0.0.x` version
receives fixes; there are no long-term support branches yet.

| Version | Supported |
| ------- | --------- |
| latest `0.0.x` release | :white_check_mark: |
| older `0.0.x` releases | :x: |
| `main` (unreleased) | :white_check_mark: — fixes land here first |

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Use GitHub's private vulnerability reporting:

1. Open the **Security** tab of this repository.
2. Click **Report a vulnerability** (Advisories → *Report a vulnerability*).
3. Describe the issue as precisely as you can.

That channel is private, keeps the discussion attached to the code, and lets a
fix and an advisory be prepared together.

### What to include

- The affected version (`About` dialog, or `python -c "import opensees_studio; print(opensees_studio.__version__)"`).
- The platform and Python version.
- Steps to reproduce, ideally with a minimal `.osmodel` or script.
- What an attacker gains: code execution, file read/write outside the project
  directory, crash, data loss in a saved model, etc.

### What to expect

- Acknowledgement within **7 days**.
- An assessment (accepted / not a vulnerability / needs more information) within
  **14 days**.
- Credit in the advisory once a fix ships, unless you prefer to stay anonymous.

Given the size of the project, these are best-effort targets, not a contract.

## Scope

In scope:

- The application code in `src/opensees_studio/` and the tooling in `tools/`,
  `packaging/` and `.github/`.
- The analysis CLI (`python -m opensees_studio.run`) and its handling of
  untrusted project files.
- Deserialisation of `.osmodel` files, HDF5 results and DXF imports (a crafted
  input must not execute code or escape the project directory).
- CI workflows, especially anything that runs with a token (`GITHUB_TOKEN`,
  PyPI credentials).

Out of scope:

- Vulnerabilities in upstream dependencies — report those to
  [OpenSeesPy](https://github.com/OpenSees/OpenSees), [PySide6/Qt](https://www.qt.io/),
  [VTK](https://vtk.org/) or [PyVista](https://github.com/pyvista/pyvista).
  If the combination is exploitable through this app, tell us as well.
- A malicious model file that makes the solver return wrong numbers without
  corrupting the application: that is an engineering-correctness question.
  Open a normal issue instead.
- Anything that requires an already-compromised machine or a modified local
  checkout.

## Handling secrets and data

- `.osmodel` projects and result files can contain model geometry and analysis
  output. Review them before attaching one to a public issue.
- Never commit tokens, credentials or customer data. Secret scanning and push
  protection are enabled on this repository; if a secret does slip through,
  rotate it first, then rewrite the history.

## Dependency hygiene

Dependabot keeps `pip` and GitHub Actions current, grouped by risk (see
`.github/dependabot.yml`). The OpenSeesPy wheels are deliberately pinned: they
are ABI-bound to the interpreter, so a blind bump is not a routine update.
