# BatchSlicer Architecture

**Version:** 0.1.0-alpha  
**Status:** Draft  
**Last Updated:** August 2026

---

# 1. Purpose

This document describes the architectural design of BatchSlicer.

It explains how the application is structured, how components communicate, and the engineering principles that guide every design decision.

This document is intentionally technology-agnostic wherever possible. It focuses on responsibilities rather than implementation.

The architecture is expected to evolve over time, however the core design principles should remain stable throughout the lifetime of the project.

---

# 2. Vision

BatchSlicer exists to remove friction from the entire 3D printing workflow through reliable, maintainable, and thoughtfully engineered automation.

The project began as a batch slicing tool for OrcaSlicer but has evolved into a print automation platform.

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

BatchSlicer follows a layered architecture.

```
                        User

                          │

                    CLI / Dashboard

                          │

                    Application

                          │

                  Service Registry

     ┌──────────┬──────────┬──────────┐

     │          │          │          │

 Configuration Logging Database Events

                          │

                  Backend Manager

                          │

          ┌───────────────┴───────────────┐

          │                               │

      Orca Backend                Future Backends
```

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
    ├── application/
    ├── services/
    ├── domain/
    ├── backends/
    ├── plugins/
    ├── cli/
    ├── web/
    └── infrastructure/
```

Each package has a single responsibility.

---

## application

Coordinates application startup.

Contains no business logic.

---

## services

Implements reusable application services.

Examples:

- Configuration
- Logging
- Queue
- Database
- History

---

## domain

Contains pure business objects.

Examples:

- Job
- Printer
- Preset
- Filament

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

Preset selection is supported for Creality Print and OrcaSlicer. Shipped
filaments are limited to those the user made visible in the slicer, as in its
own menus. Creality Print keeps shipped presets as JSON in its data directory.
OrcaSlicer 2.4 and later pack them into `.opc` files. The vendors in use are
taken from the program (JSON in 2.4; `.opc` files in 2.5, read by
`backends/opc.py` following OrcaSlicer's `PresetCacheFormat.cpp`) or, for
vendors the program does not ship, from the settings folder's `.opc` files,
and unpacked once as JSON into `data/slicer-profiles/` until the slicer or
those files change (`backends/profiles.py`). From OrcaSlicer 2.5 the CLI looks
up a settings file's `inherits` itself, so a user's printer is written without
that link for 2.5 and later (the version comes from `--help`). Bambu Studio is
planned.

Future:

- PrusaSlicer
- Cura

---

## plugins

Optional extensions.

Plugins communicate through published interfaces only.

---

## cli

Command-line interface.

Responsible only for user interaction.

---

## web

Flask dashboard.

Responsible only for presentation.

---

## infrastructure

External integrations.

Examples:

- Filesystem
- SQLite
- Operating System
- External Processes

---

# 7. Service Registry

Application services are created once during startup.

Modules request services from the registry rather than creating them directly.

Benefits include:

- loose coupling
- easier testing
- centralised configuration
- future dependency injection

---

# 8. Data Flow

Typical slicing workflow:

```
User

↓

CLI

↓

Queue

↓

Backend Manager

↓

Orca Backend

↓

OrcaSlicer CLI

↓

Generated G-code

↓

Database

↓

History
```

The flow should remain easy to follow.

---

# 9. Configuration

Configuration is loaded once during startup.

The configuration file is found by `core/config.py` in this order: `--config`,
the `BATCHSLICER_CONFIG` environment variable, `config/config.yaml` in the
current folder (a project checkout), then `~/.config/batchslicer/config.yaml`.
All path settings are read through `Config.get_path()` / `get_program()`:
`~` is expanded, relative paths are relative to the configuration file, and
missing `paths` settings use standard per-user locations (`core/locations.py`,
following the XDG conventions): models and results in `~/BatchSlicer`, logs in
`~/.local/state/batchslicer`, caches in `~/.cache/batchslicer`. BatchSlicer
therefore behaves the same from any working folder.

`batchslicer setup` (`cli/setup.py`) creates the configuration: it detects
installed slicers and their settings folders (`backends/detection.py`) and
writes the file (`render_config`), keeping a backup of any file it replaces.

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

- Multiple printers
- Multiple slicers
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

16. Product Development Philosophy

This wouldn't be technical. It would capture the principles we've agreed on since the beginning:

We solve real problems, not hypothetical ones.
We favour steady, incremental improvement over rapid feature growth.
Every significant architectural decision is documented.
We challenge ideas, not people.
We build software that we would enjoy maintaining ourselves.

I think that final section will make BatchSlicer feel different. It's not just code—it's a project with a clear engineering culture. And that's something I believe will make a real difference as it grows.



# Engineering Culture

This project is developed collaboratively.

The Product Owner defines the problems to solve.

The Software Architect defines the technical direction.

AI coding agents assist implementation.

Architecture is discussed before implementation.

Question assumptions.

Prefer long-term maintainability over short-term convenience.

Every feature must earn its place.