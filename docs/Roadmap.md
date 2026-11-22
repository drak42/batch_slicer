# Roadmap

This is the agreed plan. Items move from **Next** to **Done** as they ship;
`CHANGELOG.md` records the details of each release.

## Done

### 0.2.0 (2026-11-20): first usable release

- Slicing with OrcaSlicer, Creality Print and Bambu Studio.
- Preset selection (printer, filament, process) for OrcaSlicer and Creality
  Print, matching the slicers' own menus.
- Single models and whole folder trees; output mirrors the source folders;
  G-code named after the model.
- Command-line options for every choice and `--no-prompt` for unattended runs.
- `batchslicer setup`, standard per-user locations, clean Ctrl+C and error
  handling, CI and automated GitHub releases.

### 0.3.0 (2026-11-20): reuse and several printers

- Profiles: `--save-profile`, `--profile`, `--last`.
- Slicing the same models for several printers in one run.

### 0.4.0 (2026-11-20): dependable in everyday use

- Weekly test against the newest OrcaSlicer, Creality Print and Bambu Studio
  releases.
- `batchslicer doctor` for checking a setup and reporting problems.
- Log rotation; single-file mode lists models in subfolders.

### 0.5.0 (2026-11-22): large batches (from a soak test of 1,719 real models)

- `--orient retry|always`: slice rejected models again with auto-orient.
- `--allow-newer-files` for projects saved by newer slicers.
- `--jobs N`: several models at once.
- Batch report (`report.csv`, `report.json`) with print time and filament.
- Result folders hold only G-code: slicer status files, folders of failed
  models and partial output of interrupted models are removed.

### 0.6.0 (2026-11-22): every slicer, newest versions

- OrcaSlicer 2.5: reading its packed `.opc` preset files.
- Bambu Studio preset selection; the weekly test now covers its presets.

### 0.7.0 (2026-11-22): leave models out, send to the printer

- `--exclude PATTERN` skips folders and files, such as meshes bundled with
  other software (the soak test's largest group of failures).
- `--send PRINTER` uploads the G-code to a Klipper printer through Moonraker,
  by address or configured name; `--start` prints a single model.

### 0.7.1 (2026-11-22): pictures on the printer's screen

- Preview pictures drawn from the G-code, shown on the K2 Plus touchscreen.
- Sending checked with a real K2 Plus.

## Next

- [x] **Ask about sending in interactive runs** ("Send to k2plus?") when a
  printer is configured or was used last time.
- [ ] **Several models per plate**, and copies: slicing many small parts as one
  plate saves printer time (OrcaSlicer and Bambu Studio; Creality Print has no
  command-line arrange).

## Then: decisions on reach

These need a decision from the project owner before work starts.

- **Visibility**: make the repository public?
- **PyPI**: publish with trusted publishing so `pipx install batchslicer` works
  for anyone (the name is available).
- **Audience**: Linux command-line users only, or also people who expect a
  graphical interface and Windows/macOS? This decides between the feature work
  below and the platform work further down.

## Later: features

| Feature | Why |
|---|---|
| Watch folder | drop models in, get G-code out, unattended |
| Multi-material (several filaments per printer) | Creality CFS, Bambu AMS |
| Flat output option | all G-code in one folder |

## Later: platform

- Windows and macOS support (locations, slicer detection, reading built-in
  presets without AppImages).
- A standalone download that does not need Python.
- A graphical or web interface (the architecture reserves a `web` layer).
- Sending G-code to other printers (Bambu LAN, OctoPrint); Klipper/Moonraker
  is done.
