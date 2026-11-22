# Startup and run sequence

What happens, in order, when `batchslicer` runs. Each step that makes a choice
takes it from the command line or a profile when given, and otherwise asks,
unless `--no-prompt` is used (then a missing choice is an error). Code lives in
`src/batchslicer/app.py` unless noted.

## Commands

`batchslicer setup` (`cli/setup.py`) and `batchslicer doctor`
(`cli/doctor.py`) are separate commands chosen by the first argument; they do
not slice. Everything below describes a normal run.

## Sequence

1. **Parse options** (`cli/arguments.py`). Invalid options stop with exit
   status 2.
2. **Show the banner**, except for listing commands (`--list-presets`,
   `--list-profiles`, `--delete-profile`).
3. **Load the configuration** (`core/config.py`): `--config`, then
   `BATCHSLICER_CONFIG`, then `./config/config.yaml`, then
   `~/.config/batchslicer/config.yaml`.
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
8. **Choose what to slice** (`cli/file_prompt.py`), leave out models matching
   `--exclude` (`exclude_models`), and **choose the output folder**
   (`cli/output_prompt.py`). For a folder with loose models to share plates,
   an interactive run without a profile, `--plates` or `--no-plates` asks
   whether to slice each folder's models together; `--plates` is refused for
   Creality Print. For a single STL, OBJ or STEP model it asks how many copies
   to make (`--copies`); copies are refused for folders, 3MF projects and
   Creality Print (a profile's copies are left out with a note). An interactive run without a profile, `--send`
   or `--no-send` then asks whether to send the G-code
   (`cli/send_prompt.py`), when a printer is configured or the last run sent
   to one. `--start` is refused here unless every target
   sends and a single model was chosen, and each printer to send to must
   answer (`infrastructure/moonraker.py`), so nothing is sliced for a
   printer that is off.
9. **Remember the run** as the profile `last`, and as `--save-profile` if given.
10. **Check the slicing options** (`--orient`, `--allow-newer-files`,
    `--jobs`, possibly from a profile) against each chosen slicer, and show
    them with the presets.
11. **Slice** (`services/slicing.py`, `backends/orca.py`): for each target, a
    job folder (one model) or batch folder (a folder of models) is created, the
    resolved presets are written into it, and the slicer runs inside each
    model's folder, up to `--jobs` at a time. With `--plates` the loose models
    of each folder are one job (`--arrange 1`, named after the folder), sliced
    one by one if that fails. With `--orient retry` a failed
    model is sliced once more with auto-orient. The slicer's status files are
    read and removed; folders of failed or interrupted models are removed.
    Preview pictures are drawn from each G-code file and inserted into it
    (`services/thumbnails.py`) unless `--no-thumbnails` is given.
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
