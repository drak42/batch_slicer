# Security

## Reporting a problem

Please report security problems privately through GitHub:
[Report a vulnerability](https://github.com/drak42/batch_slicer/security/advisories/new)
(the **Security** tab of the repository). Don't open a public issue for them.

Include what you found, how to reproduce it, and which version of BatchSlicer
(`batchslicer --version`) it affects. You'll get a reply as soon as possible,
and a fix is released as a new version on PyPI and GitHub.

## Supported versions

Only the latest release receives fixes. Upgrade with `pipx upgrade batchslicer`.

## What BatchSlicer touches

Useful context when judging a problem:

- It runs the slicer programs named in your configuration, with your presets.
- It reads the slicers' settings folders but never writes to them.
- It writes only to its own folders (output, logs, cache, profiles).
- With `--send`, it uploads G-code to the printer address you give, through
  Moonraker's HTTP API, and with `--start` asks the printer to print it. An
  `api_key` in the configuration is sent only to that printer.
