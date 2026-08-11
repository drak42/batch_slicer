# OrcaBatch Architecture

**Version:** 0.1.0-alpha  
**Status:** Draft  
**Last Updated:** August 2026

---

# 1. Purpose

This document describes the architectural design of OrcaBatch.

It explains how the application is structured, how components communicate, and the engineering principles that guide every design decision.

This document is intentionally technology-agnostic wherever possible. It focuses on responsibilities rather than implementation.

The architecture is expected to evolve over time, however the core design principles should remain stable throughout the lifetime of the project.

---

# 2. Vision

OrcaBatch exists to remove friction from the entire 3D printing workflow through reliable, maintainable, and thoughtfully engineered automation.

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

OrcaBatch follows a layered architecture.

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

Application startup follows a deterministic sequence.

```
main()

↓

Create Application

↓

Load Configuration

↓

Configure Logging

↓

Initialise Database

↓

Discover Backends

↓

Initialise Services

↓

Ready
```

Every stage must complete successfully before the next begins.

Startup failures should clearly identify the failing stage.

---

# 6. Project Structure

```
src/
└── orcabatch/
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

Initially:

- OrcaSlicer

Future:

- PrusaSlicer
- Cura
- Bambu Studio

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
