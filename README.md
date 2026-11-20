# batch_slicer
STL Batch Slicer

BatchSlicer

BatchSlicer exists to remove friction from the entire 3D printing workflow through reliable, maintainable, and thoughtfully engineered automation.

Its purpose is not simply to batch slice STL files.

Its purpose is to become a dependable automation platform that helps makers, professionals, and print farms spend less time managing printers and more time creating.

Every feature must provide measurable value.

Every release must improve reliability, usability, or maintainability.

The software should remain understandable, extensible, and enjoyable to work on for many years.

## Usage

Install into a virtual environment, then set the slicers you use in
`config/config.yaml` (each needs its `executable` and `datadir`):

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Run interactively; BatchSlicer asks for the slicer, printer, filament, process,
what to slice (one file or a folder and its subfolders) and the output folder:

```bash
.venv/bin/batchslicer
```

Or give any of the choices on the command line. Anything left out is still
asked for, unless `--no-prompt` is used (for scripts and scheduled runs):

```bash
.venv/bin/batchslicer --slicer creality \
  --printer "Creality K2 Plus 0.4 nozzle" \
  --filament "Generic PETG @Creality K2 Plus 0.4 nozzle" \
  --process "0.20mm Standard @Creality K2 Plus 0.4 nozzle" \
  --input incoming/brackets --output output/k2 --no-prompt
```

Find the exact preset names with `--list-presets`:

```bash
.venv/bin/batchslicer --slicer creality --list-presets
.venv/bin/batchslicer --slicer creality --printer "Creality K2 Plus 0.4 nozzle" --list-presets
```

`--slicer` accepts `orca`, `creality` or `bambu`. Preset names match ignoring
case. `--input` takes a model file (`.stl`, `.3mf`, `.obj`) or a folder;
`--output` is created if needed and defaults to the configured output folder.
The exit status is 0 when everything sliced and 1 otherwise. Run `--help` for
all options. Run from the project folder, since `config/config.yaml` and the
runtime folders are found relative to it.

Run the tests with `.venv/bin/pytest`.
