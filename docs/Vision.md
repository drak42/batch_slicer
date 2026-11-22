# Vision

## Why BatchSlicer exists

Slicing is the step between a 3D model and a print, and it is repetitive: the
same printer, the same filament, the same settings, over and over, one model at
a time in a slicer's window. BatchSlicer removes that friction. It drives the
slicer you already use, with the presets you already tuned, and turns a folder
of models into ready-to-print G-code without clicking through each one.

## Who it is for

- **Makers** who print regularly and want to slice a whole project (a kit, an
  RC car, a set of brackets) in one go.
- **Small print farms and businesses** that slice the same parts for several
  printers and want the result to be repeatable and unattended.
- **Tinkerers and scripters** who want slicing as a dependable step in their own
  automation (scheduled jobs, watch folders, pipelines).

## What "good" looks like

- **It respects the user's slicer.** BatchSlicer uses OrcaSlicer, Creality Print
  and Bambu Studio as they are, with the user's own presets, and never changes
  their settings. If the slicer would accept a job, BatchSlicer should slice it
  the same way.
- **It is trustworthy.** Results are never silently wrong or overwritten; every
  job records the exact presets used; failures say why, in the slicer's own
  words; nothing is left lying around in unexpected places.
- **It is easy the first time and fast every time after.** A first run asks a
  few clear questions; later runs repeat a saved profile with one command.
- **It keeps working.** Slicers change their command lines between releases;
  BatchSlicer is tested against their newest releases every week.

## Where it is going

BatchSlicer started as a batch slicing tool for OrcaSlicer. The long-term goal
is a dependable print automation platform: slicing for every printer in a
workshop, reporting what each job will cost in time and material, arranging
parts onto plates, and handing finished G-code to the printers, while staying
understandable, extensible and enjoyable to maintain.

Much of that is in place: it slices for several printers at once, reports
print time and filament, puts a folder's parts together on plates, adds
preview pictures for printer screens, and sends G-code to Klipper and
OctoPrint printers.
Next come copies on plates, multi-material printers, watch folders and other
kinds of printer connection.

See [Roadmap](Roadmap.md) for the concrete plan and
[Architecture](Architecture.md) for how the software is built.

## Principles

- Every feature must provide measurable value to someone printing.
- Every release must improve reliability, usability, or maintainability.
- Prefer doing a few things dependably over many things approximately.
