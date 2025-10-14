import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from config import Config


def test_defaults():
    assert Config.PORT == 5000
    assert Config.HOST
    assert Config.DEVICE_TYPE in {"handy", "lovense"}
    assert isinstance(Config.LOVENSE_SECURE, bool)
    assert Config.LOVENSE_PORT == 20010
