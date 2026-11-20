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

## Next: 0.4.0, dependable in everyday use

- [x] **Weekly test against the newest slicer releases** (OrcaSlicer, Creality
  Print, Bambu Studio), so a slicer update that changes its command line is
  noticed within a week.
- [x] **`batchslicer doctor`**: checks configuration, folders and slicers, and
  produces a report for bug reports.
- [x] **Log rotation** so the log cannot grow without limit.
- [x] **Single-file mode lists models in subfolders.**
- [ ] **Bambu Studio preset selection** (needs a Bambu Studio settings folder to
  verify against).

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
| Batch report (CSV/JSON: print time, filament, status per model) | costing and planning; the numbers are already in each G-code file |
| Several models per plate, and copies | slicing many small parts as one plate saves printer time |
| Parallel slicing (`--jobs N`) | large batches finish faster |
| Watch folder | drop models in, get G-code out, unattended |
| Multi-material (several filaments per printer) | Creality CFS, Bambu AMS |
| Flat output option | all G-code in one folder |

## Later: platform

- Windows and macOS support (locations, slicer detection, reading built-in
  presets without AppImages).
- A standalone download that does not need Python.
- A graphical or web interface (the architecture reserves a `web` layer).
- Sending G-code to printers (Klipper/Moonraker, Bambu LAN, OctoPrint).
