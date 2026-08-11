from pathlib import Path

from orcabatch.core.config import Config


def test_load_configuration():

    config = Config(
        Path("config/config.yaml")
    )

    config.load()

    assert config.get(
        "application",
        "name"
    ) == "OrcaBatch"