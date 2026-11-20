# BatchSlicer

Slice one 3D model or whole folders of them with **OrcaSlicer**, **Creality
Print** or **Bambu Studio**, using the printer, filament and process presets
you already have in those slicers. Run it interactively and answer a few
questions, or pass everything on the command line for unattended, scripted runs.

BatchSlicer exists to remove friction from the 3D printing workflow through
reliable, maintainable automation. Batch slicing is the first step towards a
dependable automation platform that helps makers, professionals and print
farms spend less time managing printers and more time creating.

---

## Contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Using BatchSlicer interactively](#using-batchslicer-interactively)
- [Using the command line](#using-the-command-line)
- [Output](#output)
- [Exit status and logs](#exit-status-and-logs)
- [Troubleshooting](#troubleshooting)
- [Testing](#testing)
- [Current limitations](#current-limitations)

---

## What it does

- **Works with the slicer you already use.** OrcaSlicer, Creality Print and
  Bambu Studio are supported, driven through their own command-line slicing.
- **Uses your presets.** Choose a printer, then a compatible filament and
  process, from the same lists the slicer shows. Presets you created or edited
  yourself are listed first and marked `(mine)`.
- **Slices one file or a whole folder tree.** Point it at a folder and every
  `.stl`, `.3mf` and `.obj` model in it and its subfolders is sliced, with
  progress shown per file.
- **Keeps your file names.** `bracket.stl` becomes `bracket.gcode`, and a batch
  mirrors your folder structure.
- **Never overwrites earlier results.** Every run gets its own time-stamped
  folder, which also records the exact presets that were used.
- **Explains failures.** A model that fails does not stop the batch; the
  summary lists each failure with the slicer's own reason.
- **Runs unattended.** Every choice can be given as a command-line option, so it
  can be scripted or scheduled.
- **Leaves your slicers alone.** BatchSlicer only reads the slicers' settings
  folders; it never changes them.

| Slicer | Slicing | Preset selection |
|---|---|---|
| OrcaSlicer (tested with 2.4) | Yes | Yes |
| Creality Print (tested with 7.3) | Yes | Yes |
| Bambu Studio (tested with 2.8) | Yes | Not yet (see [limitations](#current-limitations)) |

## How it works

A run goes through these steps. Each choice comes from the command line if you
gave it there, and is asked for otherwise.

1. **Choose a slicer.** Only slicers set up in the configuration can be
   chosen.
2. **Check the environment.** The Python version, the configuration, the
   working folders and the chosen slicer's program and data folder are checked.
   If anything is wrong, each problem is listed and BatchSlicer stops.
3. **Choose presets: printer, filament, process.**
   - Printers are the ones you have added in the slicer, plus printer presets
     you saved yourself.
   - Filaments and processes are limited to those compatible with the chosen
     printer. Built-in filaments are limited to those you have made visible in
     the slicer, so the lists match the slicer's own menus.
4. **Choose what to slice:** one model file, or every model in a folder and its
   subfolders.
5. **Choose the output folder.**
6. **Slice.** BatchSlicer runs the slicer's command-line mode for each model and
   collects the G-code.

**Why preset files are prepared first.** Presets saved in a slicer usually store
only the settings that differ from the preset they are based on, and the
slicers' command-line mode cannot use them in that form. BatchSlicer combines
each chosen preset with everything it inherits from into a complete file, saves
those files with the job, and passes them to the slicer.

**OrcaSlicer's built-in presets.** OrcaSlicer 2.4 keeps its built-in presets in
a packed internal format. The same presets ship as plain files inside the
OrcaSlicer AppImage, so BatchSlicer extracts the vendors you use (for example
Creality) once, caches them in `~/.cache/batchslicer/slicer-profiles/`, and extracts again
automatically when OrcaSlicer is updated. This takes well under a second.

## Requirements

- Linux (the slicers are used as AppImages, or a regular install for
  OrcaSlicer)
- Python 3.12 or newer
- At least one of OrcaSlicer, Creality Print or Bambu Studio installed, and
  **opened at least once** so it has created its settings folder and you have
  added your printers in it

## Installation

From the project folder:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

This creates a private Python environment in `.venv` and installs BatchSlicer
into it, along with the `batchslicer` command and the test tools.

Then let BatchSlicer find your slicers and create its configuration:

```bash
.venv/bin/batchslicer setup
```

## Configuration

### Setting up with `batchslicer setup`

`setup` looks for slicer AppImages in `~/Apps`, `~/Applications`,
`~/AppImages`, `~/Downloads`, `~/Desktop` and `~/.local/bin` (and one folder
below each), in `/opt`, and for slicer programs on your PATH. For each slicer
it shows what it found and recommends the newest stable version:

```
OrcaSlicer:
  1) ~/Apps/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.0.AppImage  (version 2.4.0, recommended)
  2) ~/Downloads/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.3.1.AppImage  (version 2.3.1)
  3) ~/Apps/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.5.0-alpha.AppImage  (version 2.5.0, pre-release)
  4) Don't use OrcaSlicer
Enter for 1, or a number 1-4:
```

Press Enter for the recommendation, pick another version, or skip the slicer.
Setup also finds each slicer's settings folder (for Creality Print, the one
matching the program's version). A slicer that has never been opened is
skipped with a note: open it once, add your printers, and run setup again.

Setup writes `~/.config/batchslicer/config.yaml` and creates
`~/BatchSlicer/incoming` and `~/BatchSlicer/output`. If a configuration already
exists it asks before replacing it and keeps the old one as `config.yaml.bak`.

| Option | Meaning |
|---|---|
| `--config PATH` | write the configuration somewhere else |
| `--no-prompt` | accept the recommended version of each slicer without asking |
| `--force` | replace an existing configuration (needed with `--no-prompt`) |

Flatpak installs are not detected; point the configuration at the slicer
program yourself if you use one.

### Where the configuration lives

BatchSlicer uses the first of these that applies:

1. the file given with `--config PATH`
2. the file named by the `BATCHSLICER_CONFIG` environment variable
3. `config/config.yaml` in the current folder (handy when working in a copy of
   this project)
4. `~/.config/batchslicer/config.yaml` (where `setup` writes it)

### Editing it by hand

`config/config.example.yaml` is a commented template. Each slicer you use needs
two paths; leave both empty for a slicer you do not use:

- `executable`: the slicer program (for example its AppImage, or just a program
  name such as `orca-slicer` if it is on your PATH)
- `datadir`: the folder where the slicer keeps its settings and presets

```yaml
orca:
  executable: "~/Apps/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.0.AppImage"
  datadir: "~/.config/OrcaSlicer"

creality_print:
  executable: "~/Apps/CrealityPrint-V7.3.0.6157-x86_64-Release.AppImage"
  datadir: "~/.config/Creality/Creality Print/7.3"

bambu_studio:
  executable: ""
  datadir: ""

paths:              # all optional; empty means the default
  incoming: ""      # models offered for slicing   (default ~/BatchSlicer/incoming)
  output: ""        # default output folder        (default ~/BatchSlicer/output)
  logs: ""          # log files                    (default ~/.local/state/batchslicer)
  data: ""          # BatchSlicer's working cache  (default ~/.cache/batchslicer)
```

Paths may start with `~` for your home folder. Relative paths are relative to
the folder the configuration file is in, so BatchSlicer behaves the same
whichever folder you run it from. Folders are created when needed.

Typical slicer settings folders on Linux:

| Slicer | `datadir` |
|---|---|
| OrcaSlicer | `~/.config/OrcaSlicer` |
| Creality Print | `~/.config/Creality/Creality Print/<version>` (for example `7.3`) |
| Bambu Studio | `~/.config/BambuStudio` |

## Using BatchSlicer interactively

Put the models you want to slice in your incoming folder
(`~/BatchSlicer/incoming` by default; subfolders are fine), then run:

```bash
.venv/bin/batchslicer
```

BatchSlicer asks one question at a time:

```
Select a slicer:
  1) OrcaSlicer
  2) Creality Print
  3) Bambu Studio  (not configured)
Enter 1-3: 2

Select a printer:
  1) Creality Ender-3 V3 SE 0.4 nozzle
  2) Creality K2 Plus 0.4 nozzle
Printer number, or text to search: 2

Select a filament:
  1) Sliced PETG @Creality K2 Plus 0.4 nozzle  (mine)
  2) CR-PETG @Creality K2 Plus 0.4 nozzle
  ...
Filament number, or text to search: petg
```

How the menus work:

- **Type a number** to pick that entry.
- **Type text** to show only entries containing it (`petg`, `0.12`, `k2`), then
  pick by number from the shorter list. **Press Enter** to show everything
  again.
- **Ctrl+C** (or Ctrl+D) at any question stops BatchSlicer without slicing
  anything.

After the presets you choose what to slice:

```
What would you like to slice?
  1) One model file
  2) Every model in a folder (including subfolders)
```

- **One model file** lists the models directly in the incoming folder. You can also type
  the path to a model anywhere else.
- **Every model in a folder** lists the incoming folder and every folder beneath it that
  contains models, with a count for each. You can also type any folder path.
  BatchSlicer shows how many files it found and asks you to confirm.

Finally, the output folder:

```
Select an output folder:
  1) output  (default)
  2) output/k2-batch
Folder number, a new folder name or path, or Enter for the default:
```

Press Enter for the default, pick an existing folder by number, or type a new
name (created inside the output folder) or a full path (used as typed). BatchSlicer asks
before creating a folder.

## Using the command line

Every question has a matching option. Options you give are used without
asking; anything you leave out is still asked for, unless you add
`--no-prompt`.

| Option | Meaning |
|---|---|
| `--slicer NAME` | `orca`, `creality` or `bambu` (full names such as `"Creality Print"` also work) |
| `--printer NAME` | printer preset name |
| `--filament NAME` | filament preset name (must suit the printer) |
| `--process NAME` | process (print settings) preset name (must suit the printer) |
| `--input PATH` | a model file, or a folder: every model in it and its subfolders is sliced, without asking for confirmation |
| `--output PATH` | output folder; created if missing; defaults to the configured `output` folder |
| `--no-prompt` | never ask anything; a missing choice is an error that names the option to add |
| `--list-presets` | list preset names, then exit (see below) |
| `--help`, `--version` | show help or the version |

Preset names must match the slicer's name exactly, except that upper/lower case
does not matter. Put names containing spaces or `@` in quotes.

### Finding preset names

```bash
# printers for a slicer
.venv/bin/batchslicer --slicer creality --list-presets

# filaments and processes for one printer
.venv/bin/batchslicer --slicer creality --printer "Creality K2 Plus 0.4 nozzle" --list-presets
```

If you mistype a name, BatchSlicer suggests the closest matches:

```
BatchSlicer startup failed: No filament preset named 'Generic PTEG @Creality K2 Plus 0.4 nozzle'
compatible with Creality K2 Plus 0.4 nozzle. Did you mean: 'Generic PETG @Creality K2 Plus 0.4 nozzle'; ...?
```

### Examples

Slice a whole folder, fully unattended:

```bash
.venv/bin/batchslicer --slicer creality \
  --printer "Creality K2 Plus 0.4 nozzle" \
  --filament "Generic PETG @Creality K2 Plus 0.4 nozzle" \
  --process "0.20mm Standard @Creality K2 Plus 0.4 nozzle" \
  --input incoming/brackets \
  --output output/k2-petg \
  --no-prompt
```

Slice one file with OrcaSlicer into the default output folder:

```bash
.venv/bin/batchslicer --slicer orca \
  --printer "Creality K2 Plus 0.4 nozzle" \
  --filament "Generic PLA @System" \
  --process "0.20mm Standard @Creality K2 Plus 0.4 nozzle" \
  --input ~/models/bracket.stl --no-prompt
```

Set the slicer and printer, and be asked for everything else:

```bash
.venv/bin/batchslicer --slicer orca --printer "Creality K2 Plus 0.4 nozzle"
```

Run on a schedule (for example from cron). Use full paths, and `--config` if
the configuration is not in `~/.config/batchslicer/`:

```bash
/path/to/batch_slicer/.venv/bin/batchslicer --slicer creality \
  --printer "..." --filament "..." --process "..." \
  --input ~/BatchSlicer/incoming --output ~/BatchSlicer/output/nightly --no-prompt
```

## Output

Each run creates a new folder inside the output folder, so earlier results are
never overwritten.

**One model** (`bracket.stl`):

```
output/
  bracket-20261120-144428/
    bracket.gcode
    result.json        # the slicer's own report
    presets/           # the complete printer, process and filament files used
```

**A folder** (`incoming/brackets/` with `left.stl` and `old/v1.stl`):

```
output/
  brackets-20261120-144808/
    presets/           # shared by the whole batch
    left/
      left.gcode
      result.json
    old/
      v1/
        v1.gcode
        result.json
```

- G-code is named after the model. A `.3mf` project with several plates gives
  one file per plate: `kit_plate_1.gcode`, `kit_plate_2.gcode`, and so on.
- Two models with the same name in one folder (`part.stl` and `part.3mf`) get
  separate folders (`part` and `part-2`).
- A model that fails still gets its folder, with `result.json` explaining why.

## Exit status and logs

| Exit status | Meaning |
|---|---|
| `0` | everything sliced successfully |
| `1` | a model failed to slice, or BatchSlicer stopped (missing option, unknown preset, failed check, cancelled) |
| `2` | invalid command-line option (for example an unknown `--slicer`) |

A log of every run is written to `batchslicer.log` in the logs folder
(`~/.local/state/batchslicer/` by default), including the choices
made, each slicer command and its result, and the slicer's error output when a
model fails.

## Troubleshooting

**"X is not configured"**: set both `executable` and `datadir` for that slicer
in the configuration, or run `batchslicer setup` again.

**"No configuration file found"**: run `batchslicer setup`, or pass
`--config PATH`. The message lists where BatchSlicer looked.

**"environment verification failed"**: the list underneath names each problem,
usually a wrong path to the slicer program or its settings folder.

**A printer you use is missing from the list**: add it in the slicer itself
(printer selection or setup wizard), close the slicer, and run BatchSlicer
again. BatchSlicer lists the printers the slicer has recorded.

**A filament is missing from the list**: make it visible in the slicer's
filament selection. Only compatible, visible built-in filaments are listed,
plus all of your own.

**"The input model file to the slicer can not be parsed."**: the model file is
damaged or not a valid STL/3MF/OBJ. Open it in the slicer to check.

**"There are some incorrect slicing parameters..."**: the slicer rejected the
combination of presets. Some built-in presets do not suit every nozzle (for
example OrcaSlicer's "0.20mm Standard" for the Ender-3 V3 SE 0.2 mm nozzle uses
layers thicker than that nozzle allows). Try another process preset, and check
`batchslicer.log` (see [logs](#exit-status-and-logs)) for the slicer's detailed output.

**Bambu Studio says "Preset selection is not available"**: see
[limitations](#current-limitations). Slicing a `.3mf` project that already
contains its settings still works.

## Testing

Run the automated tests:

```bash
.venv/bin/pytest
```

Some tests run your real slicers (checking that every option BatchSlicer uses
is accepted, and slicing a test cube with your real presets). They are skipped
unless you point them at your installation:

```bash
BATCHSLICER_TEST_ORCA_EXECUTABLE=~/Apps/OrcaSlicer.AppImage \
BATCHSLICER_TEST_ORCA_DATADIR=~/.config/OrcaSlicer \
BATCHSLICER_TEST_CREALITY_EXECUTABLE=~/Apps/CrealityPrint.AppImage \
BATCHSLICER_TEST_CREALITY_DATADIR="$HOME/.config/Creality/Creality Print/7.3" \
BATCHSLICER_TEST_BAMBU_EXECUTABLE=~/Apps/BambuStudio.AppImage \
.venv/bin/pytest
```

Re-run these after updating a slicer.

## Current limitations

- **Bambu Studio presets** are not selectable yet; slicing works, but without
  preset selection. This needs Bambu Studio's settings folder, which exists
  after it has been opened and set up once.
- **One filament per job.** Multi-material setups (Creality CFS, Bambu AMS)
  need several filaments and are not supported yet.
- **One set of presets per run.** A batch uses the same printer, filament and
  process for every model.
- **"One model file" mode** lists only the models directly in the incoming folder, not
  in its subfolders (type a path, or use folder mode).

See `docs/Architecture.md` for the design and planned features, and
`CHANGELOG.md` for what has changed.
