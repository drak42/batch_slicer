"""Describe the slicers BatchSlicer can drive and which of them are configured.

OrcaSlicer, Bambu Studio and Creality Print share one command-line interface
(Bambu Studio is the common ancestor), so a single backend drives all three.
This module records the per-slicer differences: the configuration section that
holds its paths, extra launch and slice arguments, CLI options it does not
support, and whether its presets can be listed.
It does not run slicers, check that configured paths exist, or prompt users.
"""

from dataclasses import dataclass

from batchslicer.core.config import Config


@dataclass(frozen=True, slots=True)
class SlicerDefinition:
    """Describe one supported slicer and how its CLI differs from OrcaSlicer."""

    key: str
    """Configuration section holding ``executable`` and ``datadir``."""

    display_name: str
    launch_arguments: tuple[str, ...] = ()
    """Arguments placed straight after the executable, before any option."""

    unsupported_options: frozenset[str] = frozenset()

    slice_arguments: tuple[str, ...] = ()
    """Arguments every slice command needs for this slicer to write G-code."""

    app_config_name: str | None = None
    """Settings file in the data directory used to list presets; None if preset
    selection is not yet supported for this slicer."""

    resolves_inherits_from: tuple[int, ...] | None = None
    """Version from which the slicer's CLI looks up a settings file's ``inherits``
    itself (and fails if it cannot find it); None if it never does."""

    @property
    def supports_preset_selection(self) -> bool:
        """Return whether BatchSlicer can list and resolve this slicer's presets."""
        return self.app_config_name is not None

    def supports(self, option: str) -> bool:
        """Return whether this slicer's CLI accepts ``option``."""
        return option not in self.unsupported_options


ORCASLICER = SlicerDefinition(
    key="orca",
    display_name="OrcaSlicer",
    app_config_name="OrcaSlicer.conf",
    # OrcaSlicer 2.5 resolves "inherits" against its own loaded presets.
    resolves_inherits_from=(2, 5),
)

BAMBU_STUDIO = SlicerDefinition(
    key="bambu_studio",
    display_name="Bambu Studio",
    app_config_name="BambuStudio.conf",
)

CREALITY_PRINT = SlicerDefinition(
    key="creality_print",
    display_name="Creality Print",
    # Without --cli, Creality Print ignores command-line options and opens its window.
    launch_arguments=("--cli",),
    # Checked against Creality Print 7.3 `--cli --help`.
    unsupported_options=frozenset(
        {"--orient", "--arrange", "--skip-modified-gcodes", "--export-settings"}
    ),
    # Without this, Creality Print reports success but writes no G-code.
    slice_arguments=("--need-gcode-file",),
    app_config_name="Creality.conf",
)

SLICERS: tuple[SlicerDefinition, ...] = (ORCASLICER, CREALITY_PRINT, BAMBU_STUDIO)
"""Every supported slicer, in the order they are offered to the user."""


def get_slicer(key: str) -> SlicerDefinition:
    """Return the slicer whose configuration section is ``key``."""
    for slicer in SLICERS:
        if slicer.key == key:
            return slicer
    raise KeyError(f"Unknown slicer: {key}")


def is_configured(slicer: SlicerDefinition, config: Config) -> bool:
    """Return whether ``config`` gives ``slicer`` a non-empty executable and data directory."""
    for setting in ("executable", "datadir"):
        if not config.has(slicer.key, setting):
            return False
        value = config.get(slicer.key, setting)
        if not isinstance(value, str) or not value:
            return False
    return True
