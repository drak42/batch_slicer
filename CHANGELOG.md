# Changelog

## Unreleased

- feat(backends): support Creality Print and Bambu Studio alongside OrcaSlicer; the user is prompted to choose a configured slicer at startup before the application proceeds. New `creality_print` and `bambu_studio` config sections; existing `orca` config is unchanged.
- feat(app): name each failed environment check when startup fails.
- Initial project bootstrap.
- fix(orca): build slice commands to the OrcaSlicer CLI contract (`--slice <plate>`, model as positional argument, values for `--orient`/`--arrange`/`--skip-modified-gcodes`, semicolon-separated `--load-settings`/`--load-filaments`).
- fix(orca): remove unsupported `--version` command.
- fix(orca): stop OrcaSlicer commands after a timeout (default 30 minutes) and log stderr when a command fails.
- fix(orca): run `--help` and `--export-settings` from a temporary directory so OrcaSlicer's `result.json` is not left in the working directory; make configured paths absolute.
- build: declare PyYAML runtime dependency and pytest dev dependency; configure pytest to find `src`.
