# BatchSlicer Architecture

**Version:** 0.21.1  
**Status:** Current; parts marked *planned* are not built yet  
**Last Updated:** November 2026

---

# 1. Purpose

This document describes the architectural design of BatchSlicer.

It explains how the application is structured, how components communicate, and the engineering principles that guide every design decision.

This document is intentionally technology-agnostic wherever possible. It focuses on responsibilities rather than implementation.

The architecture is expected to evolve over time, however the core design principles should remain stable throughout the lifetime of the project.

---

# 2. Vision

BatchSlicer exists to remove friction from the entire 3D printing workflow through reliable, maintainable, and thoughtfully engineered automation.

The project began as a batch slicing tool for OrcaSlicer. It now drives OrcaSlicer, Creality Print and Bambu Studio, and is growing into a print automation platform.

The long-term goal is to automate repetitive printing tasks while remaining understandable, extensible, and dependable.

Every feature must provide measurable value.

---

# 3. Core Philosophy

The following principles guide every engineering decision.

## Build for today. Design for tomorrow.

Only implement functionality that provides immediate value.

Design systems so they can grow without requiring large-scale rewrites.

---

## Simplicity over cleverness.

Readable code is preferred over complex or highly optimised code.

Future maintainability is valued more highly than short-term convenience.

---

## One responsibility.

Every module should have one clearly defined purpose.

If a module cannot describe its purpose in one sentence, it is probably doing too much.

---

## Explicit over implicit.

Configuration should never be hidden.

Dependencies should always be visible.

Application behaviour should always be understandable.

---

## Testability is a design requirement.

Software should be designed so it can be tested.

Testing is not an afterthought.

---

## Documentation is part of the implementation.

A feature is not complete until it is documented.

Documentation should explain **why** the software behaves as it does, not simply **what** it does.

---

# 4. High-Level Architecture

BatchSlicer follows a layered architecture. As built today:

```
                        User
                          │
                    CLI (cli/)                    Web page (web/, see WebPlan.md)
                          │
              Application (app.py: one run, start to finish)
                          │
        ┌─────────────────┼──────────────────┐
        │                 │                  │
  Core (core/)      Services (services/)   Infrastructure (infrastructure/)
  configuration,    slicing, reports,      saved profiles,
  logging,          G-code statistics,     Moonraker, OctoPrint
                    sending
  environment checks      │
                          │
                  Backends (backends/)
     one CLI backend for OrcaSlicer, Creality Print and Bambu Studio;
     preset reading, .opc unpacking, installation detection
```

Planned layers not built yet: a service registry, a database and history, an
event system, a job queue and plugins. The web page's first release is built
(0.20.0); what comes next for it is planned in [WebPlan](WebPlan.md).

Each layer has clearly defined responsibilities.

Communication should flow downwards.

Lower layers should never depend on higher layers.

---

# 5. Application Lifecycle

A run follows a deterministic sequence: options, configuration, logging,
profiles, then for each target the slicer, environment check and presets,
then input, output and slicing. [Startup](Startup.md) describes each step and
where its code lives.

Every stage must complete successfully before the next begins.

Each selection stage takes its value from the command line or a profile when
given (`cli/arguments.py`) and otherwise prompts, unless `--no-prompt` is used.

Startup failures should clearly identify the failing stage.

---

# 6. Project Structure

```
src/
└── batchslicer/
    ├── app.py             # one run, start to finish (see Startup.md)
    ├── core/              # configuration, locations, logging, environment checks
    ├── cli/               # arguments, prompts, setup and doctor commands
    ├── domain/            # plain value objects: presets, profiles, slicing options
    ├── services/          # slicing jobs and batches, reports, G-code statistics, sending
    ├── backends/          # slicer CLI, presets, .opc reader, detection
    ├── infrastructure/    # saved profiles (YAML), printer clients
    ├── application/       # reserved (planned)
    ├── plugins/           # reserved (planned)
    └── web/               # the web page (Starlette app, templates, static files; see WebPlan.md)
```

Each package has a single responsibility. [Modules](Modules.md) lists every
module.

---

## application

Coordinates application startup.

Contains no business logic.

Today this role is filled by `app.py`; the package is reserved for when
startup grows (for example a service registry).

---

## services

Implements reusable application services.

Built: slicing one model or a batch (`services/slicing.py`), the run report
(`services/report.py`), G-code statistics (`services/gcode_stats.py`),
preview pictures drawn from the G-code (`services/thumbnails.py`) and sending
G-code to printers (`services/sending.py`), watching a folder for models
to slice (`services/watching.py`), matching multi-colour projects to the
filaments loaded in a printer (`services/filament_matching.py`) and unpacking
zip files safely (`services/archives.py`). A dry run (`--dry-run`) goes
through the same planning (`plan_work` in `services/slicing.py`) and stops
before slicing.
Configuration and logging live in `core/`.

Planned: queue, database, history.

---

## domain

Contains pure business objects.

Built: `Preset`, `PresetSelection`, `Target`, `Profile`, `SliceOptions` (see
[Data model](DataModel.md)). Planned: Job, Printer.

Domain objects should never know about Flask, SQLite or OrcaSlicer.

---

## backends

Interfaces with slicing software.

Supported (all share the OrcaSlicer command-line interface, driven by one backend):

- OrcaSlicer
- Creality Print (run with `--cli`; no `--orient`, `--arrange`, `--skip-modified-gcodes` or `--export-settings`)
- Bambu Studio

Each slicer has its own configuration section (`orca`, `creality_print`, `bambu_studio`)
with `executable` and `datadir`. The user chooses one at startup.

Presets are read from the slicer's data directory (`backends/presets.py`). Saved
presets only store differences from the preset they inherit from, and the slicer
CLI cannot load them as saved, so the chosen presets are written out as complete,
self-contained files for `--load-settings` / `--load-filaments`. The slicer's data
directory is never modified. Creality Print also needs `--need-gcode-file`, without
which it reports success but writes no G-code.

Preset selection is supported for all three slicers. Shipped
filaments are limited to those the user made visible in the slicer, as in its
own menus. Creality Print keeps shipped presets as JSON in its data directory.
OrcaSlicer 2.4 and later pack them into `.opc` files. The vendors in use are
taken from the program (JSON in 2.4; `.opc` files in 2.5, read by
`backends/opc.py` following OrcaSlicer's `PresetCacheFormat.cpp`) or, for
vendors the program does not ship, from the settings folder's `.opc` files,
and unpacked once as JSON into `data/slicer-profiles/` until the slicer or
those files change (`backends/profiles.py`). From OrcaSlicer 2.5 the CLI looks
up a settings file's `inherits` itself, so a user's printer is written without
that link for 2.5 and later (the version comes from `--help`). Bambu Studio
keeps shipped presets as JSON in its data directory and records added printers
as models and nozzle sizes (`models` in `BambuStudio.conf`), which are mapped
to the shipped printers with that `printer_model` and `printer_variant`.

Future:

- PrusaSlicer
- Cura

Slicer processes are started and stopped by the backend itself, so several can
run at once (`--jobs`) and Ctrl+C stops all of them.

---

## plugins

Optional extensions (planned).

Plugins communicate through published interfaces only.

---

## cli

Command-line interface.

Responsible only for user interaction.

---

## web

A web page served by Starlette (`batchslicer web`; see [WebPlan](WebPlan.md)).
It shows the watch folder's queue and the results, read from the watched
folder's status file and the output folder's reports and G-code; uploads go
into the watched folder (`services/uploads.py`) and downloads come only from
the output folder. The printers page and sending use the same printer
clients and sending service as `--send`. It never slices (the watch run does)
and never starts a print. Installed watch services' folders are further
upload targets, found through `cli/service.py` when the page starts; the
About page runs `cli/doctor.py`.

Responsible only for presentation. It needs the optional `web` extra, and
only `cli/web.py` starts it, so the command line works without it.

---

## infrastructure

External integrations.

Built: the saved-profiles store (`infrastructure/profiles.py`) and the
Moonraker and OctoPrint clients that send G-code to printers
(`infrastructure/moonraker.py`, `infrastructure/octoprint.py`, sharing
`infrastructure/printer_api.py`; standard library only). Planned: SQLite,
other external storage, and other printer connections (Bambu LAN). (Slicer processes are run by the backends.)

---

# 7. Service Registry

*Planned.* Today `app.py` creates the configuration, logging, profile store,
backends and slicing services once per run and passes them on explicitly;
modules do not create their own. A registry would formalise this.

Application services are created once during startup.

Modules request services from the registry rather than creating them directly.

Benefits include:

- loose coupling
- easier testing
- centralised configuration
- future dependency injection

---

# 8. Data Flow

Typical slicing workflow, as built:

```
User
  ↓
CLI: options, profiles and prompts choose slicer, presets, input, output
  ↓
Application (app.py)
  ↓
Preset library: resolves the chosen presets into complete files
  ↓
Slicing service: job or batch folders, up to --jobs at a time, retries,
  each folder's models together on plates (--plates)
  ↓
Backend: slicer CLI (OrcaSlicer, Creality Print or Bambu Studio)
  ↓
G-code, named after each model (or folder), with preview pictures added
  ↓
Report (report.csv / report.json) and summary
  ↓
Sending service (--send): G-code to the printer through Moonraker or OctoPrint
```

Planned: a queue before slicing, and a database and history after it.

The flow should remain easy to follow.

---

# 9. Configuration

Configuration is loaded once during startup.

The configuration file is found by `core/config.py` in this order: `--config`,
the `BATCHSLICER_CONFIG` environment variable, `config/config.yaml` in the
current folder (a project checkout), then `~/.config/batchslicer/config.yaml`
(`%APPDATA%\BatchSlicer\config.yaml` on Windows,
`~/Library/Application Support/BatchSlicer/config.yaml` on macOS).
All path settings are read through `Config.get_path()` / `get_program()`:
`~` is expanded, relative paths are relative to the configuration file, and
missing `paths` settings use standard per-user locations (`core/locations.py`):
models and results in `~/BatchSlicer`; on Linux, following the XDG conventions,
logs in `~/.local/state/batchslicer` and caches in `~/.cache/batchslicer`; on
Windows, settings and profiles in `%APPDATA%\BatchSlicer` and logs and caches
in `%LOCALAPPDATA%\BatchSlicer`; on macOS, settings and profiles in
`~/Library/Application Support/BatchSlicer`, logs in `~/Library/Logs/BatchSlicer`
and caches in `~/Library/Caches/BatchSlicer`. BatchSlicer therefore behaves the
same from any working folder.

`core/locations.is_windows()` and `is_macos()` are the one place that decides
which system's conventions apply; modules call it through the `locations` module so tests can
switch the layout.

`batchslicer setup` (`cli/setup.py`) creates the configuration: it detects
installed slicers and their settings folders (`backends/detection.py`) and
writes the file (`render_config`), keeping a backup of any file it replaces.
On Windows, detection searches Program Files and `%LOCALAPPDATA%\Programs` and
reads versions from Windows' list of installed programs; because the slicers
are window programs there, their help text never reaches BatchSlicer, so the
backend falls back to that detected version (`detection.program_version`).
On macOS, detection looks for the slicer apps in `/Applications` and
`~/Applications`, takes the program inside the app and its version from
`Info.plist`; the slicers there print their help text as on Linux.
`batchslicer service` (`cli/service.py`) installs a background service that
runs a watch run with the configuration file named explicitly. It talks to the
system's service manager through one interface
(`infrastructure/service_manager.py`): systemd user units on Linux
(`infrastructure/systemd.py`), launchd agents on macOS
(`infrastructure/launchd.py`, with the output in a log file) and Task
Scheduler tasks on Windows (`infrastructure/windows_tasks.py`). On Windows the
task runs `pythonw.exe` (no window) with `cli/service_host.py`, which sends the
output to a log file and turns a stop-request file into Ctrl+C, because Task
Scheduler's own stop ends the process outright.

No module should read configuration files directly.

Configuration changes should be visible and traceable.

---

# 10. Logging

All logging passes through the logging service.

Modules must never use print() for diagnostic output.

Logging should answer three questions:

- What happened?
- When did it happen?
- Why did it happen?

---

# 11. Error Handling

Errors should:

- be explicit
- provide useful messages
- preserve context
- be logged

Unexpected exceptions should never terminate silently.

---

# 12. Future Expansion

The architecture should support future capabilities without major redesign.

Examples include:

- Multiple printers (built: several printers per run)
- Multiple slicers (built: OrcaSlicer, Creality Print, Bambu Studio)
- Sending to printers (built: Klipper/Moonraker, OctoPrint; planned: Bambu LAN)
- Arranging parts onto plates (built: `--plates` and `--copies`, by the slicer's own arrange)
- Distributed workers
- Remote dashboard
- REST API
- Authentication
- Cloud storage
- Plugin marketplace

---

# 13. Design Rules

The following rules are considered mandatory.

- No global state.
- No "utils.py".
- No duplicated configuration.
- No circular imports.
- No hidden dependencies.
- No business logic inside the UI.
- No filesystem access outside infrastructure.
- No feature without documented purpose.

---

# 14. Definition of Done

A feature is complete only when:

- Implementation complete
- Unit tests pass
- Documentation updated
- Logging added where appropriate
- Reviewed
- Merged

---

# 15. Engineering Motto

> Build for today. Design for tomorrow.

> Every feature must earn its place.

> Reliability is a feature.

---

# 16. Product Development Philosophy

- We solve real problems, not hypothetical ones.
- We favour steady, incremental improvement over rapid feature growth.
- Every significant architectural decision is documented.
- We challenge ideas, not people.
- We build software that we would enjoy maintaining ourselves.

---

# 17. Engineering Culture

This project is developed collaboratively.

The Product Owner defines the problems to solve.

The Software Architect defines the technical direction.

AI coding agents assist implementation.

Architecture is discussed before implementation.

Question assumptions.

Prefer long-term maintainability over short-term convenience.

Every feature must earn its place.