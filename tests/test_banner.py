from orcabatch.banner import create_banner


def test_banner_contains_name():

    banner = create_banner()

    assert "OrcaBatch" in banner


def test_banner_contains_version():

    banner = create_banner()

    assert "Version" in banner