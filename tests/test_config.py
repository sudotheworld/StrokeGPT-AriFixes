from config import Config


def test_defaults():
    # Default port should be 5000 if not overridden
    assert Config.PORT == 5000
    # Host should be defined and non-empty
    assert Config.HOST