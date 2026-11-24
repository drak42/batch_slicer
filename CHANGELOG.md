# Changelog

All notable changes to BatchSlicer are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.20.0] - 2026-11-24

The web page: upload, follow, download and send from a browser on this
computer.

### Added

- `batchslicer web` (first step of the web page, needs the new `web` extra:
  `pipx install --force "batchslicer[web]"`): runs a watch together with a
  page on <http://127.0.0.1:8765> that shows what is waiting, what is being
  sliced (model *n* of *m*), the drops finished, and the results in the
  output folder with their preview pictures, print time, filament per slot
  and the slicer's reason for failures. Drag models, zip files or folders
  onto the page (or choose them) to slice them, up to 2 GB at a time; they
  reach the watched folder only once complete. Download each G-code file and
  the reports, or a whole run as a ZIP. Send a run's G-code to a configured
  printer, into the same folders as `--send` (it is never started), and see
  on the Printers page whether each printer answers and what is loaded in
  its CFS. An About page shows the settings and runs `batchslicer doctor`.
  Folders watched by installed services are offered as upload targets, with
  what each service is doing. It works only on this computer, and takes
  uploads, sends and checks only from the page itself. `--port` chooses another port.
- `batchslicer service install --web` keeps the web page and its watch
  running in the background, as a service named `web` (`--port` for another
  port).
- A watch run keeps `.batchslicer-status.json` in the watched folder up to
  date with what it is doing, for the web page and your own scripts.

## [0.19.0] - 2026-11-24

The background service on every system, API keys from the environment, and a
quick printers-only check.

### Added

- `api_key_env: VARIABLE` in a printer's settings reads its API key from that
  environment variable, so the key need not be stored in the configuration
  file. A missing or empty variable, or setting both `api_key` and
  `api_key_env`, is explained; `batchslicer doctor` shows where each key
  came from, never the key (#18).
- `batchslicer doctor --printer NAME|ADDRESS` checks only that printer (a
  configured name, or any address, even without a configuration): whether it
  answers, which software answered, where its key came from and what is
  loaded in its CFS. Repeat it for several printers (#19).
- `batchslicer service` works on macOS: it installs a launchd agent that
  watches while you are signed in, starts at login, starts again after an
  error, and writes its output to `~/Library/Logs/BatchSlicer/service-NAME.log`.
  `status` and `uninstall` work as on Linux; stopping works like Ctrl+C.
- `batchslicer service` works on Windows: it registers a Task Scheduler task
  that starts when you sign in and runs in your session without a window (so
  Bambu Studio slices there), with its output in
  `%LOCALAPPDATA%\BatchSlicer\logs\service-NAME.log`. Stopping asks it to
  stop like Ctrl+C before ending it.

### Documentation

- The README and User Guide give Linux, Windows and macOS their own
  installation steps, and the README has one table per system for where
  BatchSlicer keeps its configuration, folders, logs and the slicers'
  settings, instead of mixing the three in the same paragraphs.

## [0.18.0] - 2026-11-24

macOS: BatchSlicer runs on macOS with OrcaSlicer, Creality Print and Bambu
Studio, tested on a real Mac (macOS 15.8).

### Added

- macOS support. Settings and profiles live in
  `~/Library/Application Support/BatchSlicer`, logs in
  `~/Library/Logs/BatchSlicer` and the cache in `~/Library/Caches/BatchSlicer`;
  models and results in `~/BatchSlicer` as on Linux.
- `batchslicer setup` finds `OrcaSlicer.app`, `BambuStudio.app` and
  `Creality Print.app` in `/Applications` and `~/Applications`, uses the
  program inside the app and reads its version from the app's `Info.plist`;
  the settings folders are found under `~/Library/Application Support`.
  Built-in presets are read from the app itself.
- The automated checks also run on macOS (Python 3.12 and 3.13).

### Fixed

- The watch folder's stop hint no longer mentions `systemctl` on macOS.

### Documentation

- Installing and using BatchSlicer on macOS, in the README (installation,
  where setup looks, folders, troubleshooting) and the User Guide; macOS
  locations in the architecture, startup sequence and example configuration.
- `batchslicer service` is Linux-only: on macOS, as on Windows, run `--watch`
  in a Terminal window. macOS's own `python3` (3.9) is too old; Terminal needs
  permission to read Desktop, Documents and Downloads.

## [0.17.0] - 2026-11-24

Windows: BatchSlicer runs on Windows 10 and 11 with OrcaSlicer, Creality
Print and Bambu Studio, tested on a real Windows 11 machine.

### Added

- Windows support. Settings and profiles live in `%APPDATA%\BatchSlicer`,
  logs and cache in `%LOCALAPPDATA%\BatchSlicer`, and models and results in
  `%USERPROFILE%\BatchSlicer` as on Linux.
- `batchslicer setup` finds slicers installed in Program Files or
  `%LOCALAPPDATA%\Programs`, and portable copies in Downloads, Desktop and the
  other usual folders; their settings folders are found under `%APPDATA%`.
  The version comes from Windows' list of installed programs.
- The automated checks also run on Windows (Python 3.12 and 3.13).

### Fixed

- Creality Print's hidden migration folders (`.7.3.staging-...`,
  `.migration-7.3`) are no longer mistaken for its settings folder. This
  could happen on Linux too, once Creality Print 7.3 had moved its settings.
- Slicer output is read as UTF-8 on every system, and paths in the
  configuration, reports and menus are written with `/`.
- A Windows path written with backslashes inside YAML double quotes gets a
  message saying how to write it, instead of a bare YAML error.

### Documentation

- Installing and using BatchSlicer on Windows, in the README (installation,
  where setup looks, folders, Windows paths in the configuration, running the
  watch folder, troubleshooting) and the User Guide; Windows locations in the
  architecture, startup sequence and example configuration.
- Known limits on Windows: `batchslicer service` is Linux-only (run `--watch`
  in a terminal window), and Bambu Studio slices only from a signed-in
  desktop session, not over SSH or as a background task.
- A short terminal demo (`docs/images/demo.gif`, recorded with
  `docs/demo/demo.sh`) in the README's "See it in action" and the User Guide.

## [0.16.1] - 2026-11-24

A zip file's name in messages, a demo script, and documentation brought up to date.

### Fixed

- A zip file's name is shown in progress and dry-run messages ("Slicing 3
  model files from boat-kit.zip"), not its temporary folder.

### Documentation

- `docs/demo/demo.sh` runs a short, repeatable demo for recording (a dry run,
  a multi-colour project matched to the CFS, a kit zip on one plate) in its
  own `~/demo` folder, without touching your configuration.
- The README's "How it works" and the startup sequence (`docs/Startup.md`)
  follow the real order of the steps (the output folder comes last, after
  sending and the multi-colour question) and cover zip files, `--dry-run` and
  stopping on a terminate request; the README's feature list includes zip
  files and `--dry-run`; the architecture, data model and coding standards
  mention the zip unpacking and the dry run.

## [0.16.0] - 2026-11-24

Zip files: slice a downloaded kit without unpacking it first.

### Added

- Zip files: `--input kit.zip` and zip files dropped into the watch folder
  are unpacked into a temporary folder and sliced like a folder (a kit
  downloaded from a model site no longer needs unpacking first). Only model
  files are taken out; folders every model shares are left out; archives with
  paths outside their folder or an unusual size are refused; a zip without
  models fails with the reason. `--last` remembers the zip.

### Documentation

- Confirmed on a Creality K2 Plus: a single-colour part sliced for one CFS
  spool (`--loaded-filaments --slot "*=1B"`) has that spool already selected
  on the printer's slot-mapping screen.

## [0.15.0] - 2026-11-23

A dry run, and a clean stop when BatchSlicer is asked to end.

### Added

- `--dry-run` shows what a run would do (each model or plate group, copies,
  `--slot` filaments, how multi-colour projects would be filled or matched to
  the CFS, models that would fail, where results would go and which printer
  they would be sent to) without slicing, writing or sending anything.

### Changed

- A request to terminate BatchSlicer (`kill`, `systemctl stop`) now stops it
  like Ctrl+C: slicers are stopped, partial results removed, and a watch run
  says "Stopped watching" instead of ending mid-run.

## [0.14.2] - 2026-11-23

Documentation: a Buy Me a Coffee link. The program is unchanged from 0.14.1.

### Documentation

- A Buy Me a Coffee link (https://buymeacoffee.com/drak42) in the README, the
  User Guide and the repository's Sponsor button (`.github/FUNDING.yml`).

## [0.14.1] - 2026-11-23

Documentation: a User Guide, a banner, and OctoPrint confirmed on a real
server. The program is unchanged from 0.14.0.

### Documentation

- A retro banner (G-code rain, a green-screen console, a part printing) at the
  top of the README and the User Guide; its source and generator are in
  `docs/images/`.
- A step-by-step User Guide (`docs/UserGuide.md`), linked from the README.
- The README's interactive walkthrough now follows the real order of the
  questions (the output folder comes last) and includes the multi-colour
  question; the Profiles section lists every saved setting; Troubleshooting
  covers the newer messages (Creality Print and 3MF projects, mixed filament
  temperatures, `--slot`, "Line width too small").
- Sending to OctoPrint is confirmed with a real server (OctoPrint 2.0.1):
  status, nested folders, names with spaces, replacing a file sent again, and
  `--start` printing a single file.

## [0.14.0] - 2026-11-23

Flat output, and the CFS in `doctor`.

### Added

- `--flat` puts all of a batch's G-code straight into its folder, and into one
  folder on the printer; a name used twice gets its folders in front
  (`kits-arm.gcode`). Profiles store it as `flat`.
- `batchslicer doctor` lists what is loaded in each Creality printer's CFS and
  external spool holder.

### Changed

- The roadmap moves the web interface to "Later".

## [0.13.0] - 2026-11-23

Colours for STL kits, and clearer Creality Print failures.

### Added

- `--slot PATTERN=SLOT` gives STL, OBJ and STEP models their own filament
  slot, so a kit prints in several colours (on one plate with `--plates`). A
  slot is a number (the `--filament` in that place) or, with
  `--loaded-filaments`, a loaded CFS slot such as `1B` or `external`.
  Profiles store it as `slots`.

### Fixed

- With Creality Print, a 3MF project saved by a slicer now fails at once with
  the reason (its command line cannot apply presets to projects) and a pointer
  to OrcaSlicer or Bambu Studio, instead of "Invalid parameters to the slicer"
  after starting Creality Print. Other models in the folder slice as usual.

## [0.12.1] - 2026-11-23

Small fixes, and CFS matching confirmed on a real printer.

### Fixed

- Bambu Studio's multi-colour G-code now shows its number of filament
  changes too (counted from the tool changes, as Bambu Studio does not write
  it).
- A watch run without a terminal (a `batchslicer service`) no longer says
  "Press Ctrl+C to stop"; it says how to stop the service instead.

### Documentation

- Matching to the CFS is confirmed on a Creality K2 Plus: the touchscreen's
  slot-mapping screen picks the matched slots by itself.

## [0.12.0] - 2026-11-23

Multi-colour projects, with filaments matched to the Creality CFS.

### Added

- Multi-colour 3MF projects: the slicer is given a filament for every slot
  the project lists (before, such projects failed or kept the project's own
  filaments for the extra slots).
- `--filament` can be repeated, one per slot; in a profile `filament` takes a
  list.
- `--loaded-filaments` matches each colour of a multi-colour project to the
  filament loaded in the `--send` printer's Creality CFS (or external spool)
  that looks most like it, slicing it with a preset of that material in the
  loaded colour. Interactive runs ask which way to fill the slots.
- Preview pictures show each filament in its own colour.
- The summary and report give the grams of each filament and the number of
  filament changes (`filament_g_each`, `filament_changes`).

### Changed

- `--start` does not start a multi-colour print; it is sent, to be started on
  the printer's screen where the CFS slots can be checked.

## [0.11.0] - 2026-11-23

The watch folder runs in the background.

### Added

- `batchslicer service install` runs the watch folder in the background as a
  systemd user service, with the same options as a watch run; `status` shows
  what each service is doing and `uninstall` removes one. Stopping a service
  works like Ctrl+C. `--name` runs several.

### Changed

- GitHub Actions updated (checkout, setup-python, upload/download-artifact and
  the PyPI upload action); no change to the program.

## [0.10.0] - 2026-11-23

A watch folder, and sending to OctoPrint.

### Added

- Watch folder: `--watch` keeps running and slices each model file or folder
  put in the input folder (or the incoming folder) once it has finished
  copying, then moves it to the folder's `sliced` or `failed` subfolder.
  Works with profiles, `--plates`, `--copies` (single models) and `--send`;
  never with `--start`. Stop with Ctrl+C.

- `--send` can upload to OctoPrint: name the printer in the configuration
  with `type: octoprint`, its address and an API key. Folders are created as
  needed, `--start` selects and prints a single file when the printer is
  ready, and `batchslicer doctor` checks it. Tested against a stand-in
  OctoPrint; not yet with a real server.

### Changed

- `batchslicer doctor` shows a Klipper printer as "Klipper is ready" and leaves
  out Moonraker's version when the printer reports none (the Creality K2 Plus
  reports "?").

## [0.9.3] - 2026-11-22

The repository is public. The program is unchanged from 0.9.2.

### Added

- The repository is public: README badges, issue forms for bug reports
  (asking for `batchslicer doctor` output) and feature requests, and
  `SECURITY.md` with private vulnerability reporting.
- Dependabot proposes weekly updates for the GitHub Actions and Python
  packages BatchSlicer uses; `main` is protected, so those (and any pull
  request) must pass CI on Python 3.12 and 3.13 before they can be merged.

## [0.9.2] - 2026-11-22

The first release on PyPI.

### Added

- **Published on PyPI.** `pipx install batchslicer` installs it; each tagged
  release is uploaded automatically through trusted publishing.

## [0.9.1] - 2026-11-22

One failing part no longer splits a folder's plates.

### Changed

- **One failing part no longer splits a folder's plates.** With `--plates`,
  when a folder's parts cannot be sliced together, each is sliced on its own
  to find the failing ones, and the rest are put back together on plates
  (before, every part of the folder got its own plate). Parts that only slice
  after an auto-orient retry keep their own plate. Tested with OrcaSlicer 2.5.2.

## [0.9.0] - 2026-11-22

Copies of a part, arranged by the slicer.

### Added

- **Copies of a single model.** `--copies N` slices N copies of one STL, OBJ
  or STEP model; the slicer arranges them, adding plates when they don't fit
  (one G-code file per plate). Interactive single-model runs ask "How many
  copies?" (Enter for 1), profiles can save the number, and the summary and
  report show it. Not for folders (see `--plates`), 3MF projects or Creality
  Print. Tested with OrcaSlicer 2.5.2.

## [0.8.0] - 2026-11-22

Kits on plates, and sending to the printer from interactive runs.

### Added

- **Several models per plate.** When slicing a folder, the loose models (STL,
  OBJ, STEP) of each folder can be sliced together: the slicer arranges them
  on as few plates as fit, giving one G-code file per plate, named after the
  folder. Interactive runs ask ("Put the models in each folder together on
  plates?"); `--plates` / `--no-plates` decide on the command line, and
  profiles can save it. If a part fails, the folder's models are sliced one
  by one instead. 3MF projects keep their own plates. OrcaSlicer and Bambu
  Studio (Creality Print cannot arrange from its command line). The report
  lists each plate group's models. Tested with OrcaSlicer 2.5.2 and Bambu
  Studio 2.9.1.
- **Interactive runs ask whether to send the G-code** to a printer, when one
  is configured or the last run sent to one ("Enter keeps what the last run
  did"; another address can be typed). Runs from a profile or with `--send` /
  `--no-send` are not asked, and people who never send are never asked.

## [0.7.1] - 2026-11-22

Preview pictures on the printer's screen, checked with a real K2 Plus.

### Added

- **Preview pictures in the G-code.** Printer screens (such as the K2 Plus
  touchscreen) now show a picture of each file. Slicers draw these only in
  their windows, so BatchSlicer draws them from the G-code's toolpaths: the
  part as it will print, shaded, in the filament's colour, at the sizes the
  printer preset asks for (usually 300x300 and 96x96 PNG). About a second per
  typical model; `--no-thumbnails` turns it off, and profiles can save it.
  Checked on the Creality K2 Plus touchscreen.

### Changed

- The README notes how sending works with the Creality K2 Plus (tested: ports
  7125 and 4408, no API key, folders shown on the touchscreen).

## [0.7.0] - 2026-11-22

Leave unwanted files out of a batch, and send the results to the printer.

### Added

- **`--exclude PATTERN`** leaves out folders or files when slicing a folder
  (repeatable; `Cura-*` matches a name at any depth, `kits/old` a path; case is
  ignored). BatchSlicer says how many it skipped, and profiles save the
  patterns. In the soak test, `--exclude "Cura-*"` would have left out the 241
  printer-bed meshes behind 99 of the 216 failures.
- **Sending G-code to a printer.** `--send PRINTER` uploads the G-code of every
  model that sliced to a Klipper printer through Moonraker (Creality K1/K2,
  Voron and others), keeping a batch's folder structure on the printer.
  `--start` starts printing a single model. The printer is given by its
  address (`--send 192.168.1.50`, port 7125 unless another is given) or by a
  name from the new `printers` section of the configuration. Printers are
  checked before slicing starts,
  and are checked by `batchslicer doctor`. Profiles remember the printer
  (`--no-send` skips it for one run) but never `--start`. `batchslicer setup`
  keeps the `printers` section when it rewrites the configuration. Tested
  with real slicing against a stand-in Moonraker; not yet with a real printer.

### Changed

- The `--orient retry` hint also appears for OrcaSlicer 2.5's "empty first
  layer" failures, and a failure's reason is no longer repeated when the
  slicer's log only restates it.

## [0.6.0] - 2026-11-22

Every supported slicer has preset selection, and the newest OrcaSlicer works.

### Added

- **Bambu Studio preset selection.** Choose a printer, then a compatible
  filament and process, as for the other slicers. Bambu Studio records the
  printer models you added and their nozzle sizes, so BatchSlicer lists the
  shipped printers for those, plus printers you created yourself. Tested with
  Bambu Studio 2.9.1.
- The weekly "Latest slicers" job now also slices with Bambu Studio's presets.
- **OrcaSlicer 2.5 support.** OrcaSlicer 2.5 ships its built-in presets only as
  packed `.opc` files; BatchSlicer now reads that format (following
  OrcaSlicer's own source) and unpacks the presets it needs. Vendors that
  OrcaSlicer 2.5 does not ship (it downloads them) are read from the `.opc`
  files in its settings folder. Checked against 2.4.0 and 2.5.2: the presets
  decode completely, and slicing the same model gives the same settings apart
  from those 2.5 itself changed.

### Fixed

- With OrcaSlicer 2.5, slicing for a printer you created yourself failed
  ("can not resolve preset"), because 2.5 looks up the printer it is based on
  itself. BatchSlicer now leaves that link out for 2.5 and later.
- `config/config.yaml.bak` (written by `batchslicer setup`) is no longer offered
  for committing.

## [0.5.0] - 2026-11-22

Large batches: found by slicing 1,719 real downloaded models.

### Added

- **`--orient retry|always`** uses the slicer's auto-orient. `retry` slices a
  model that fails once more with auto-orient; this fixed 97 of 115 "Failed
  slicing the model" errors in the test. `always` auto-orients every model.
  Models sliced this way are marked "auto-oriented". Not available for Creality
  Print, whose command line has no auto-orient.
- **`--allow-newer-files`** lets the slicer open `.3mf` projects saved by a
  newer slicer version (6 of 9 such projects then sliced).
- **`--jobs N`** slices N models at the same time; progress is shown as each
  finishes. Ctrl+C stops every running slicer. The slicers are already
  multi-threaded, so the gain varies: on a 4-core computer two jobs were 12%
  faster and four were no faster.
- **Batch report**: every run writes `report.csv` and `report.json` with each
  model's status, G-code, print time, filament weight, length and cost, and
  failure reason. A batch's report is updated as it runs. The summary shows
  total print time and filament.
- Hints after failures that `--orient retry` or `--allow-newer-files` may fix.
- The three new options can be saved in profiles.

### Changed

- Result folders hold only G-code and presets: the slicer's `result.json` and
  `NNNNN.log` are read and then removed, folders of failed models are removed,
  and a model interrupted by Ctrl+C leaves no partial files.
- A batch's time is the time it took from start to finish, shown as minutes
  and hours when long.
- Slicer processes are started and stopped by BatchSlicer itself, so Ctrl+C
  always stops them.

## [0.4.0] - 2026-11-20

Dependable in everyday use: a setup check, tidy logs, and weekly testing
against the newest slicers.

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

[Unreleased]: https://github.com/drak42/batch_slicer/compare/v0.20.0...HEAD
[0.20.0]: https://github.com/drak42/batch_slicer/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/drak42/batch_slicer/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/drak42/batch_slicer/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/drak42/batch_slicer/compare/v0.16.1...v0.17.0
[0.16.1]: https://github.com/drak42/batch_slicer/compare/v0.16.0...v0.16.1
[0.16.0]: https://github.com/drak42/batch_slicer/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/drak42/batch_slicer/compare/v0.14.2...v0.15.0
[0.14.2]: https://github.com/drak42/batch_slicer/compare/v0.14.1...v0.14.2
[0.14.1]: https://github.com/drak42/batch_slicer/compare/v0.14.0...v0.14.1
[0.14.0]: https://github.com/drak42/batch_slicer/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/drak42/batch_slicer/compare/v0.12.1...v0.13.0
[0.12.1]: https://github.com/drak42/batch_slicer/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/drak42/batch_slicer/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/drak42/batch_slicer/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/drak42/batch_slicer/compare/v0.9.3...v0.10.0
[0.9.3]: https://github.com/drak42/batch_slicer/compare/v0.9.2...v0.9.3
[0.9.2]: https://github.com/drak42/batch_slicer/compare/v0.9.1...v0.9.2
[0.9.1]: https://github.com/drak42/batch_slicer/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/drak42/batch_slicer/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/drak42/batch_slicer/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/drak42/batch_slicer/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/drak42/batch_slicer/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/drak42/batch_slicer/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/drak42/batch_slicer/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/drak42/batch_slicer/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/drak42/batch_slicer/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/drak42/batch_slicer/compare/v0.1.0-bootstrap...v0.2.0
[0.1.0]: https://github.com/drak42/batch_slicer/releases/tag/v0.1.0-bootstrap
