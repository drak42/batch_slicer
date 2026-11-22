# Coding Standards

The standards below are what the code follows today; most are checked by the
tools on every push (see "Checks").

## Language and style

- Python 3.12 or newer, with type hints on every function.
- `pathlib.Path` for paths, never `os.path`.
- `dataclasses` (usually `frozen=True, slots=True`) for value objects.
- Lines up to 100 characters.
- No global state, no generic `utils.py`, no circular imports.
- Each module has one responsibility and starts with a docstring saying what
  it does and what it intentionally does not do. Every public class and
  function has a docstring.
- User-facing text is plain and specific: say what happened and what to do.

## Behaviour

- Diagnostics go through the logging service (`core/logging.py`); `print()` is
  only for what the user is meant to see. Errors go to stderr.
- Configuration is read only through `core/config.py`; paths come from
  `Config.get_path()` / `get_program()`.
- The slicers' own folders are only read, never written.
- Slicer processes run only through `backends/orca.py`, which applies the
  timeout and stops them on Ctrl+C.
- Printers are contacted only through the clients in `infrastructure/`
  (`moonraker.py`, `octoprint.py`, chosen by `printer_clients.py`), with the
  Python standard library (no extra dependencies).
- G-code files are changed after slicing only by `services/thumbnails.py`,
  which replaces a file in one step so it is never left half-written.
- Expected problems raise a specific error (`PresetError`, `ProfileError`,
  `SlicerSelectionError`, ...) with a message for the user; `app.py` turns
  them into an exit status.

## Tests

- New behaviour comes with tests; a bug fix with a test that would have caught
  it.
- Tests never touch the real home folder (`tests/conftest.py` redirects the
  standard locations to temporary folders) and never contact a real printer
  (the `fake_moonraker` and `fake_octoprint` fixtures run stand-ins on a local port).
- Tests that need a real slicer are skipped unless pointed at one (see the
  README's "Testing" section).

## Checks

Run before every commit; GitHub Actions runs the same on Python 3.12 and 3.13:

```bash
.venv/bin/ruff check src tests   # rules E4, E7, E9, F, I, B (pyproject.toml)
.venv/bin/mypy                   # type check of src/
.venv/bin/pytest
```

## Commits

[Conventional Commits](https://www.conventionalcommits.org/), for example
`feat(presets): ...`, `fix(slicing): ...`, `docs: ...`, `chore(release): X.Y.Z`.
Work happens on a branch and is merged to `main` when it passes the checks.
