# BatchSlicer

Slice one 3D model or whole folders of them with **OrcaSlicer**, **Creality
Print** or **Bambu Studio**, using the printer, filament and process presets
you already have in those slicers. Run it interactively and answer a few
questions, or pass everything on the command line for unattended, scripted runs.
It can put a kit's parts together on plates, adds preview pictures for printer
screens, and can send the G-code straight to a Klipper printer.

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
- [Sending G-code to a printer](#sending-g-code-to-a-printer)
- [Output](#output) (including [several models per plate](#several-models-per-plate), [reports](#reports) and [speed](#speed))
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
  progress shown per file. `--exclude` leaves out folders or files you do not
  want, such as old versions or meshes bundled with other software.
- **Puts small parts together on plates.** When slicing a folder, the parts in
  each folder (a kit, say) can be arranged on as few plates as fit, giving one
  G-code file per plate instead of one print per part.
- **Keeps your file names.** `bracket.stl` becomes `bracket.gcode`, and a batch
  mirrors your folder structure.
- **Never overwrites earlier results.** Every run gets its own time-stamped
  folder, which also records the exact presets that were used.
- **Explains failures.** A model that fails does not stop the batch; the
  summary lists each failure with the slicer's own reason, and suggests an
  option when one may fix it.
- **Rescues awkwardly saved models.** With `--orient retry`, a model the slicer
  rejects is sliced again with the slicer's auto-orient. In a test on 1,719
  downloaded models this fixed 97 of 115 "Failed slicing the model" errors.
- **Adds preview pictures for printer screens.** Slicers draw these only in
  their windows, so BatchSlicer draws them from the G-code itself: the part as
  it will print, in the filament's colour.
- **Reports print time and filament.** Every run writes `report.csv` and
  `report.json` with each model's status, print time, filament weight, length
  and cost, and the summary shows the totals.
- **Can slice several models at once.** `--jobs N` runs N slicers side by
  side, which helps most on computers with many cores (see [Speed](#speed)).
- **Slices for several printers at once.** One run can slice the same models
  for different printers, each with its own slicer and presets, into separate
  folders.
- **Sends the G-code to your printer.** With `--send`, the G-code goes straight
  to a Klipper printer over the network (Moonraker), keeping the folder
  structure; `--start` starts printing a single model.
- **Remembers your choices.** Save a run as a named profile, or repeat the last
  run with `--last`.
- **Runs unattended.** Every choice can be given as a command-line option or a
  profile, so it can be scripted or scheduled.
- **Leaves your slicers alone.** BatchSlicer only reads the slicers' settings
  folders; it never changes them.

| Slicer | Slicing | Preset selection | Several models per plate |
|---|---|---|---|
| OrcaSlicer (tested with 2.4 and 2.5) | Yes | Yes | Yes |
| Creality Print (tested with 7.3) | Yes | Yes | No (no command-line arrange) |
| Bambu Studio (tested with 2.8 and 2.9) | Yes | Yes | Yes |

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
   subfolders. For a folder whose subfolders hold several loose models,
   BatchSlicer asks whether to put each folder's models together on plates.
7. **Choose the output folder.**
8. **Send to a printer (optional).** If a printer is configured or the last
   run sent to one, BatchSlicer asks whether to send the G-code there. It
   checks that the printer answers before slicing anything.
9. **Slice.** BatchSlicer runs the slicer's command-line mode for each model
   (or each folder of models on plates, and each printer), collects the
   G-code, and adds preview pictures to it. The run's choices are saved as the
   profile `last`.
10. **Report and send.** The summary shows print time and filament, a report
    is written, and the G-code goes to the printer if you chose one.

**Why preset files are prepared first.** Presets saved in a slicer usually store
only the settings that differ from the preset they are based on, and the
slicers' command-line mode cannot use them in that form. BatchSlicer combines
each chosen preset with everything it inherits from into a complete file, saves
those files with the job, and passes them to the slicer.

**OrcaSlicer's built-in presets.** OrcaSlicer 2.4 and later keep their
built-in presets in packed `.opc` files. BatchSlicer takes the vendors you use
(for example Creality) from the OrcaSlicer program itself (2.4 ships them as
plain files, 2.5 as `.opc` files, which BatchSlicer reads), or from the `.opc`
files in OrcaSlicer's settings folder for vendors the program does not ship.
They are unpacked once into `~/.cache/batchslicer/slicer-profiles/` and again
automatically when OrcaSlicer or those files change. This takes about a
second.

## Requirements

- Linux (the slicers are used as AppImages, or a regular install for
  OrcaSlicer)
- Python 3.12 or newer
- At least one of OrcaSlicer, Creality Print or Bambu Studio installed, and
  **opened at least once** so it has created its settings folder and you have
  added your printers in it
- Optional, for sending G-code: a printer running Klipper with Moonraker (such
  as the Creality K1 and K2 series) on your network

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
  1) ~/Apps/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.5.2.AppImage  (version 2.5.2, recommended)
  2) ~/Apps/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.0.AppImage  (version 2.4.0)
  3) ~/Downloads/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.6.0-beta.AppImage  (version 2.6.0, pre-release)
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
  executable: "~/Apps/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.5.2.AppImage"
  datadir: "~/.config/OrcaSlicer"

creality_print:
  executable: "~/Apps/CrealityPrint-V7.3.0.6157-x86_64-Release.AppImage"
  datadir: "~/.config/Creality/Creality Print/7.3"

bambu_studio:
  executable: "~/Apps/BambuStudio_ubu24-v02.09.01.70-20261103183404.AppImage"
  datadir: "~/.config/BambuStudio"

paths:              # all optional; empty means the default
  incoming: ""      # models offered for slicing   (default ~/BatchSlicer/incoming)
  output: ""        # default output folder        (default ~/BatchSlicer/output)
  logs: ""          # log files                    (default ~/.local/state/batchslicer)
  data: ""          # BatchSlicer's working cache  (default ~/.cache/batchslicer)
  profiles: ""      # saved profiles file          (default ~/.local/share/batchslicer/profiles.yaml)

printers:           # optional: printers for --send (see "Sending G-code to a printer")
  k2plus:
    url: "http://192.168.1.50:7125"
    api_key: ""     # only if Moonraker asks for one
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

When you slice a folder whose subfolders hold several loose models (STL, OBJ
or STEP files), BatchSlicer asks whether to put them together on plates (see
[Several models per plate](#several-models-per-plate)):

```
Put the models in each folder together on plates? (8 models in 1 folder could share plates; 3MF projects keep their own) [y/N]
```

Enter keeps what the last run did. The question is skipped with `--plates` or
`--no-plates`, for runs from a profile, and for Creality Print (which cannot
arrange from its command line).

Last, if you have a printer to send to (one in the configuration's `printers`
section, or the one the last run sent to), BatchSlicer asks whether to send
the G-code there (see [Sending G-code to a printer](#sending-g-code-to-a-printer)):

```
Send the G-code to a printer?
  0) Don't send
  1) k2plus (http://192.168.1.242:7125)  (last time)
  Or type another printer's address, such as 192.168.1.50
Enter for 1, a number 0-1, or an address:
```

Enter keeps what the last run did. If you have never sent to a printer, this
question is not asked. It is also skipped when the run comes from a profile
or `--last` (the profile decides), with `--send` or `--no-send`, and for runs
that slice for several printers.

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
| `--orient MODE` | the slicer's auto-orient: `off` (default), `retry` (slice a model that fails once more with auto-orient) or `always` (auto-orient every model; this may rotate parts saved the right way up). Not available for Creality Print |
| `--allow-newer-files` | let the slicer open `.3mf` projects saved by a newer slicer version (`--no-allow-newer-files` turns off a profile's setting) |
| `--jobs N` | slice N models at the same time (default 1); see [Speed](#speed) |
| `--plates` | when slicing a folder, put the loose models of each folder together on as few plates as fit (see [Several models per plate](#several-models-per-plate)); `--no-plates` slices each model on its own |
| `--no-thumbnails` | don't add preview pictures to the G-code (see [Output](#output)); `--thumbnails` turns them back on over a profile |
| `--exclude PATTERN` | leave out folders or files matching PATTERN when slicing a folder; repeat for several (see [Leaving models out](#leaving-models-out)) |
| `--send PRINTER` | after slicing, upload the G-code to PRINTER: its address (`192.168.1.50`, `k2.local:4408` or a full URL) or a name from the configuration's `printers` section (see [Sending G-code to a printer](#sending-g-code-to-a-printer)); `--no-send` turns off a profile's printer |
| `--start` | start printing once the G-code is on the printer; only for a single model that gives one G-code file |
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

A large batch, two models at a time, rescuing models the slicer rejects and
leaving out the printer-bed meshes that come with Cura:

```bash
batchslicer --profile k2-pla --input ~/Downloads \
  --exclude "Cura-*" --orient retry --allow-newer-files --jobs 2 --no-prompt
```

A folder of kits, each kit's parts together on plates, sent to the printer:

```bash
batchslicer --profile k2-pla --input ~/BatchSlicer/incoming/kits   --plates --send 192.168.1.242 --no-prompt
```

One model, sent to the printer and started:

```bash
batchslicer --profile k2-pla --input ~/models/bracket.stl --send 192.168.1.242 --start
```

### Leaving models out

`--exclude PATTERN` leaves out models when slicing a folder. Repeat it for
several patterns.

| Pattern | Leaves out |
|---|---|
| `Cura-*` | every folder (or file) whose name starts with `Cura-`, at any depth |
| `old` | every folder named `old`, wherever it is |
| `*_v1.stl` | files ending in `_v1.stl`, in any folder |
| `kits/old` | only the `old` folder inside `kits`, within the folder being sliced |
| `*/supports/*` | anything inside a `supports` folder one or more levels down |

- A pattern without `/` matches any single folder or file name; a pattern with
  `/` matches a path inside the folder being sliced.
- `*`, `?` and `[...]` work as in the shell, and upper/lower case is ignored.
  Quote patterns so the shell does not expand them.
- BatchSlicer says how many model files it skipped. If every model matches, it
  stops without slicing.
- A single model file chosen explicitly is always sliced.
- Hidden folders (names starting with `.`) are always skipped.

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
and output, plus `--orient`, `--allow-newer-files`, `--jobs`, `--exclude`,
`--plates`, `--thumbnails` and `--send` if you gave them; `--start` is never
saved) that you can reuse instead of typing them again. Options you
add override the profile's; for `--exclude`, the patterns you give replace the
profile's list.

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
    send: 192.168.1.242          # optional: this printer's G-code is sent here
  - slicer: orca
    printer: Creality Ender-3 V3 SE 0.4 nozzle
    filament: Generic PLA @System
    process: 0.20mm Standard @Creality Ender3V3SE 0.4
  input: ~/BatchSlicer/incoming/brackets
```

## Sending G-code to a printer

BatchSlicer can upload the G-code to a printer running Klipper with
Moonraker, its web interface: the Creality K1 and K2 series, Voron and many
others. Give the printer's address directly:

```bash
batchslicer --profile k2-pla --input ~/BatchSlicer/incoming/kit --send 192.168.1.50
batchslicer --profile k2-pla --input ~/BatchSlicer/incoming/kit --send 192.168.1.50:4408
```

An address without a port uses Moonraker's usual port 7125; `k2.local` and
full URLs such as `http://192.168.1.50:7125` work too. Nothing needs to be set
up first.

Or name each printer once in the configuration, which also lets you set an
API key, and use the name:

```yaml
printers:
  k2plus:
    url: "http://192.168.1.50:7125"   # the printer's address and Moonraker's port
    api_key: ""                       # only if Moonraker asks for one
```

The address is the one you open in a browser for Fluidd or Mainsail, or the
one in your slicer's "physical printer" or "send to printer" settings. Then:

```bash
# slice a folder and put the results on the printer
batchslicer --profile k2-pla --input ~/BatchSlicer/incoming/kit --send k2plus

# slice one model and start printing it
batchslicer --profile k2-pla --input bracket.stl --send k2plus --start
```

- Before slicing, BatchSlicer checks that the printer answers, so a long
  batch doesn't run only to find the printer switched off.
- The files go into the printer's G-code folder. A batch keeps its folder
  structure inside a folder named like the batch
  (`kit-20261122-073000/arms/left.gcode`), and a single model goes to the top
  folder. A file already on the printer with the same name is replaced.
- Only models that sliced are sent. A file the printer refuses is listed,
  and makes the run end with status 1.
- `--start` works for one model that gives one G-code file. If the printer is
  busy or not ready, the file stays on it without starting (or joins
  Moonraker's job queue, if that is on).
- A profile remembers the printer (`--send`), but never `--start`, so a saved
  profile cannot start prints by itself. `--no-send` skips sending for one run.
- With several printers, each profile sends to its own printer.
- In an interactive run, BatchSlicer asks whether to send (see
  [Using BatchSlicer interactively](#using-batchslicer-interactively)), and
  offers the printer used last time as the default.
- `batchslicer doctor` checks that every configured printer answers.
- **Creality K2 Plus** (tested): Moonraker answers on port 7125 and on 4408,
  with no API key needed, and the touchscreen shows the batch folders and
  BatchSlicer's preview pictures. Creality Print's device list shows the
  printer's address. When a file is replaced under the same name, the screen
  may keep showing the old picture (or none); in testing, sending the file
  again fixed it.

## Output

Each run creates a new folder inside the output folder, so earlier results are
never overwritten.

**One model** (`bracket.stl`):

```
output/
  bracket-20261120-144428/
    bracket.gcode
    presets/           # the complete printer, process and filament files used
    report.csv         # see "Reports" below
    report.json
```

**A folder** (`incoming/brackets/` with `left.stl` and `old/v1.stl`):

```
output/
  brackets-20261120-144808/
    presets/           # shared by the whole batch
    report.csv
    report.json
    left/
      left.gcode
    old/
      v1/
        v1.gcode
```

- G-code is named after the model. A `.3mf` project with several plates gives
  one file per plate: `kit_plate_1.gcode`, `kit_plate_2.gcode`, and so on.
- With `--plates`, a folder's models sliced together go into a `plates` folder
  instead (see below).
- Two models with the same name in one folder (`part.stl` and `part.3mf`) get
  separate folders (`part` and `part-2`).
- A model that fails leaves no folder; its reason is in the summary, the
  report and the log. The slicer's own status files (`result.json`,
  `00000.log`) are read and then removed, so result folders hold only G-code.
- A model that was stopped by Ctrl+C leaves nothing behind (no partial G-code).
- **Preview pictures.** Slicers draw the pictures printer screens show only
  in their windows, so G-code sliced from the command line has none.
  BatchSlicer adds them, drawn from the G-code itself: the walls and surfaces
  of the part as it will print (after any auto-orient, and per plate of a
  project), seen from the front at an angle in the filament's colour. The
  sizes are the ones the printer preset asks for (usually 300x300 and 96x96),
  in the PNG format OrcaSlicer and Creality Print use. It takes about a second
  for a typical model (around 10 seconds for an 80 MB file); `--no-thumbnails`
  skips it. G-code that already has pictures is left as it is.

### Several models per plate

Kits often come as a folder of small parts. Printing them one per plate wastes
printer time, so BatchSlicer can slice each folder's parts together: the
slicer arranges them on the bed and adds plates for any that don't fit. Turn
it on by answering `y` to the question in an interactive run, or with
`--plates`:

```bash
batchslicer --profile k2-pla --input ~/BatchSlicer/incoming/kits --plates
```

```
output/
  kits-20261122-211835/
    Lastman kit/
      plates/
        Lastman kit.gcode            # one plate: all 8 parts
    Swamp trailer/
      plates/
        Swamp trailer_plate_1.gcode  # more parts than fit on one plate
        Swamp trailer_plate_2.gcode
```

- **What goes together:** the loose models (STL, OBJ, STEP) directly in the
  same folder. 3MF projects keep their own plates, and a folder with a single
  model slices as usual. Subfolders are separate groups.
- **Names:** the G-code is named after the folder. Sent to a printer, it lands
  at `kits-.../Lastman kit/Lastman kit.gcode`.
- **If a part fails,** for example a damaged file, the folder's models are
  sliced one by one instead, so the rest still slice:
  `Lastman kit/ (models together on plates) ... could not share plates; sliced one by one:`.
- **The report** has one row per folder, with its models in the `models`
  column; the summary counts every model and the plates they're on.
- `--orient always` auto-orients the parts before arranging. With
  `--orient retry`, a part that fails is retried with auto-orient when the
  folder falls back to one by one.
- OrcaSlicer and Bambu Studio only: Creality Print cannot arrange from its
  command line.
- Profiles can save the choice (`--plates` or `--no-plates`).

### Reports

Every run writes `report.csv` (opens in any spreadsheet) and `report.json` (the
same, for scripts) with one row per model:

| Column | Meaning |
|---|---|
| `model` | the model, relative to the folder that was sliced |
| `status` | `ok` or `failed` |
| `auto_oriented` | `yes` if the G-code came from the slicer's auto-orient (see `--orient`) |
| `gcode` | the G-code file(s), relative to the run's folder |
| `print_time`, `print_seconds` | the slicer's estimated print time |
| `filament_g`, `filament_m`, `filament_cost` | filament weight (g), length (m) and cost, as calculated by the slicer from the filament preset |
| `slice_seconds` | how long slicing took |
| `message` | why the model failed |

A batch's report is updated as it runs, so an interrupted batch still has a
report of what was finished. The summary at the end shows the totals, for
example `To print: 12h 41m, 255 g filament, filament cost 5.07`.

### Speed

Models are sliced one at a time unless `--jobs N` is given. The slicers are
already multi-threaded, so the gain depends on the computer and the models,
and more jobs is not always faster. Each slicer can also use 1-2 GB of memory.
Measured on a 4-core computer with OrcaSlicer, 40 typical models:

| `--jobs` | Time |
|---|---|
| 1 | 2m 42s |
| 2 | 2m 23s (12% faster) |
| 4 | 2m 48s (no faster) |

Start with `--jobs 2` and compare the times the summary shows; computers with
more cores and memory gain more. Progress is shown as each model finishes.

## Exit status and logs

| Exit status | Meaning |
|---|---|
| `0` | everything sliced successfully (and was sent, with `--send`) |
| `1` | a model failed to slice, a file could not be sent to the printer, or BatchSlicer stopped (missing option, unknown preset, failed check, a question was cancelled, or an unexpected error) |
| `2` | invalid command-line option (for example an unknown `--slicer`) |
| `130` | stopped with Ctrl+C |

Progress and results are printed to standard output; error messages go to
standard error, so a script can capture them separately (`2> errors.txt`).

**Stopping a run.** Press Ctrl+C at any time. During a batch, BatchSlicer stops
the slicer(s) still running, keeps every model already finished, and reports
what was done and what was not sliced.

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

**"Failed slicing the model ..."** (OrcaSlicer 2.4, often with "found slicing
or export error for partplate 1") or **"One object has an empty first layer"**
(OrcaSlicer 2.5): usually the part was saved in an orientation that cannot be
printed as it is, for example floating above the bed or balanced on an
edge. Add `--orient retry` to slice such models again with the slicer's
auto-orient, and check the result in the slicer before printing.

**"One of the plate is empty or has no object fully inside it"** (2.5: "The
plate has nothing to slice"): the model is larger than the printer's bed, or a
project plate has nothing on it. If such files are not models at all (for
example the printer-bed meshes in a Cura download), leave them out with
`--exclude`.

**"Unsupported 3MF version ..."**: the project was saved by a newer version of
the slicer (for example Bambu Studio 2.5 or 2.6 projects in OrcaSlicer 2.4 or 2.5). Add
`--allow-newer-files`, or update the slicer.

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

**"Cannot reach k2plus ..."**: the printer is off, on another network, or the
address or port is wrong. Open the address in a browser: it should show
Fluidd or Mainsail. Moonraker's own port is usually 7125.

**"... refused access (HTTP 401)"**: Moonraker only accepts known clients.
Add this computer's address (or its network, such as `192.168.1.0/24`) to
`trusted_clients` in the `[authorization]` section of the printer's
`moonraker.conf`, or set `api_key` to Moonraker's API key.

**"... cannot arrange models from its command line, so --plates cannot be
used with it"**: Creality Print's command line has no arrange. Use OrcaSlicer
or Bambu Studio for `--plates`, or slice each model on its own.

**A folder's line says "could not share plates; sliced one by one"**: one of
its parts failed when sliced together (its reason is listed under "Failed").
The other parts were sliced one per plate. Fix or `--exclude` the failed part
and run again to get them on plates.

**"No printer named ..."**: the name after `--send` must match one in the
configuration's `printers` section (the message lists them), or be the
printer's address, such as `192.168.1.50`.

**Bambu Studio lists no printers, or not the one you expect**: Bambu Studio
records the printer *models* you added (with their nozzle sizes), and
BatchSlicer lists the shipped printers for those, plus printers you created
yourself. Add the model in Bambu Studio (printer selection), close it, and
run BatchSlicer again. Bambu Studio must have been opened and set up once.

## Checking your setup: `batchslicer doctor`

```bash
batchslicer doctor
```

Shows the BatchSlicer and Python versions, which configuration file is used and
how it was found, where BatchSlicer keeps its files, and for each configured
slicer whether its program runs and accepts BatchSlicer's commands, whether its
settings folder exists, and how many printers it offers. It also checks that
each printer for `--send` answers, and that saved profiles can be read. It ends with "No problems found." or a list of
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

The tests never touch your real BatchSlicer folders or configuration, and
never contact a real printer: sending is tested against a stand-in Moonraker
that runs on your computer during the test.

Some tests run your real slicers (checking that every option BatchSlicer uses
is accepted, reading OrcaSlicer's packed `.opc` preset files, and slicing a
test cube with your real presets). They are skipped unless you point them at
your installation:

```bash
BATCHSLICER_TEST_ORCA_EXECUTABLE=~/Apps/OrcaSlicer.AppImage \
BATCHSLICER_TEST_ORCA_DATADIR=~/.config/OrcaSlicer \
BATCHSLICER_TEST_CREALITY_EXECUTABLE=~/Apps/CrealityPrint.AppImage \
BATCHSLICER_TEST_CREALITY_DATADIR="$HOME/.config/Creality/Creality Print/7.3" \
BATCHSLICER_TEST_BAMBU_EXECUTABLE=~/Apps/BambuStudio.AppImage \
BATCHSLICER_TEST_BAMBU_DATADIR=~/.config/BambuStudio \
.venv/bin/pytest
```

Re-run these after updating a slicer.

GitHub Actions also runs these tests every week against the newest release of
each slicer, using a minimal stand-in settings folder created by
`scripts/make_test_slicer_data.py`, so a slicer update that changes its
command line or its presets is noticed quickly. It can be started by hand from
the Actions tab ("Latest slicers").

## Current limitations

- **Linux only.** Windows and macOS are not supported yet.
- **One filament per printer.** Multi-material setups (Creality CFS, Bambu AMS)
  need several filaments and are not supported yet.
- **The same presets for every model.** Within a run, each printer uses one
  filament and process for all models; to vary them, use separate runs or
  profiles.
- **No copies yet.** `--plates` puts each part on a plate once; printing
  several copies of a part needs them as separate files.
- **One bad part splits a folder.** If any part fails, the whole folder is
  sliced one model per plate, not just the failed part.
- **Sending needs Klipper with Moonraker.** Bambu Lab printers (LAN mode),
  OctoPrint and Creality printers without Moonraker are not supported yet.
- **Flatpak installs are not detected** by `batchslicer setup`; configure them
  by hand.

See `docs/Roadmap.md` for planned features, `docs/Architecture.md` for the
design, and `CHANGELOG.md` for what has changed.
