# Startup and run sequence

What happens, in order, when `batchslicer` runs. Each step that makes a choice
takes it from the command line or a profile when given, and otherwise asks,
unless `--no-prompt` is used (then a missing choice is an error). Code lives in
`src/batchslicer/app.py` unless noted.

## Commands

`batchslicer setup` (`cli/setup.py`), `batchslicer doctor` (`cli/doctor.py`)
and `batchslicer service` (`cli/service.py`) are separate commands chosen by
the first argument; they do not slice. A service runs a normal watch run
(below) with `--watch --no-prompt`. Everything below describes a normal run.

## Sequence

Throughout a run, a request to terminate (SIGTERM, from `kill` or
`systemctl stop`) is handled like Ctrl+C: slicers are stopped and partial
results removed, and the run ends with exit status 130 (0 for a watch run).

1. **Parse options** (`cli/arguments.py`). Invalid options stop with exit
   status 2.
2. **Show the banner**, except for listing commands (`--list-presets`,
   `--list-profiles`, `--delete-profile`).
3. **Load the configuration** (`core/config.py`): `--config`, then
   `BATCHSLICER_CONFIG`, then `./config/config.yaml`, then
   `~/.config/batchslicer/config.yaml` (`%APPDATA%\BatchSlicer\config.yaml`
   on Windows, `~/Library/Application Support/BatchSlicer/config.yaml` on
   macOS).
4. **Configure logging** (`core/logging.py`) in the configured logs folder,
   rotating at about 1 MB.
5. **Open the profiles store** (`infrastructure/profiles.py`); handle
   `--list-profiles` / `--delete-profile` and stop if given.
6. **Plan the targets.** Profiles from `--profile` / `--last` are combined;
   with no options and saved profiles, one is offered. Command-line slicer and
   preset options fill in or override a single target.
7. **For each target:**
   1. choose the slicer (only configured slicers are offered);
   2. verify the environment for that slicer (`core/environment.py`), once per
      slicer;
   3. load its presets (`backends/presets.py`, with built-in presets located or
      extracted by `backends/profiles.py`);
   4. choose the printer, then a compatible filament and process
      (`cli/preset_prompt.py`).

   In an interactive run, "Slice for another printer as well?" adds targets.
   `--list-presets` stops here after printing names. A target with `--send`
   (or a profile's `send`) is given its printer from the configuration's
   `printers` section, or from the address given (`domain/printers.py`).
8. **Choose what to slice** (`cli/file_prompt.py`; a zip file given with
   `--input` is first unpacked into a temporary folder in the data folder by
   `services/archives.py`, removed when the run ends) and leave out models
   matching `--exclude` (`exclude_models`). For a folder with loose models to share plates,
   an interactive run without a profile, `--plates` or `--no-plates` asks
   whether to slice each folder's models together; `--plates` is refused for
   Creality Print. For a single STL, OBJ or STEP model it asks how many copies
   to make (`--copies`); copies are refused for folders, 3MF projects and
   Creality Print (a profile's copies are left out with a note). An interactive run without a profile, `--send`
   or `--no-send` then asks whether to send the G-code
   (`cli/send_prompt.py`), when a printer is configured or the last run sent
   to one. When the input holds a multi-colour 3MF project and no filaments
   or `--loaded-filaments` were given, it asks how to fill the filament
   slots: matched to the filaments loaded in the printer it sends to, the
   chosen filament in every slot, or one chosen per slot. `--start` and
   `--slot` are checked here: `--start` needs every target to send and a
   single model, and each `--slot` must name a filament that will be there.
   With `--dry-run`, the run stops at this point: it asks each printer
   whether it answers and what is loaded (a printer that does not answer is
   reported, not an error), lists each model or plate group, copies, `--slot`
   filaments, how multi-colour projects would be filled, models that would
   fail, and where results would go and be sent, then exits without creating
   the output folder, slicing, sending or remembering the run. Otherwise
   **the output folder** is chosen last (`cli/output_prompt.py`), and each
   printer to send to must answer (`infrastructure/printer_clients.py`), so
   nothing is sliced for a printer that is off.
9. **Remember the run** as the profile `last`, and as `--save-profile` if given.
10. **Check the slicing options** (`--orient`, `--allow-newer-files`,
    `--jobs`, possibly from a profile) against each chosen slicer, and show
    them with the presets.
11. **Slice** (`services/slicing.py`, `backends/orca.py`): for each target, a
    job folder (one model) or batch folder (a folder of models) is created, the
    resolved presets are written into it, and the slicer runs inside each
    model's folder, up to `--jobs` at a time. With `--plates` the loose models
    of each folder are one job (`--arrange 1`, named after the folder); if that
    fails, each is sliced on its own and those that slice as they are go back
    together on plates. With `--orient retry` a failed
    model is sliced once more with auto-orient. The slicer's status files are
    read and removed; folders of failed or interrupted models are removed.
    A 3MF project is given one filament per slot it lists
    (`backends/projects.py`): the chosen filaments in order, the last one
    filling the rest, or with `--loaded-filaments` the loaded filaments that
    match its colours (`services/filament_matching.py`, the printer's CFS read
    once per target). Preview pictures are drawn from each G-code file, each
    filament in its colour, and inserted into it (`services/thumbnails.py`)
    unless `--no-thumbnails` is given.
12. **Report** (`services/report.py`, `services/gcode_stats.py`): write
    `report.csv` and `report.json` (kept up to date during a batch), show the
    summary with print time and filament totals and hints for failures an
    option may fix.
13. **Send** (`services/sending.py`): for a target with a printer, the G-code
    of every model that sliced is uploaded, keeping the batch's folders, and
    with `--start` a single file is started. Exit: 0 success, 1 failure
    (slicing or sending), 130 interrupted.

Failures before slicing stop the run with a message naming the problem.
Ctrl+C at any point stops cleanly: running slicers are stopped and a batch
keeps its finished models. Unexpected
errors are reported in one line with details in the log.

## Watch runs (`--watch`)

Steps 1 to 7 and 10 are the same. Then, instead of steps 8 to 13 once:

- The watched folder is `--input` as typed on the command line (never a
  profile's input) or the configured incoming folder, created if missing.
- An interactive run without a profile asks once whether dropped folders go
  on plates, whether to send (`cli/send_prompt.py`) and where the output goes.
  The output folder must not be inside the watched folder. Printers to send
  to must answer.
- The run is not remembered as `last`; `--save-profile` saves the choices
  without an input.
- `services/watching.py` looks at the folder every 5 seconds. Each model file,
  zip file or folder that two looks in a row find unchanged runs steps 8
  (input and `--exclude` only; a zip is unpacked into a temporary folder,
  removed after the drop) and 11 to 13 as a run of its own, then is moved to
  the folder's `sliced` or `failed` subfolder. Ctrl+C, or a request to
  terminate (`kill`, `systemctl stop`), stops watching with exit status 0; a
  drop being sliced at that moment is left where it is.
