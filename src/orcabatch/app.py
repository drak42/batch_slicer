"""Coordinate the OrcaBatch application startup lifecycle."""

from orcabatch.banner import get_banner
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
		results = EnvironmentService(config=config, logger=logger).run_checks()
	except (FileNotFoundError, KeyError, OSError, ValueError) as error:
		print(f"OrcaBatch startup failed: {error}")
		if logger is not None:
			logger.error("OrcaBatch startup failed: %s", error)
		return 1

	if not all(result.passed for result in results):
		logger.error("OrcaBatch startup failed environment verification.")
		print("OrcaBatch startup failed: environment verification failed.")
		return 1

	logger.info("OrcaBatch startup completed successfully.")
	print("OrcaBatch ready.")
	return 0
