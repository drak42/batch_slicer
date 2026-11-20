# Changelog

## Unreleased

- Initial project bootstrap.
- fix(orca): build slice commands to the OrcaSlicer CLI contract (`--slice <plate>`, model as positional argument, values for `--orient`/`--arrange`/`--skip-modified-gcodes`, semicolon-separated `--load-settings`/`--load-filaments`).
- fix(orca): remove unsupported `--version` command.
- fix(orca): stop OrcaSlicer commands after a timeout (default 30 minutes) and log stderr when a command fails.
- build: declare PyYAML runtime dependency and pytest dev dependency; configure pytest to find `src`.
