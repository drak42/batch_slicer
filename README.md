# BatchSlicer

Slice one 3D model or whole folders of them with **OrcaSlicer**, **Creality
Print** or **Bambu Studio**, using the printer, filament and process presets
you already have in those slicers. Run it interactively and answer a few
questions, or pass everything on the command line for unattended, scripted runs.

BatchSlicer exists to remove friction from the 3D printing workflow through
reliable, maintainable automation. Batch slicing is the first step towards a
dependable automation platform that helps makers, professionals and print
farms spend less time managing printers and more time creating.

## Quick start

```bash
pipx install ./batchslicer-*-py3-none-any.whl   # from the latest release
batchslicer setup                                # find your slicers, write the configuration
cp ~/Downloads/*.stl ~/BatchSlicer/incoming/     # put some models where BatchSlicer looks
batchslicer                                      # answer a few questions, get G-code
```

Results appear in `~/BatchSlicer/output`. Next time, `batchslicer --last`
repeats the same run.

---

## Contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Using BatchSlicer interactively](#using-batchslicer-interactively)
- [Using the command line](#using-the-command-line)
- [Profiles](#profiles)
- [Slicing for several printers](#slicing-for-several-printers)
- [Output](#output)
- [Exit status and logs](#exit-status-and-logs)
- [Troubleshooting](#troubleshooting)
- [Checking your setup: `batchslicer doctor`](#checking-your-setup-batchslicer-doctor)
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
- **Slices for several printers at once.** One run can slice the same models
  for different printers, each with its own slicer and presets, into separate
  folders.
- **Remembers your choices.** Save a run as a named profile, or repeat the last
  run with `--last`.
- **Runs unattended.** Every choice can be given as a command-line option or a
  profile, so it can be scripted or scheduled.
- **Leaves your slicers alone.** BatchSlicer only reads the slicers' settings
  folders; it never changes them.

| Slicer | Slicing | Preset selection |
|---|---|---|
| OrcaSlicer (tested with 2.4) | Yes | Yes |
| Creality Print (tested with 7.3) | Yes | Yes |
| Bambu Studio (tested with 2.8) | Yes | Not yet (see [limitations](#current-limitations)) |

## How it works

A run goes through these steps. Each choice comes from the command line or a
profile if you gave it there, and is asked for otherwise.

1. **Start from a profile (optional).** If you have saved profiles and gave no
   options, BatchSlicer offers them first; Enter skips this.
2. **Choose a slicer.** Only slicers set up in the configuration can be
   chosen.
3. **Check the environment.** The Python version, the configuration, the
   working folders and the chosen slicer's program and data folder are checked.
   If anything is wrong, each problem is listed and BatchSlicer stops.
4. **Choose presets: printer, filament, process.**
   - Printers are the ones you have added in the slicer, plus printer presets
     you saved yourself.
   - Filaments and processes are limited to those compatible with the chosen
     printer. Built-in filaments are limited to those you have made visible in
     the slicer, so the lists match the slicer's own menus.
5. **Add another printer (optional).** Repeat steps 2 to 4 for each extra
   printer to slice for.
6. **Choose what to slice:** one model file, or every model in a folder and its
   subfolders.
7. **Choose the output folder.**
8. **Slice.** BatchSlicer runs the slicer's command-line mode for each model
   (and each printer) and collects the G-code. The run's choices are saved as
   the profile `last`.

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

### From a release (recommended)

Download the `.whl` file from the
[latest release](https://github.com/drak42/batch_slicer/releases) and install
it with [pipx](https://pipx.pypa.io/), which keeps BatchSlicer in its own
environment and puts the `batchslicer` command on your PATH:

```bash
pipx install ./batchslicer-*-py3-none-any.whl
batchslicer --version
```

(`python3 -m pip install --user ./batchslicer-*-py3-none-any.whl` works too.)
To upgrade, install the newer file with `pipx install --force`.

### From source (for development)

From a copy of this repository:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

This installs BatchSlicer into `.venv` together with the test and lint tools.
Run it as `.venv/bin/batchslicer` (or activate the environment with
`source .venv/bin/activate`); the examples below just say `batchslicer`.

### First run

Let BatchSlicer find your slicers and create its configuration:

```bash
batchslicer setup
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
  profiles: ""      # saved profiles file          (default ~/.local/share/batchslicer/profiles.yaml)
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
batchslicer
```

BatchSlicer asks one question at a time. If you have saved profiles, it first
offers them (press Enter to skip):

```
Start from a saved profile?
  1) last run: creality_print, Creality K2 Plus 0.4 nozzle, ...
  2) k2-petg: creality_print, Creality K2 Plus 0.4 nozzle, ...
Profile number 1-2, or Enter to choose everything yourself:
```

Otherwise it starts with the slicer and presets:

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

After the presets, BatchSlicer asks `Slice for another printer as well? [y/N]`.
Press Enter to continue with one printer, or `y` to add another (see
[Slicing for several printers](#slicing-for-several-printers)).

Then you choose what to slice:

```
What would you like to slice?
  1) One model file
  2) Every model in a folder (including subfolders)
```

- **One model file** lists the models in the incoming folder and its subfolders
  (shown as `brackets/left.stl`). You can also type the path to a model
  anywhere else.
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
| `--profile NAME` | start from a saved profile (see [Profiles](#profiles)); repeat it to slice for several printers |
| `--last` | repeat the last run |
| `--save-profile NAME` | save this run's choices as a profile |
| `--list-profiles`, `--delete-profile NAME` | list or delete saved profiles |
| `--config PATH` | use a specific configuration file |
| `--help`, `--version` | show help or the version |

Preset names must match the slicer's name exactly, except that upper/lower case
does not matter. Put names containing spaces or `@` in quotes.

### Finding preset names

```bash
# printers for a slicer
batchslicer --slicer creality --list-presets

# filaments and processes for one printer
batchslicer --slicer creality --printer "Creality K2 Plus 0.4 nozzle" --list-presets
```

If you mistype a name, BatchSlicer suggests the closest matches:

```
BatchSlicer startup failed: No filament preset named 'Generic PTEG @Creality K2 Plus 0.4 nozzle'
compatible with Creality K2 Plus 0.4 nozzle. Did you mean: 'Generic PETG @Creality K2 Plus 0.4 nozzle'; ...?
```

### Examples

Slice a whole folder, fully unattended:

```bash
batchslicer --slicer creality \
  --printer "Creality K2 Plus 0.4 nozzle" \
  --filament "Generic PETG @Creality K2 Plus 0.4 nozzle" \
  --process "0.20mm Standard @Creality K2 Plus 0.4 nozzle" \
  --input ~/BatchSlicer/incoming/brackets \
  --output ~/BatchSlicer/output/k2-petg \
  --no-prompt
```

Slice one file with OrcaSlicer into the default output folder:

```bash
batchslicer --slicer orca \
  --printer "Creality K2 Plus 0.4 nozzle" \
  --filament "Generic PLA @System" \
  --process "0.20mm Standard @Creality K2 Plus 0.4 nozzle" \
  --input ~/models/bracket.stl --no-prompt
```

Set the slicer and printer, and be asked for everything else:

```bash
batchslicer --slicer orca --printer "Creality K2 Plus 0.4 nozzle"
```

Run on a schedule (for example from cron). Save the choices as a profile once,
then run it unattended. Cron has a minimal PATH, so give the full path to
`batchslicer` (`command -v batchslicer` shows it), and `--config` if the
configuration is not in `~/.config/batchslicer/`:

```bash
# crontab -e: slice everything in incoming at 02:00 every night
0 2 * * * $HOME/.local/bin/batchslicer --profile nightly --no-prompt >> $HOME/batchslicer-cron.txt 2>&1
```

## Profiles

A profile is a named set of choices (slicer, printer, filament, process, input
and output) that you can reuse instead of typing them again.

```bash
# slice as usual and save the choices under a name
batchslicer --slicer creality --printer "Creality K2 Plus 0.4 nozzle" \
  --filament "Generic PETG @Creality K2 Plus 0.4 nozzle" \
  --process "0.20mm Standard @Creality K2 Plus 0.4 nozzle" \
  --input ~/BatchSlicer/incoming/brackets --save-profile k2-petg

# reuse it; any option you add overrides the profile's choice
batchslicer --profile k2-petg --no-prompt
batchslicer --profile k2-petg --input ~/BatchSlicer/incoming/wheels --no-prompt

# repeat the last run exactly
batchslicer --last --no-prompt

batchslicer --list-profiles
batchslicer --delete-profile k2-petg
```

- Every run's choices are saved automatically as the profile `last`, which
  `--last` repeats.
- When you start `batchslicer` with no options and have saved profiles, it
  first offers them; press Enter to choose everything yourself instead.
- Profile names match ignoring case and may contain letters, digits, spaces,
  dots, dashes and underscores.
- Profiles are kept in `~/.local/share/batchslicer/profiles.yaml` (set
  `paths.profiles` in the configuration to move it). It is plain YAML and can
  be edited by hand.

## Slicing for several printers

One run can slice the same models for more than one printer, each with its own
slicer, filament and process.

**Interactively**, after choosing the presets BatchSlicer asks:

```
Slice for another printer as well? [y/N]
```

Answer `y` to choose another slicer and printer; repeat as often as you like.

**On the command line**, save each printer as a profile and list them:

```bash
batchslicer --profile k2-petg --profile ender-pla \
  --input ~/BatchSlicer/incoming/brackets --no-prompt
```

- Each printer's results go into its own subfolder of the output folder, named
  after the printer (with the slicer's name added if the same printer is used
  with two slicers, and a number if it is used twice with one slicer):

  ```
  output/
    Creality K2 Plus 0.4 nozzle/brackets-20261120-161654/...
    Creality Ender-3 V3 SE 0.4 nozzle/brackets-20261120-161720/...
  ```

- Printers are sliced one after another; a failure for one does not stop the
  others, and a summary at the end lists each printer as ok or FAILED.
  Ctrl+C stops the current printer and skips the rest.
- `--save-profile` saves all the printers as one profile, and `--last` repeats
  the whole run.
- `--slicer`, `--printer`, `--filament` and `--process` describe a single
  printer, so they cannot be combined with several; use one profile per
  printer instead.

In the profiles file, a profile for several printers lists them under
`targets`:

```yaml
k2-and-ender:
  targets:
  - slicer: creality_print
    printer: Creality K2 Plus 0.4 nozzle
    filament: Generic PETG @Creality K2 Plus 0.4 nozzle
    process: 0.20mm Standard @Creality K2 Plus 0.4 nozzle
  - slicer: orca
    printer: Creality Ender-3 V3 SE 0.4 nozzle
    filament: Generic PLA @System
    process: 0.20mm Standard @Creality Ender3V3SE 0.4
  input: ~/BatchSlicer/incoming/brackets
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
  The slicer runs inside that folder, so any extra files it writes (such as
  OrcaSlicer's `00000.log`) stay there, and their reason is added to the
  failure message.

## Exit status and logs

| Exit status | Meaning |
|---|---|
| `0` | everything sliced successfully |
| `1` | a model failed to slice, or BatchSlicer stopped (missing option, unknown preset, failed check, a question was cancelled, or an unexpected error) |
| `2` | invalid command-line option (for example an unknown `--slicer`) |
| `130` | stopped with Ctrl+C |

Progress and results are printed to standard output; error messages go to
standard error, so a script can capture them separately (`2> errors.txt`).

**Stopping a run.** Press Ctrl+C at any time. During a batch, BatchSlicer stops
after cancelling the model being sliced, keeps every model already finished,
and reports what was done and what was not started.

**Unexpected errors.** If BatchSlicer hits a problem it does not expect (a
bug), it prints one line describing it and the location of the log; the full
technical details are in the log. Please include them when reporting a problem.

A log of every run is written to `batchslicer.log` in the logs folder
(`~/.local/state/batchslicer/` by default), including the choices
made, each slicer command and its result, and the slicer's error output when a
model fails. When it reaches about 1 MB it is renamed `batchslicer.log.1` and a
new one is started; the three most recent old logs are kept.

## Troubleshooting

Start with `batchslicer doctor` (see below): it checks the configuration,
folders and each slicer, and names any problem it finds.

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

**"No profile named ..."**: the message lists the saved profiles; check the
spelling with `batchslicer --list-profiles`.

**"... cannot be combined with several printers"**: `--slicer`, `--printer`,
`--filament` and `--process` describe one printer. To change a printer in a
multi-printer run, save it as its own profile and pass each with `--profile`.

**Bambu Studio says "Preset selection is not available"**: see
[limitations](#current-limitations). Slicing a `.3mf` project that already
contains its settings still works.

## Checking your setup: `batchslicer doctor`

```bash
batchslicer doctor
```

Shows the BatchSlicer and Python versions, which configuration file is used and
how it was found, where BatchSlicer keeps its files, and for each configured
slicer whether its program runs and accepts BatchSlicer's commands, whether its
settings folder exists, and how many printers it offers. It also checks that
saved profiles can be read. It ends with "No problems found." or a list of
problems and what to do about them, and exits with status 0 or 1.

When reporting a problem, please include the output of `batchslicer doctor`.
Use `--config PATH` to check a specific configuration file.

## Testing

Run the same checks as the automated build (GitHub Actions runs them on every
push to `main` and on every pull request, with Python 3.12 and 3.13):

```bash
.venv/bin/ruff check src tests   # lint: errors, import order, likely bugs
.venv/bin/mypy                   # type check
.venv/bin/pytest                 # tests
```

The tests never touch your real BatchSlicer folders or configuration.

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

GitHub Actions also runs these tests every week against the newest release of
each slicer, using a minimal stand-in settings folder created by
`scripts/make_test_slicer_data.py`, so a slicer update that changes its
command line is noticed quickly. It can be started by hand from the Actions
tab ("Latest slicers").

## Current limitations

- **Bambu Studio presets** are not selectable yet; slicing works, but without
  preset selection. This needs Bambu Studio's settings folder, which exists
  after it has been opened and set up once.
- **Linux only.** Windows and macOS are not supported yet.
- **One filament per printer.** Multi-material setups (Creality CFS, Bambu AMS)
  need several filaments and are not supported yet.
- **The same presets for every model.** Within a run, each printer uses one
  filament and process for all models; to vary them, use separate runs or
  profiles.
- **One model at a time, one model per plate.** Models are sliced one after
  another, and several models are not arranged onto one plate.
- **Flatpak installs are not detected** by `batchslicer setup`; configure them
  by hand.

See `docs/Architecture.md` for the design and planned features, and
`CHANGELOG.md` for what has changed.
