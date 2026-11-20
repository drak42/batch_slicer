"""Coordinate the OrcaBatch application startup lifecycle.

Startup shows the banner, configures logging, loads configuration, asks the
user which slicer to use, and verifies the environment for that slicer. The
application does not proceed until a configured slicer has been chosen.
"""

from orcabatch.backends.slicers import SLICERS, is_configured
from orcabatch.banner import get_banner
from orcabatch.cli.slicer_prompt import SlicerSelectionError, prompt_for_slicer
from orcabatch.core.config import get_config
from orcabatch.core.environment import EnvironmentService
from orcabatch.core.logging import configure_logging


def main() -> int:
    """Start OrcaBatch and return a process exit status."""
    print(get_banner(), end="")
    logger = None

    try:
        logger = configure_logging()
        config = get_config()
        configured = [slicer for slicer in SLICERS if is_configured(slicer, config)]
        slicer = prompt_for_slicer(SLICERS, configured)
        logger.info("Selected slicer: %s", slicer.display_name)
        results = EnvironmentService(
            config=config,
            logger=logger,
            slicer=slicer,
        ).run_checks()
    except (SlicerSelectionError, FileNotFoundError, KeyError, OSError, ValueError) as error:
        print(f"OrcaBatch startup failed: {error}")
        if logger is not None:
            logger.error("OrcaBatch startup failed: %s", error)
        return 1

    failed = [result for result in results if not result.passed]
    if failed:
        logger.error("OrcaBatch startup failed environment verification.")
        print("OrcaBatch startup failed: environment verification failed.")
        for result in failed:
            print(f"  - {result.name}: {result.message}")
        return 1

    logger.info("OrcaBatch startup completed successfully using %s.", slicer.display_name)
    print(f"OrcaBatch ready. Slicer: {slicer.display_name}.")
    return 0
