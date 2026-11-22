# Modules

Every module in `src/batchslicer`, with its one responsibility. Each module's
docstring says more, including what it intentionally does not do.

## Entry points

| Module | Purpose |
|---|---|
| `__main__.py` | `python -m batchslicer` |
| `app.py` | runs one `batchslicer` invocation from start to finish ([Startup](Startup.md)) |
| `banner.py` | the start-up banner |
| `version.py` | the version number (the only place it is written) |

## core

| Module | Purpose |
|---|---|
| `core/config.py` | find, load and render the configuration; resolve its paths and programs |
| `core/locations.py` | standard per-user folders (XDG) |
| `core/logging.py` | the rotating log file |
| `core/environment.py` | start-up checks of Python, configuration, folders and the chosen slicer |

## cli

| Module | Purpose |
|---|---|
| `cli/arguments.py` | parse command-line options for runs, `setup` and `doctor` |
| `cli/menu.py` | numbered menus with search, and yes/no questions |
| `cli/slicer_prompt.py` | choose a slicer |
| `cli/preset_prompt.py` | choose printer, filament and process; find presets by name |
| `cli/profile_prompt.py` | offer saved profiles |
| `cli/file_prompt.py` | choose a model file or a folder of models |
| `cli/output_prompt.py` | choose or create the output folder |
| `cli/setup.py` | `batchslicer setup`: detect slicers, write the configuration |
| `cli/doctor.py` | `batchslicer doctor`: check the setup and report problems |

## domain

| Module | Purpose |
|---|---|
| `domain/presets.py` | `Preset`, `PresetKind`, `PresetSelection` |
| `domain/profiles.py` | `Target`, `Profile`, combining profiles, valid names |
| `domain/options.py` | `SliceOptions`, orient modes, the `--jobs` limit |

## services

| Module | Purpose |
|---|---|
| `services/slicing.py` | slice one model or a batch into job folders (parallel jobs, auto-orient retry, clean-up) |
| `services/report.py` | write `report.csv` and `report.json` |
| `services/gcode_stats.py` | read print time and filament use from G-code |

## backends

| Module | Purpose |
|---|---|
| `backends/slicers.py` | the supported slicers and how their command lines differ |
| `backends/orca.py` | build and run slicer commands (all three slicers share this CLI) |
| `backends/presets.py` | list compatible presets and resolve them into complete files |
| `backends/profiles.py` | locate built-in presets, extracting or unpacking them into the cache |
| `backends/opc.py` | read OrcaSlicer's packed `.opc` preset files |
| `backends/detection.py` | find installed slicers and their settings folders |
| `backends/backend.py` | the minimal `Backend` protocol (`run(command)`) |

## infrastructure

| Module | Purpose |
|---|---|
| `infrastructure/profiles.py` | read and write `profiles.yaml` atomically |

## Reserved

`application/`, `plugins/`, `web/` and `cli/commands/` are empty packages kept
for planned work (see [Architecture](Architecture.md)).
