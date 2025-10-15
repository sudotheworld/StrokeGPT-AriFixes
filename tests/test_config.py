from config import Config


def test_defaults_present():
    assert Config.PORT == 5000
    assert Config.HOST
    assert Config.IMAGE_API_URL.endswith("/api/image")
    assert Config.IMAGE_WORKER_COUNT >= 1
    assert Config.IMAGE_WIDTH > 0
    assert Config.IMAGE_HEIGHT > 0
