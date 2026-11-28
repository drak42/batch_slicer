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
| `core/locations.py` | standard per-user folders (XDG on Linux, AppData on Windows, `~/Library` on macOS), and which system is running |
| `core/logging.py` | the rotating log file |
| `core/environment.py` | start-up checks of Python, configuration, folders and the chosen slicer |

## cli

| Module | Purpose |
|---|---|
| `cli/arguments.py` | parse command-line options for runs, `setup`, `doctor`, `service` and `web` |
| `cli/menu.py` | numbered menus with search, yes/no questions and number questions |
| `cli/slicer_prompt.py` | choose a slicer |
| `cli/preset_prompt.py` | choose printer, filament and process; find presets by name |
| `cli/profile_prompt.py` | offer saved profiles |
| `cli/file_prompt.py` | choose a model file or a folder of models; apply `--exclude` patterns |
| `cli/output_prompt.py` | choose or create the output folder |
| `cli/send_prompt.py` | ask whether to send the G-code to a printer, and to which |
| `cli/setup.py` | `batchslicer setup`: detect slicers, write the configuration |
| `cli/doctor.py` | `batchslicer doctor`: check the setup and report problems (or, with `--printer`, only the printers named) |
| `cli/service_host.py` | Windows: run BatchSlicer for a background task, with its output in a log file, stopping like Ctrl+C when asked |
| `cli/service.py` | `batchslicer service`: install, show and remove watch-folder services (or, with `--web`, the web page with its watch), with this system's service manager; tell the web page which folders services watch |
| `cli/web.py` | `batchslicer web`: serve the web page on this computer in a background thread while a watch run keeps the terminal |

## domain

| Module | Purpose |
|---|---|
| `domain/presets.py` | `Preset`, `PresetKind`, `PresetSelection` |
| `domain/profiles.py` | `Target`, `Profile`, combining profiles, valid names |
| `domain/options.py` | `SliceOptions`, orient modes, the `--jobs` limit |
| `domain/patterns.py` | match model paths against typed patterns (`--exclude`, `--slot`) |
| `domain/colours.py` | name `#RRGGBB` colours ("dark blue") and measure how alike two colours look |
| `domain/filaments.py` | `ProjectFilament`, `LoadedFilament`, and matching a project's slots to the loaded filaments |
| `domain/printers.py` | `PrinterHost`: printers for `--send`, read and checked from the `printers` section |

## services

| Module | Purpose |
|---|---|
| `services/slicing.py` | slice one model or a batch into job folders (parallel jobs, auto-orient retry, models together on plates, copies, clean-up) |
| `services/report.py` | write `report.csv` and `report.json` |
| `services/print_settings.py` | write `print-settings.txt`: the printer, filament and process presets of a result folder, their main settings and what the user's own presets change |
| `services/gcode_stats.py` | read print time and filament use from G-code |
| `services/thumbnails.py` | draw preview pictures from G-code toolpaths and insert them as PNG blocks; read them back |
| `services/filament_matching.py` | match multi-colour projects to the filaments loaded in the printer (`--loaded-filaments`) and write their filament files |
| `services/sending.py` | plan where each G-code file goes on the printer, for a run or a finished run in the output folder, and send them (`--send`, `--start`, the web page) |
| `services/archives.py` | unpack the models of a zip file (`--input kit.zip`, zip drops) safely: model files only, no paths outside the folder, size limits |
| `services/watching.py` | watch a folder (`--watch`): find drops that have finished copying and move them to `sliced` or `failed` once handled |
| `services/watch_status.py` | write and read `.batchslicer-status.json`: what a watch run is doing, for the web page |
| `services/results.py` | find the runs in the output folder, newest first, and read their reports; keep paths inside it; pack a run's G-code, reports and `print-settings.txt` into a ZIP |
| `services/uploads.py` | put uploaded files into the watched folder all at once, through a hidden staging folder: clean names, keep only what the watcher slices, limit sizes |

## backends

| Module | Purpose |
|---|---|
| `backends/slicers.py` | the supported slicers and how their command lines differ |
| `backends/orca.py` | build and run slicer commands (all three slicers share this CLI) |
| `backends/presets.py` | list compatible presets and resolve them into complete files |
| `backends/projects.py` | read the filament slots a 3MF project lists |
| `backends/profiles.py` | locate built-in presets, extracting or unpacking them into the cache |
| `backends/opc.py` | read OrcaSlicer's packed `.opc` preset files |
| `backends/detection.py` | find installed slicers and their settings folders (AppImages and PATH on Linux, Program Files on Windows, `.app` bundles on macOS) and their versions |
| `backends/backend.py` | the minimal `Backend` protocol (`run(command)`) |

## infrastructure

| Module | Purpose |
|---|---|
| `infrastructure/profiles.py` | read and write `profiles.yaml` atomically |
| `infrastructure/printer_api.py` | what every printer connection offers (`PrinterClient`, `PrinterStatus`, `UploadResult`, `PrinterError`) and the streamed multipart upload they share |
| `infrastructure/moonraker.py` | talk to a Klipper printer's Moonraker: check it answers, upload (and start) G-code |
| `infrastructure/octoprint.py` | talk to OctoPrint: check it answers and the printer's state, create folders, upload (and start) G-code |
| `infrastructure/printer_clients.py` | choose the Moonraker or OctoPrint client for a printer by its `type` |
| `infrastructure/service_manager.py` | what `batchslicer service` needs from a system's service manager (an interface), service names and errors |
| `infrastructure/systemd.py` | Linux: write, list and remove systemd user units for `batchslicer service`, and run `systemctl`/`journalctl` |
| `infrastructure/launchd.py` | macOS: write, list and remove launchd agents for `batchslicer service`, and run `launchctl` |
| `infrastructure/windows_tasks.py` | Windows: register, list and remove Task Scheduler tasks for `batchslicer service`, with `schtasks` and PowerShell |

## web

Needs the `web` extra (Starlette, Uvicorn, Jinja2); nothing else imports it.

| Module | Purpose |
|---|---|
| `web/app.py` | the Starlette application: queue, results, preview pictures, uploads (also into services' folders), downloads, the printers and their CFS, sending, and the About page with `doctor`; answers only to `localhost` and `127.0.0.1`, and takes uploads, sends and checks only with the page's token from the page itself |
| `web/templates/` | the pages (Jinja2) |
| `web/static/` | the stylesheet, `upload.js` (dragging and choosing files and folders) and htmx (shipped, never downloaded) |

## Reserved

`application/`, `plugins/` and `cli/commands/` are empty packages kept
for planned work (see [Architecture](Architecture.md)).
