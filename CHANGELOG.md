# Changelog

All notable changes to BatchSlicer are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **`batchslicer doctor`** checks the configuration, folders and each
  configured slicer (does it run, does it accept BatchSlicer's commands, how
  many printers it offers) and saved profiles, and reports any problems with
  what to do about them. Exit status 0 or 1.
- A weekly GitHub Actions job tests BatchSlicer against the newest release of
  OrcaSlicer, Creality Print and Bambu Studio.
- `docs/Vision.md`, `docs/Roadmap.md` and `docs/Startup.md`.

### Changed

- The log file is rotated at about 1 MB, keeping the three most recent old
  logs.
- "One model file" mode also lists models in subfolders of the incoming folder.
  Text containing `/` is now a search unless it names an existing file.

## [0.3.0] - 2026-11-20

Reuse your choices and slice for several printers at once.

### Added

- **Profiles**: save a run's choices with `--save-profile NAME`, reuse them with
  `--profile NAME` (other options override the profile), and repeat the last
  run with `--last`; every run is remembered automatically. Interactive runs
  without options offer the saved profiles first. `--list-profiles` and
  `--delete-profile` manage them; they are stored in
  `~/.local/share/batchslicer/profiles.yaml`.
- **Several printers per run**: repeat `--profile` (or answer "yes" to "Slice
  for another printer as well?") to slice the same models for more than one
  printer, each with its own slicer and presets, into its own output subfolder,
  with a summary at the end. Such runs can be saved as one profile (a `targets`
  list) and repeated with `--last`.
- A failed slice's reason now includes the slicer's own validation message
  (for example OrcaSlicer's "Too small line width").

### Fixed

- Slicers run inside the job's output folder, so files they write on failure
  (such as OrcaSlicer's `00000.log`) no longer appear in the current folder.

## [0.2.0] - 2026-11-20

The first usable release: slice single models or whole folder trees with
OrcaSlicer, Creality Print or Bambu Studio, interactively or unattended.

### Added

- **Three slicers.** OrcaSlicer, Creality Print and Bambu Studio, driven
  through their command-line slicing. Creality Print is run in its `--cli`
  mode with `--need-gcode-file`; options a slicer lacks are refused with a
  clear message.
- **Preset selection** for OrcaSlicer and Creality Print: choose a printer,
  then a compatible filament and process. Lists match the slicer's own menus
  (printers you added, filaments you made visible); your own presets come
  first, marked "(mine)"; type text to search. Chosen presets are combined
  with everything they inherit from into complete files the slicer CLI
  accepts. OrcaSlicer 2.4's built-in presets are extracted once from its
  AppImage and cached.
- **Folder batches.** Slice every `.stl`, `.3mf` and `.obj` in a folder and its
  subfolders, with per-file progress. Results mirror the source folders; a
  failed model does not stop the batch, and the summary gives each failure's
  reason as reported by the slicer.
- **Output folders.** Every run gets its own time-stamped folder that also
  keeps the exact presets used. G-code is named after the model
  (`bracket.stl` → `bracket.gcode`, multi-plate projects →
  `<name>_plate_N.gcode`). Choose the default output folder, an existing one,
  or create a new one.
- **Command-line options** for every choice: `--slicer`, `--printer`,
  `--filament`, `--process`, `--input`, `--output`, `--config`. Anything left
  out is asked for, unless `--no-prompt` is given for unattended runs.
  `--list-presets` shows preset names, and mistyped names get suggestions.
- **`batchslicer setup`** finds installed slicers (AppImages in the usual
  folders, programs on PATH), recommends the newest stable version, finds each
  slicer's settings folder, and writes the configuration. An existing
  configuration is only replaced after confirmation (or `--force`) and is kept
  as a `.bak` copy.
- **Standard locations.** Configuration is found via `--config`,
  `BATCHSLICER_CONFIG`, `./config/config.yaml`, then
  `~/.config/batchslicer/config.yaml`. Paths may use `~` and are relative to
  the configuration file. Models and results default to `~/BatchSlicer`, logs
  to `~/.local/state/batchslicer`, caches to `~/.cache/batchslicer`.
- **Clean stopping and error reporting.** Ctrl+C stops with exit status 130; an
  interrupted batch keeps the models already sliced and reports what was not
  started. Unexpected errors print one line and the log location, with full
  details in the log. Errors go to stderr. Exit statuses: 0 success,
  1 failure, 2 invalid option, 130 interrupted.
- **Configuration, logging and startup checks.** Startup verifies the Python
  version, configuration, working folders and the chosen slicer, naming each
  problem it finds. Every run is logged: choices made, slicer commands and
  their results, and the slicer's error output when a model fails.
- **Continuous integration**: ruff, mypy and pytest run on Python 3.12 and 3.13
  for every push and pull request, and pushing a version tag builds the
  package and publishes a GitHub release.

### Changed

- Renamed the project from OrcaBatch to BatchSlicer (package `batchslicer`,
  command `batchslicer`).
- `config/config.yaml` is no longer part of the repository;
  `config/config.example.yaml` is the documented template.
- The version number is written only in `src/batchslicer/version.py`.

### Fixed

- OrcaSlicer slice commands now follow its command-line interface: `--slice`
  takes a plate number, the model is the last argument, and settings files are
  passed as one `;`-separated list. The unsupported `--version` call was
  removed.
- Slicer runs that hang are stopped after a timeout (30 minutes by default).
- OrcaSlicer's `result.json` is no longer left in the working folder.
- Logs are written to the configured logs folder.
- Declared the PyYAML dependency so a clean install works.

## [0.1.0] - 2026-08-11

- Initial project bootstrap: project structure, architecture and coding
  documents, and version information.

[Unreleased]: https://github.com/drak42/batch_slicer/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/drak42/batch_slicer/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/drak42/batch_slicer/compare/v0.1.0-bootstrap...v0.2.0
[0.1.0]: https://github.com/drak42/batch_slicer/releases/tag/v0.1.0-bootstrap
