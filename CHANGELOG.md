# Changelog

## Unreleased

- feat(app): Ctrl+C stops cleanly with exit status 130; an interrupted batch keeps the models already sliced and reports what was not started. Unexpected errors print one line and the log location, with the full traceback in the log. Error messages go to stderr.
- ci: GitHub Actions runs ruff, mypy and pytest on Python 3.12 and 3.13 for every push to main and every pull request. ruff and mypy versions are pinned in the dev extra.
- test: the suite keeps BatchSlicer's default log and cache folders out of the real home folder.
- feat(setup): `batchslicer setup` finds installed slicers (AppImages in the usual folders, programs on PATH), recommends the newest stable version, finds each slicer's settings folder, and writes the configuration. Existing configuration is only replaced after confirmation (or `--force`) and kept as `.bak`.
- feat(config): configuration is found via `--config`, `BATCHSLICER_CONFIG`, `./config/config.yaml`, then `~/.config/batchslicer/config.yaml`. Paths may use `~`, relative paths are relative to the configuration file, and folders default to `~/BatchSlicer/{incoming,output}`, `~/.local/state/batchslicer` (logs) and `~/.cache/batchslicer` (cache). BatchSlicer no longer depends on the folder it is run from.
- fix(logging): logs are written to the configured logs folder.
- chore(config): `config/config.yaml` is no longer tracked; `config/config.example.yaml` is the documented template. Removed the unused `Config.validate()`.
- feat(cli): command-line options for every choice (`--slicer`, `--printer`, `--filament`, `--process`, `--input`, `--output`), `--no-prompt` for unattended runs, and `--list-presets` to find preset names. Unknown preset names suggest close matches. Adds a `batchslicer` command.
- feat(presets): preset selection for OrcaSlicer. Built-in presets are extracted once from the OrcaSlicer AppImage (its data folder only has packed `.opc` files) and cached in `data/slicer-profiles/`. Verified with real OrcaSlicer 2.4 slices.
- feat(presets): filament lists only show built-in filaments made visible in the slicer, matching its own menus (applies to Creality Print too).
- feat(slicing): name G-code after the model (`bracket.stl` → `bracket.gcode`; multi-plate projects → `<name>_plate_N.gcode`) instead of `plate_1.gcode`.
- feat(slicing): slice every model in a folder and its subfolders as a batch, with per-file progress and a summary of failures; results mirror the source folder structure.
- feat(cli): choose the output folder: the configured default, an existing subfolder, or a new folder created after confirmation.
- feat(slicing): after setup, choose a model file (.stl/.3mf/.obj) from the incoming folder or by path, and slice it into its own timestamped job folder under output, which also keeps the exact presets used. Failures show the slicer's own reason from result.json.
- feat(presets): after choosing Creality Print, choose a printer, then a compatible filament and process preset (your own presets listed first; type text to search). Chosen presets can be written as complete files the Creality CLI accepts; verified with real slices.
- fix(backends): pass `--need-gcode-file` to Creality Print so slicing writes G-code.
- feat(backends): support Creality Print and Bambu Studio alongside OrcaSlicer; the user is prompted to choose a configured slicer at startup before the application proceeds. New `creality_print` and `bambu_studio` config sections; existing `orca` config is unchanged.
- feat(app): name each failed environment check when startup fails.
- Initial project bootstrap.
- fix(orca): build slice commands to the OrcaSlicer CLI contract (`--slice <plate>`, model as positional argument, values for `--orient`/`--arrange`/`--skip-modified-gcodes`, semicolon-separated `--load-settings`/`--load-filaments`).
- fix(orca): remove unsupported `--version` command.
- fix(orca): stop OrcaSlicer commands after a timeout (default 30 minutes) and log stderr when a command fails.
- fix(orca): run `--help` and `--export-settings` from a temporary directory so OrcaSlicer's `result.json` is not left in the working directory; make configured paths absolute.
- build: declare PyYAML runtime dependency and pytest dev dependency; configure pytest to find `src`.
