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
   `--list-presets` stops here after printing names.
8. **Choose what to slice** (`cli/file_prompt.py`) and **the output folder**
   (`cli/output_prompt.py`).
9. **Remember the run** as the profile `last`, and as `--save-profile` if given.
10. **Slice** (`services/slicing.py`, `backends/orca.py`): for each target, a
    job folder (one model) or batch folder (a folder of models) is created, the
    resolved presets are written into it, and the slicer runs inside it.
11. **Report** results and exit: 0 success, 1 failure, 130 interrupted.

Failures before slicing stop the run with a message naming the problem.
Ctrl+C at any point stops cleanly (a batch keeps finished models). Unexpected
errors are reported in one line with details in the log.
