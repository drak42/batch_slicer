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

### 0.8.0 (2026-11-22): kits on plates

- Several models per plate: each folder's parts arranged together (`--plates`,
  asked before slicing a folder), with a fallback to one per plate.
- Interactive runs ask whether to send the G-code to a printer.

### 0.9.0 (2026-11-22): copies

- Copies of a single model (`--copies N`, asked in interactive runs),
  arranged on as many plates as needed.

### 0.9.1 (2026-11-22): plates survive a failing part

- When one part of a folder fails, the others still go back together on plates.

### 0.9.2 (2026-11-22): on PyPI

- `pipx install batchslicer`; each tagged release is uploaded automatically.

### 0.9.3 (2026-11-22): public

- The repository is public, with issue forms, private vulnerability reporting,
  Dependabot and a protected `main`.

### 0.10.0 (2026-11-23): watch folder, OctoPrint

- `--watch` slices each model or folder dropped into a folder and moves it to
  `sliced` or `failed`.
- `--send` uploads to OctoPrint as well as Klipper/Moonraker (tested against a
  stand-in OctoPrint; still to be tried with a real server).

### 0.11.0 (2026-11-23): watch folder in the background

- `batchslicer service install` runs `--watch` as a systemd user service.

### 0.12.0 (2026-11-23): multi-colour projects

- A filament for every slot of a 3MF project: the chosen one, one per slot,
  or matched to the filaments loaded in the Creality CFS; colour preview
  pictures; grams per filament and filament changes in the report.

### 0.12.1 (2026-11-23): fixes

- Bambu Studio's filament changes are counted; a watch service says how to
  stop it; CFS matching confirmed on a Creality K2 Plus.

### 0.13.0 (2026-11-23): colours for STL kits

- `--slot PATTERN=SLOT` gives STL models their own filament slot, numbered or
  a loaded CFS slot; Creality Print 3MF projects fail at once with the reason.

### 0.14.0 (2026-11-23): flat output

- `--flat` puts a batch's G-code in one folder; `doctor` lists what is loaded
  in a Creality printer's CFS.

### 0.14.1 (2026-11-23): documentation

- A User Guide and a banner; OctoPrint confirmed with a real server.

### 0.14.2 (2026-11-23): support link

- A Buy Me a Coffee link and a Sponsor button.

### 0.15.0 (2026-11-23): dry run

- `--dry-run` shows what a run would do; a terminate request stops
  BatchSlicer like Ctrl+C.

### 0.16.0 (2026-11-24): zip files

- `--input kit.zip` and zips dropped into the watch folder are unpacked
  safely and sliced like a folder.

### 0.16.1 (2026-11-24): fixes and docs

- A zip file's name in messages; a demo script for recording; the step order
  and newest features documented throughout.

## Next

- Multi-colour: the Bambu AMS.
- Windows and macOS work continues on the `feat/windows` and `feat/macos`
  branches (draft pull requests), outside `main`.

## Then: decisions on reach

These need a decision from the project owner before work starts.

- **Visibility**: decided; the repository is public (with issue templates,
  private vulnerability reporting and `SECURITY.md`).
- **PyPI**: decided; published from 0.9.2 with trusted publishing.
- **Audience**: Linux command-line users only, or also people who expect a
  graphical interface and Windows/macOS? This decides between the feature work
  below and the platform work further down.

## Later: features

The features planned here are built. New ones will come from what users ask
for after the launch.

## Later: platform

- **Web interface** (agreed, to be done later; see [WebPlan](WebPlan.md)):
  `batchslicer web` in a browser on this computer, with upload, queue,
  results, download, sending and the printers' CFS; network access with a
  password in the release after; Docker after that.
- Windows and macOS support (locations, slicer detection, reading built-in
  presets without AppImages).
- A standalone download that does not need Python.
- Sending G-code to Bambu Lab printers (LAN mode); Klipper/Moonraker and
  OctoPrint are done.
