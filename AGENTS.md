# AGENTS.md

# Before You Write Code

Ask yourself:

1. Does this feature solve a real user problem?
2. Does it follow the documented architecture?
3. Is this the simplest implementation that satisfies the requirement?
4. Will this still make sense in two years?
5. Would I be happy maintaining this code?

If the answer to any of these questions is "no", stop and rethink the implementation.



## Project

**Product:** BatchSlicer

**Repository:** batch_slicer

BatchSlicer is a professional print automation platform centred around OrcaSlicer. The long-term vision is to remove friction from the entire 3D printing workflow through reliable automation.

---

# Read First

Before making any code changes, read the following documents:

1. docs/Vision.md
2. docs/Architecture.md
3. docs/CodingStandards.md
4. docs/Roadmap.md

These documents are the source of truth.

If implementation conflicts with documentation, the documentation takes precedence unless the task explicitly updates the design.

---

# Development Philosophy

Every feature must provide measurable value.

Build for today.

Design for tomorrow.

Prefer readability over cleverness.

Keep solutions simple.

Avoid unnecessary abstraction.

---

# Architecture

The application follows a layered architecture.

High-level responsibilities are:

- Application
- Services
- Domain
- Backends
- Plugins
- CLI
- Web
- Infrastructure

Do not introduce new architectural layers without discussion.

Do not bypass service boundaries.

---

# Coding Standards

Use:

- Python 3.12+
- pathlib
- dataclasses where appropriate
- type hints
- logging
- pytest

Avoid:

- os.path
- global variables
- circular imports
- duplicated code
- hidden dependencies

Never create a generic `utils.py`.

Modules should have one clearly defined responsibility.

---

# Documentation

Every public class and function should include a docstring.

New modules should begin with a module-level docstring describing:

- Purpose
- Responsibilities
- What the module intentionally does not do

Documentation is considered part of the implementation.

---

# Testing

New functionality should include tests.

Bug fixes should include a regression test where practical.

The project should remain in a working state after every change.

---

# Logging

Use the project logging service.

Do not use print() for diagnostics.

Log messages should explain what happened, not narrate every line of code.

---

# Configuration

Configuration is loaded through the configuration service.

Modules must never read YAML files directly.

Avoid hard-coded paths.

---

# Design Rules

Never:

- Mix UI and business logic
- Access databases directly from UI code
- Access slicer backends from presentation code
- Introduce feature creep
- Break module responsibilities

If a change requires significant architectural changes, stop and ask for approval.

---

# Pull Request Guidelines

Keep pull requests focused.

Prefer several small commits over one large commit.

Large refactors should be split into reviewable stages.

Do not exceed approximately 500–800 changed lines unless the change is purely mechanical.

---

# Commit Messages

Use Conventional Commits.

Examples:

feat(queue): add persistent queue

fix(config): handle missing configuration

docs(architecture): update startup sequence

refactor(logging): simplify logger creation

test(queue): improve queue coverage

---

# Definition of Done

A task is complete when:

- Code builds
- Tests pass
- Documentation updated
- Logging added where appropriate
- Type hints included
- No unnecessary complexity introduced

---

# When Unsure

Prefer asking for clarification rather than making architectural assumptions.

Product direction belongs to the Product Owner.

Architecture belongs to the documented design.

The objective is not to write the most code.

The objective is to build the best software.