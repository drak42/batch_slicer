# Data Model

The objects that flow through a run. All are immutable dataclasses; the ones
in `domain/` know nothing about files, slicers or the user interface.

## Choices (`domain/`)

| Object | Module | Holds |
|---|---|---|
| `Preset` | `domain/presets.py` | one preset: name, kind (printer, filament or process), file, whether it is the user's own |
| `PresetSelection` | `domain/presets.py` | the printer, filament and process chosen for one printer |
| `Target` | `domain/profiles.py` | one slicer and its preset names, possibly not chosen yet |
| `Profile` | `domain/profiles.py` | a named run: one or more targets, input, output, and slicing settings (`orient`, `allow_newer_files`, `jobs`) |
| `SliceOptions` | `domain/options.py` | how every model is sliced: auto-orient mode and newer-file handling |

A profile with one target is stored flat in `profiles.yaml`; one with several
lists them under `targets` (`infrastructure/profiles.py`).

## Results (`services/` and `backends/`)

| Object | Module | Holds |
|---|---|---|
| `OrcaResult` | `backends/orca.py` | one slicer process: success, exit code, output, time, command |
| `SliceOutcome` | `services/slicing.py` | one model: success, G-code files, the slicer's reason, time, whether auto-oriented, `GcodeStats` |
| `BatchOutcome` | `services/slicing.py` | a batch: outcomes in model order, planned count, interruption, wall-clock time, totals |
| `GcodeStats` | `services/gcode_stats.py` | print time, filament weight, length and cost read from G-code |
| `OpcVendor`, `OpcPreset` | `backends/opc.py` | OrcaSlicer's packed built-in presets, as read from a `.opc` file |

## Files

| File | Written by | Contents |
|---|---|---|
| `config.yaml` | the user or `batchslicer setup` | slicers (`executable`, `datadir`) and folders |
| `profiles.yaml` | every run (`last`) and `--save-profile` | saved profiles |
| `<job>/presets/*.json` | each run | the complete printer, process and filament settings used |
| `<run>/report.csv`, `report.json` | each run | one row per model (see the README's "Reports") |
| `slicer-profiles/<key>/` in the cache | first use of an OrcaSlicer version | built-in presets unpacked as JSON |
