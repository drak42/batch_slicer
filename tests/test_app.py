from orcabatch.app import Application


def test_application_creation():

    app = Application()

    assert app is not None