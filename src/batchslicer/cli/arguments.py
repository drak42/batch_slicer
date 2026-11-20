"""Parse BatchSlicer's command-line options.

Every choice the interactive prompts ask for can be given on the command line.
``batchslicer setup`` has its own options for creating the configuration.
Choices left out are still prompted for, unless ``--no-prompt`` is given, in
which case a missing required choice is an error. This module only parses and
checks the shape of the options; it does not check that slicers, presets or
paths exist.
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import sys

from batchslicer.backends.slicers import SLICERS
from batchslicer.cli.setup import SetupOptions
from batchslicer.core.locations import user_config_file
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


def parse_arguments(argv: Sequence[str] | None = None) -> RunOptions | SetupOptions:
    """Return the options in ``argv`` (default: the process arguments).

    ``setup`` as the first argument selects the setup command. Invalid options
    print a usage message and exit with status 2.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["setup"]:
        return _parse_setup(arguments[1:])
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
    )


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
            "'batchslicer setup' to find your slicers and create the configuration."
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
    parser.add_argument(
        "--list-presets",
        action="store_true",
        help=(
            "list the printers for the slicer, or with --printer its filaments and "
            "processes, then exit"
        ),
    )
    return parser
