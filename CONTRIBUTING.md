# Contributing to BatchSlicer

First of all...

Thank you for taking the time to contribute.

BatchSlicer is built around one simple goal:

> Remove friction from the 3D printing workflow through reliable, maintainable automation.

Every contribution should move the project closer to that goal.

---

# Before You Begin

Please read the following documents before making changes.

1. README.md
2. AGENTS.md
3. docs/Vision.md
4. docs/Architecture.md
5. docs/CodingStandards.md

These documents describe how the project is designed and how development decisions are made.

---

# Engineering Philosophy

We believe:

- Simple solutions are usually better.
- Readable code is more valuable than clever code.
- Architecture matters.
- Documentation is part of the implementation.
- Every feature must provide measurable value.

If a feature does not solve a real problem, it probably should not exist.

---

# Development Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Before committing, run the same checks as GitHub Actions:

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy
.venv/bin/pytest
```

After changing anything that talks to a slicer, also run the real-slicer tests
against your installed slicers (see "Testing" in the README). After changing
sending, try it once with a real printer (sending a file without `--start`
is safe).
[docs/Modules.md](docs/Modules.md) says where things live, and
[docs/Startup.md](docs/Startup.md) what happens during a run.

---

# Development Workflow

Every feature follows the same process.

1. Identify the problem.
2. Discuss the design.
3. Implement the solution.
4. Add tests.
5. Update documentation.
6. Submit for review.

We intentionally avoid implementing large features without first discussing the architecture.

---

# Pull Requests

`main` is protected: a pull request can only be merged once CI has passed on
Python 3.12 and 3.13, and `main` cannot be force-pushed or deleted.
Dependabot opens pull requests for dependency updates each week; review and
merge them like any other.

Please keep pull requests focused.

Small pull requests are much easier to review than large ones.

Where practical:

- One feature per pull request.
- One bug fix per pull request.
- One architectural change per pull request.

Avoid combining unrelated changes.

---

# Coding Standards

The project uses:

- Python 3.12+
- pathlib
- dataclasses
- type hints
- logging
- pytest

Please avoid:

- global variables
- hidden dependencies
- duplicated logic
- circular imports
- generic utility modules

Every module should have one clearly defined responsibility.

---

# Documentation

Documentation is considered part of the implementation.

New modules should include:

- module docstring
- public API documentation
- explanation of responsibilities

When changing behaviour, update the relevant documentation.

---

# Testing

New functionality should include appropriate unit tests.

Bug fixes should include regression tests whenever practical.

A feature is not complete until tests pass.

---

# Releasing

1. Make sure `main` is green on GitHub Actions.
2. Set the new version in `src/batchslicer/version.py` (`__version__`); it is
   the only place the program reads it from. Update the **Version** line at the
   top of `docs/Architecture.md` to match.
3. In `CHANGELOG.md`, move the entries under `[Unreleased]` into a new
   `## [X.Y.Z] - YYYY-MM-DD` section and update the comparison links at the
   bottom. A test checks that the current version has a section. In
   `docs/Roadmap.md`, move the release's items to **Done**.
4. Commit (`chore(release): X.Y.Z`) and merge to `main`.
5. Tag and push: `git tag -a vX.Y.Z -m "BatchSlicer X.Y.Z"` then
   `git push origin vX.Y.Z`.

Pushing the tag runs `.github/workflows/release.yml`: it checks that the tag
matches the version, runs the full checks, builds the package, and publishes a
GitHub release with the wheel and source archive attached and that version's
changelog section as the release notes. A second job then uploads the same
files to PyPI (https://pypi.org/p/batchslicer) through trusted publishing; if
the `pypi` environment requires approval, approve it in the Actions tab. PyPI
never accepts the same version twice, so a failed upload is fixed with a new
version, not a re-run with changed files.

---

# Commit Messages

Use Conventional Commits.

Examples:

feat(queue): add persistent queue

fix(config): validate missing file

docs(architecture): update startup sequence

refactor(logging): simplify logger configuration

test(queue): improve queue coverage

---

# Code Reviews

Reviews should focus on improving the software.

Question ideas.

Never question people.

Constructive discussion is encouraged.

---

# Project Values

Every contributor should aim to leave the project in a better state than they found it.

We value:

- clarity
- reliability
- maintainability
- consistency
- professionalism

over speed.

---

# Definition of Done

A task is complete when:

- Code builds successfully.
- Tests pass.
- Documentation has been updated.
- Logging has been added where appropriate.
- Type hints are complete.
- The implementation follows the documented architecture.

---

# Engineering Motto

> Build for today.

> Design for tomorrow.

> Every feature must earn its place.

> Reliability is a feature.

---

Thank you for helping make BatchSlicer better.