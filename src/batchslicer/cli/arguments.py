"""Parse BatchSlicer's command-line options.

Every choice the interactive prompts ask for can be given on the command line.
``batchslicer setup`` has its own options for creating the configuration.
Choices left out are still prompted for, unless ``--no-prompt`` is given, in
which case a missing required choice is an error. This module only parses and
checks the shape of the options; it does not check that slicers, presets or
paths exist.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from batchslicer.backends.slicers import SLICERS
from batchslicer.cli.doctor import DoctorOptions
from batchslicer.cli.service import SERVICE_ACTIONS, ServiceOptions
from batchslicer.cli.setup import SetupOptions
from batchslicer.core.locations import user_config_file
from batchslicer.domain.options import (
    MAX_COPIES,
    MAX_JOBS,
    ORIENT_MODES,
    OrientMode,
    orient_mode,
    slot_rule,
)
from batchslicer.domain.profiles import LAST_RUN
from batchslicer.version import get_version_string

_SLICER_ALIASES = {
    "orca": "orca",
    "orcaslicer": "orca",
    "creality": "creality_print",
    "creality_print": "creality_print",
    "crealityprint": "creality_print",
    "bambu": "bambu_studio",
    "bambu_studio": "bambu_studio",
    "bambustudio": "bambu_studio",
}


@dataclass(frozen=True, slots=True)
class RunOptions:
    """The choices given on the command line; ``None`` means "ask the user"."""

    slicer: str | None = None
    """Configuration key of the chosen slicer."""

    printer: str | None = None
    filament: str | None = None
    more_filaments: tuple[str, ...] = ()
    """Filaments for slots 2, 3... (--filament given more than once)."""

    process: str | None = None
    input: Path | None = None
    output: Path | None = None
    no_prompt: bool = False
    list_presets: bool = False
    config: Path | None = None
    """Configuration file given with --config, if any."""

    profiles: tuple[str, ...] = ()
    """Saved profiles to start from (--profile, repeatable; "last" for --last).

    Several profiles slice the same input for every printer they name.
    """

    save_profile: str | None = None
    list_profiles: bool = False
    delete_profile: str | None = None
    orient: OrientMode | None = None
    allow_newer_files: bool | None = None
    jobs: int | None = None
    """How many models to slice at the same time."""

    exclude: tuple[str, ...] | None = None
    """Patterns of folders and files to leave out of a folder run (--exclude)."""

    copies: int | None = None
    """How many copies of a single model to slice (--copies)."""

    plates: bool | None = None
    """Slice each folder's models together on plates (--plates / --no-plates)."""

    thumbnails: bool | None = None
    """Add preview pictures to the G-code (--thumbnails / --no-thumbnails)."""

    send: str | None = None
    """Printer to send the G-code to (--send): a configured name or an address; ``""`` for --no-send."""

    start: bool = False
    """Start printing the sent G-code (--start); never remembered."""

    flat: bool | None = None
    """Put a batch's G-code in one folder (--flat / --no-flat)."""

    slots: tuple[tuple[str, str], ...] | None = None
    """Filament slots for loose models (--slot PATTERN=SLOT)."""

    loaded_filaments: bool | None = None
    """Match multi-colour projects to the filaments loaded in the --send printer (--loaded-filaments)."""

    dry_run: bool = False
    """Show what the run would do without slicing, writing or sending (--dry-run)."""

    watch: bool = False
    """Keep running and slice each model or folder put in the input folder (--watch)."""

    def has_choices(self) -> bool:
        """Return whether any run choice was given on the command line."""
        return any(
            value is not None
            for value in (
                self.slicer,
                self.printer,
                self.filament,
                self.process,
                self.input,
                self.output,
            )
        ) or bool(self.profiles)

    def has_target_choices(self) -> bool:
        """Return whether a slicer, preset or printer to send to was given on the command line."""
        return any(
            value is not None
            for value in (self.slicer, self.printer, self.filament, self.process)
        ) or bool(self.send)


def parse_arguments(
    argv: Sequence[str] | None = None,
) -> RunOptions | SetupOptions | DoctorOptions | ServiceOptions:
    """Return the options in ``argv`` (default: the process arguments).

    ``setup``, ``doctor`` or ``service`` as the first argument selects that
    command. Invalid options print a usage message and exit with status 2.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["setup"]:
        return _parse_setup(arguments[1:])
    if arguments[:1] == ["doctor"]:
        return _parse_doctor(arguments[1:])
    if arguments[:1] == ["service"]:
        return _parse_service(arguments[1:])
    parser = _parser()
    namespace = parser.parse_args(arguments)
    if namespace.dry_run and namespace.watch:
        parser.error("--dry-run shows one run; it cannot be combined with --watch.")
    if namespace.watch:
        if namespace.start:
            parser.error("--start cannot be used with --watch: prints are never started unattended.")
        if namespace.list_presets or namespace.list_profiles or namespace.delete_profile:
            parser.error("--watch cannot be combined with --list-presets, --list-profiles or --delete-profile.")
        if namespace.last:
            parser.error(
                "--last repeats a single run; save the choices with --save-profile and use "
                "--profile NAME --watch instead."
            )
    return RunOptions(
        slicer=namespace.slicer,
        printer=namespace.printer,
        filament=namespace.filament[0] if namespace.filament else None,
        more_filaments=tuple(namespace.filament[1:]) if namespace.filament else (),
        process=namespace.process,
        input=namespace.input,
        output=namespace.output,
        no_prompt=namespace.no_prompt,
        list_presets=namespace.list_presets,
        config=namespace.config,
        profiles=(LAST_RUN,) if namespace.last else tuple(namespace.profile or ()),
        save_profile=namespace.save_profile,
        list_profiles=namespace.list_profiles,
        delete_profile=namespace.delete_profile,
        orient=namespace.orient,
        allow_newer_files=namespace.allow_newer_files,
        jobs=namespace.jobs,
        exclude=tuple(namespace.exclude) if namespace.exclude else None,
        thumbnails=namespace.thumbnails,
        plates=namespace.plates,
        copies=namespace.copies,
        send=namespace.send,
        start=namespace.start,
        watch=namespace.watch,
        dry_run=namespace.dry_run,
        loaded_filaments=namespace.loaded_filaments,
        slots=tuple(namespace.slot) if namespace.slot else None,
        flat=namespace.flat,
    )


def _slot(value: str) -> tuple[str, str]:
    """Return a --slot value, PATTERN=SLOT, or explain what is wrong."""
    try:
        return slot_rule(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _copies(value: str) -> int:
    """Return a --copies value: a whole number from 1 to MAX_COPIES."""
    copies = int(value) if value.strip().isdigit() else 0
    if not 1 <= copies <= MAX_COPIES:
        raise argparse.ArgumentTypeError(f"must be a whole number from 1 to {MAX_COPIES}")
    return copies


def _orient(value: str) -> OrientMode:
    """Return an --orient value, or explain the choices."""
    try:
        return orient_mode(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _jobs(value: str) -> int:
    """Return a --jobs value: a whole number from 1 to MAX_JOBS."""
    try:
        jobs = int(value)
    except ValueError:
        jobs = 0
    if not 1 <= jobs <= MAX_JOBS:
        raise argparse.ArgumentTypeError(f"must be a whole number from 1 to {MAX_JOBS}: '{value}'")
    return jobs


def _service_parser() -> argparse.ArgumentParser:
    """Build the parser for ``batchslicer service`` (used for help and errors)."""
    parser = argparse.ArgumentParser(
        prog="batchslicer service",
        usage="batchslicer service {install,status,uninstall} [--name NAME] [run options]",
        description=(
            "Keep the watch folder running in the background: a systemd user service on "
            "Linux, a launchd agent on macOS, a scheduled task on Windows. 'install' takes the same options as a watch run, such as --profile, "
            "--input and --send, and adds --watch --no-prompt; it starts the service and "
            "shows its first lines of output. 'status' shows the installed services, "
            "'uninstall' stops and removes one."
        ),
        epilog=(
            "Example: batchslicer service install --profile k2-pla --input ~/drop "
            "--plates --send k2plus"
        ),
    )
    parser.add_argument("action", choices=SERVICE_ACTIONS, help="what to do")
    parser.add_argument(
        "--name",
        metavar="NAME",
        help=(
            "the service's name, to run several (default: watch; status without it shows "
            "every service)"
        ),
    )
    return parser


def _parse_service(arguments: Sequence[str]) -> ServiceOptions:
    """Return the options for ``batchslicer service``.

    Everything after the action except ``--name`` is passed to the service as
    run options; they are checked here as a watch run without prompts would be.
    """
    parser = _service_parser()
    if not arguments or arguments[0] in ("-h", "--help") or arguments[0] not in SERVICE_ACTIONS:
        parser.parse_args(arguments)  # prints help, or the error for a missing/unknown action
    action, rest = arguments[0], list(arguments[1:])
    if "-h" in rest or "--help" in rest:
        parser.print_help()
        raise SystemExit(0)
    name: str | None = None
    run_arguments: list[str] = []
    index = 0
    while index < len(rest):
        argument = rest[index]
        if argument == "--name":
            if index + 1 >= len(rest):
                parser.error("--name needs a name")
            name = rest[index + 1]
            index += 2
            continue
        if argument.startswith("--name="):
            name = argument.partition("=")[2]
        else:
            run_arguments.append(argument)
        index += 1
    if action != "install":
        if run_arguments:
            parser.error(f"'{action}' takes only --name, not: {' '.join(run_arguments)}")
        return ServiceOptions(action=action, name=name)
    run = parse_arguments([*run_arguments, "--watch", "--no-prompt"])
    if not isinstance(run, RunOptions) or not (run.profiles or run.slicer):
        parser.error(
            "install needs --profile NAME (or --slicer with --printer, --filament and "
            "--process), because the service cannot ask questions"
        )
    return ServiceOptions(action=action, name=name, run_arguments=tuple(run_arguments))


def _parse_doctor(arguments: Sequence[str]) -> DoctorOptions:
    """Return the options for ``batchslicer doctor``."""
    parser = argparse.ArgumentParser(
        prog="batchslicer doctor",
        description=(
            "Check BatchSlicer's configuration, folders and slicers, and report any "
            "problems. Include its output when reporting a problem."
        ),
    )
    parser.add_argument("--config", type=Path, metavar="PATH", help="configuration file to check")
    parser.add_argument(
        "--printer",
        action="append",
        default=[],
        metavar="NAME|ADDRESS",
        help=(
            "check only this printer: a name from the configuration's printers, or an "
            "address such as 192.168.1.50 or k2.local:4408. Repeat for several. Nothing "
            "else is checked."
        ),
    )
    parsed = parser.parse_args(arguments)
    return DoctorOptions(config=parsed.config, printers=tuple(parsed.printer))


def _parse_setup(arguments: Sequence[str]) -> SetupOptions:
    """Return the options for ``batchslicer setup``."""
    parser = argparse.ArgumentParser(
        prog="batchslicer setup",
        description=(
            "Find installed slicers and write BatchSlicer's configuration file. "
            "Each slicer must have been opened at least once."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        default=None,
        help=f"configuration file to write (default: {user_config_file()})",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="use the recommended copy of each slicer without asking",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing configuration file (a .bak backup is kept)",
    )
    namespace = parser.parse_args(arguments)
    return SetupOptions(
        config=namespace.config or user_config_file(),
        no_prompt=namespace.no_prompt,
        force=namespace.force,
    )


def _slicer_key(value: str) -> str:
    """Return the configuration key for a slicer name or alias."""
    key = _SLICER_ALIASES.get(value.strip().casefold().replace("-", "_").replace(" ", "_"))
    if key is None:
        names = ", ".join(sorted({"orca", "creality", "bambu"}))
        raise argparse.ArgumentTypeError(f"unknown slicer '{value}' (choose from {names})")
    return key


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    slicers = ", ".join(slicer.display_name for slicer in SLICERS)
    parser = argparse.ArgumentParser(
        prog="batchslicer",
        description=(
            f"Slice 3D models with {slicers}. Choices not given here are asked "
            "for interactively, unless --no-prompt is used. First time? Run "
            "'batchslicer setup' to find your slicers and create the configuration. "
            "Something wrong? 'batchslicer doctor' checks your setup. "
            "'batchslicer service' runs --watch in the background."
        ),
        epilog=(
            "Example: batchslicer --slicer creality --printer 'Creality K2 Plus 0.4 nozzle' "
            "--filament 'Generic PETG @Creality K2 Plus 0.4 nozzle' "
            "--process '0.20mm Standard @Creality K2 Plus 0.4 nozzle' "
            "--input incoming/brackets --output output/k2 --no-prompt"
        ),
    )
    parser.add_argument("--version", action="version", version=get_version_string())
    parser.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        help=(
            "configuration file (default: $BATCHSLICER_CONFIG, ./config/config.yaml, "
            "or ~/.config/batchslicer/config.yaml)"
        ),
    )
    parser.add_argument(
        "--slicer",
        type=_slicer_key,
        metavar="NAME",
        help="slicer to use: orca, creality or bambu",
    )
    parser.add_argument("--printer", metavar="NAME", help="printer preset name")
    parser.add_argument(
        "--filament",
        metavar="NAME",
        action="append",
        help=(
            "filament preset name. Repeat for the slots of a multi-colour 3MF project "
            "(slot 1, 2, ...); slots beyond those given use the last one"
        ),
    )
    parser.add_argument("--process", metavar="NAME", help="process (print settings) preset name")
    parser.add_argument(
        "--input",
        type=Path,
        metavar="PATH",
        help="model file, or folder whose models (including subfolders) are all sliced",
    )
    parser.add_argument(
        "--output",
        type=Path,
        metavar="PATH",
        help="output folder, created if needed (default: the configured output folder)",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="never ask questions; fail if a required choice is missing",
    )
    slicing = parser.add_argument_group("slicing")
    slicing.add_argument(
        "--orient",
        type=_orient,
        metavar="MODE",
        help=(
            f"use the slicer's auto-orient: {', '.join(ORIENT_MODES)}. 'retry' slices a model "
            "that fails once more with auto-orient (often fixes 'Failed slicing the model' "
            "or 'empty first layer'); "
            "'always' auto-orients every model, which may rotate parts saved the right way "
            "up (default: off)"
        ),
    )
    slicing.add_argument(
        "--allow-newer-files",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="let the slicer open 3MF projects saved by a newer slicer version",
    )
    slicing.add_argument(
        "--jobs",
        type=_jobs,
        metavar="N",
        help=(
            "slice N models at the same time (default: 1). Slicers are already "
            "multi-threaded, so try 2 first; each can use 1-2 GB of memory"
        ),
    )
    slicing.add_argument(
        "--exclude",
        action="append",
        metavar="PATTERN",
        help=(
            "leave out folders or files matching PATTERN when slicing a folder; repeat "
            "for several. Without '/' it matches any folder or file name ('Cura-*', "
            "'*_old.stl'), with '/' a path inside the folder ('kits/old'). Wildcards "
            "*, ? and [...] work; case is ignored"
        ),
    )
    slicing.add_argument(
        "--plates",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "when slicing a folder, slice the loose models (STL, OBJ, STEP) of each folder "
            "together: the slicer arranges them on as few plates as fit, giving one G-code "
            "file per plate. 3MF projects keep their own plates. Not for Creality Print "
            "(asked in interactive runs; default: off)"
        ),
    )
    slicing.add_argument(
        "--copies",
        type=_copies,
        metavar="N",
        help=(
            "slice N copies of a single model (STL, OBJ or STEP), arranged by the slicer "
            "on as many plates as needed. Not for folders, 3MF projects or Creality Print "
            "(asked in interactive runs; default: 1)"
        ),
    )
    slicing.add_argument(
        "--flat",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "when slicing a folder, put all the G-code straight into the run's folder (and "
            "one folder on the printer) instead of mirroring the input's subfolders; a name "
            "used twice gets its folder in front, such as kits-arm.gcode (default: off)"
        ),
    )
    slicing.add_argument(
        "--slot",
        type=_slot,
        action="append",
        metavar="PATTERN=SLOT",
        help=(
            "print STL, OBJ and STEP models matching PATTERN (matched like --exclude) with "
            "filament SLOT: a number (the --filament given in that place) or, with "
            "--loaded-filaments, a loaded filament such as 1B or external. Repeat for "
            "several; the first match wins, others use slot 1. With --plates a kit's "
            "parts print in their colours on the same plate"
        ),
    )
    slicing.add_argument(
        "--thumbnails",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "add preview pictures for printer screens to the G-code, drawn from the "
            "G-code itself (default: on; --no-thumbnails saves about a second per model)"
        ),
    )
    sending = parser.add_argument_group("sending to a printer (Klipper/Moonraker or OctoPrint)")
    choosing = sending.add_mutually_exclusive_group()
    choosing.add_argument(
        "--send",
        metavar="PRINTER",
        help=(
            "after slicing, upload the G-code to PRINTER: its address (192.168.1.50, "
            "k2.local:4408 or a full URL, reached through Moonraker on port 7125 if "
            "none is given) or a name from the configuration's 'printers' section, "
            "which may also be an OctoPrint server. A folder keeps its structure on "
            "the printer"
        ),
    )
    choosing.add_argument(
        "--no-send",
        dest="send",
        action="store_const",
        const="",
        help="don't send this run's G-code, even if the profile sends it",
    )
    sending.add_argument(
        "--loaded-filaments",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "slice each colour of a multi-colour 3MF project with the filament loaded in "
            "the --send printer's CFS that matches it best (colour and material), so the "
            "G-code and its preview pictures show the real colours. Creality printers with "
            "a CFS (asked in interactive runs; default: off)"
        ),
    )
    sending.add_argument(
        "--start",
        action="store_true",
        help=(
            "start printing once the G-code is on the printer; only for a single model "
            "that gives one G-code file. Never saved in profiles"
        ),
    )
    watching = parser.add_argument_group("watch folder")
    watching.add_argument(
        "--watch",
        action="store_true",
        help=(
            "keep running and slice each model file or folder put in the input folder "
            "(--input, or the configured incoming folder) once it has finished copying, "
            "then move it into that folder's 'sliced' or 'failed' subfolder. Works with "
            "--send (never --start). Stop with Ctrl+C"
        ),
    )
    profiles = parser.add_argument_group("profiles (saved choices)")
    starting = profiles.add_mutually_exclusive_group()
    starting.add_argument(
        "--profile",
        metavar="NAME",
        action="append",
        help=(
            "start from a saved profile; other options override its choices. Repeat "
            "to slice the same input for several printers"
        ),
    )
    starting.add_argument(
        "--last",
        action="store_true",
        help="repeat the last run (its choices are saved automatically)",
    )
    profiles.add_argument(
        "--save-profile",
        metavar="NAME",
        help="save this run's choices as a profile",
    )
    profiles.add_argument(
        "--list-profiles",
        action="store_true",
        help="list saved profiles, then exit",
    )
    profiles.add_argument(
        "--delete-profile",
        metavar="NAME",
        help="delete a saved profile, then exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "show what this run would do (models, plates, copies, filament slots and CFS "
            "matches, where results would go and where they would be sent) without "
            "slicing, writing or sending anything"
        ),
    )
    parser.add_argument(
        "--list-presets",
        action="store_true",
        help=(
            "list the printers for the slicer, or with --printer its filaments and "
            "processes, then exit"
        ),
    )
    return parser
