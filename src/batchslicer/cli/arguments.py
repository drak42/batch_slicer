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
from batchslicer.cli.setup import SetupOptions
from batchslicer.core.locations import user_config_file
from batchslicer.domain.options import MAX_JOBS, ORIENT_MODES, OrientMode, orient_mode
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

    send: str | None = None
    """Printer to send the G-code to (--send): a configured name or an address; ``""`` for --no-send."""

    start: bool = False
    """Start printing the sent G-code (--start); never remembered."""

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
) -> RunOptions | SetupOptions | DoctorOptions:
    """Return the options in ``argv`` (default: the process arguments).

    ``setup`` or ``doctor`` as the first argument selects that command. Invalid options
    print a usage message and exit with status 2.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["setup"]:
        return _parse_setup(arguments[1:])
    if arguments[:1] == ["doctor"]:
        return _parse_doctor(arguments[1:])
    namespace = _parser().parse_args(arguments)
    return RunOptions(
        slicer=namespace.slicer,
        printer=namespace.printer,
        filament=namespace.filament,
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
        send=namespace.send,
        start=namespace.start,
    )


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
    return DoctorOptions(config=parser.parse_args(arguments).config)


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
            "Something wrong? 'batchslicer doctor' checks your setup."
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
    parser.add_argument("--filament", metavar="NAME", help="filament preset name")
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
    sending = parser.add_argument_group("sending to a printer (Klipper/Moonraker)")
    choosing = sending.add_mutually_exclusive_group()
    choosing.add_argument(
        "--send",
        metavar="PRINTER",
        help=(
            "after slicing, upload the G-code to PRINTER: its address (192.168.1.50, "
            "k2.local:4408 or a full URL; port 7125 if none is given) or a name from "
            "the configuration's 'printers' section. A folder keeps its structure on "
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
        "--start",
        action="store_true",
        help=(
            "start printing once the G-code is on the printer; only for a single model "
            "that gives one G-code file. Never saved in profiles"
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
        "--list-presets",
        action="store_true",
        help=(
            "list the printers for the slicer, or with --printer its filaments and "
            "processes, then exit"
        ),
    )
    return parser
