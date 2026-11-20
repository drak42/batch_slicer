# Changelog

## Unreleased

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
