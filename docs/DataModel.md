# Data Model

The objects that flow through a run. All are immutable dataclasses; the ones
in `domain/` know nothing about files, slicers or the user interface.

## Choices (`domain/`)

| Object | Module | Holds |
|---|---|---|
| `Preset` | `domain/presets.py` | one preset: name, kind (printer, filament or process), file, whether it is the user's own |
| `PresetSelection` | `domain/presets.py` | the printer, filament and process chosen for one printer; `more_filaments` for slots 2, 3... of a multi-material printer |
| `SliceOptions.slots` | `domain/options.py` | `--slot` rules: (pattern, slot) pairs, a slot being a number or a loaded slot such as `1B` |
| `ProjectFilament` | `domain/filaments.py` | one filament slot of a 3MF project: colour, material, preset name |
| `LoadedFilament` | `domain/filaments.py` | a filament loaded in the printer: CFS slot (`1B`) or `external`, colour, material |
| `Target` | `domain/profiles.py` | one slicer and its preset names, possibly not chosen yet, and the printer its G-code is sent to (`send`); `more_filaments` for slots 2, 3... (stored with `filament` as a list) |
| `Profile` | `domain/profiles.py` | a named run: one or more targets, input, output, and slicing settings (`orient`, `allow_newer_files`, `jobs`, `exclude`, `thumbnails`, `plates`, `copies`) |
| `SliceOptions` | `domain/options.py` | how every model is sliced: auto-orient mode, newer-file handling, preview pictures, models together on plates, copies of a single model |
| `PrinterHost` | `domain/printers.py` | a printer G-code can be sent to: name (or the address as given), API address, API key, and whether it is Moonraker or OctoPrint (`kind`) |

A profile with one target is stored flat in `profiles.yaml`; one with several
lists them under `targets` (`infrastructure/profiles.py`).

## Results (`services/` and `backends/`)

| Object | Module | Holds |
|---|---|---|
| `OrcaResult` | `backends/orca.py` | one slicer process: success, exit code, output, time, command |
| `SliceOutcome` | `services/slicing.py` | one model, or a folder's models sliced together on plates (`models`), or copies of one (`copies`): success, G-code files, the slicer's reason, time, whether auto-oriented, `GcodeStats` |
| `BatchOutcome` | `services/slicing.py` | a batch: outcomes in model order, planned count, interruption, wall-clock time, totals |
| `ThumbnailResult` | `services/thumbnails.py` | the preview picture sizes added to one G-code file, or why none were |
| `GcodeStats` | `services/gcode_stats.py` | print time, filament weight, length and cost read from G-code; for multi-colour prints, grams per filament slot and filament changes |
| `FilamentMatcher` | `services/filament_matching.py` | the loaded filaments with the presets they are sliced as, and which loaded filament each multi-colour project's slots got |
| `Upload`, `SentFile`, `SendOutcome` | `services/sending.py` | sending: each file and its folder on the printer, whether it arrived (and started), per printer |
| `UploadResult` | `infrastructure/printer_api.py` | what the printer did with one upload: its path, whether printing started or was queued |
| `PrinterStatus` | `infrastructure/printer_api.py` | whether a printer is ready to print, its own word for its state, and what answered (Moonraker or OctoPrint, with version) |
| `OpcVendor`, `OpcPreset` | `backends/opc.py` | OrcaSlicer's packed built-in presets, as read from a `.opc` file |

## Files

| File | Written by | Contents |
|---|---|---|
| `config.yaml` | the user or `batchslicer setup` | slicers (`executable`, `datadir`), folders and printers for `--send` (`printers`, kept by `setup`) |
| `profiles.yaml` | every run (`last`) and `--save-profile` | saved profiles |
| `<job>/presets/*.json` | each run | the complete printer, process and filament settings used |
| `<run>/report.csv`, `report.json` | each run | one row per model (see the README's "Reports") |
| `slicer-profiles/<key>/` in the cache | first use of an OrcaSlicer version | built-in presets unpacked as JSON |
