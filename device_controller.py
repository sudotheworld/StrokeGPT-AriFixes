from __future__ import annotations

from typing import Any, Optional

from config import Config
from handy_controller import HandyController
from lovense_controller import LovenseController


class DeviceController:
    """Router that normalizes access to supported stroker devices."""

    SUPPORTED_TYPES = {"handy", "lovense"}

    def __init__(self, settings: Any) -> None:
        handy_key = getattr(settings, "handy_key", None) or Config.HANDY_KEY
        self.handy = HandyController(handy_key)

        lovense_token = getattr(settings, "lovense_token", None) or Config.LOVENSE_TOKEN
        lovense_domain = getattr(settings, "lovense_domain", None) or Config.LOVENSE_DOMAIN
        lovense_port = getattr(settings, "lovense_port", None) or Config.LOVENSE_PORT
        lovense_secure = getattr(settings, "lovense_secure", None)
        if lovense_secure is None:
            lovense_secure = Config.LOVENSE_SECURE
        self.lovense = LovenseController(
            token=lovense_token,
            domain=lovense_domain,
            port=lovense_port,
            secure=lovense_secure,
        )

        requested_type = getattr(settings, "device_type", None) or Config.DEVICE_TYPE
        self.device_type = self._normalize_type(requested_type)
        self.update_settings(
            getattr(settings, "min_speed", 10),
            getattr(settings, "max_speed", 80),
            getattr(settings, "min_depth", 5),
            getattr(settings, "max_depth", 100),
        )

    # ------------------------------------------------------------------
    # Helpers
    def _normalize_type(self, value: Optional[str]) -> str:
        if not value:
            return "handy"
        value = value.lower()
        if value not in self.SUPPORTED_TYPES:
            return "handy"
        return value

    @property
    def controller(self):
        return self.handy if self.device_type == "handy" else self.lovense

    # ------------------------------------------------------------------
    # Public API mirrored from HandyController
    def set_device_type(self, value: str) -> None:
        self.device_type = self._normalize_type(value)

    def set_api_key(self, key: str) -> None:
        self.handy.set_api_key(key)

    def set_lovense_connection(
        self,
        *,
        token: Optional[str] = None,
        domain: Optional[str] = None,
        port: Optional[int] = None,
        secure: Optional[bool] = None,
    ) -> None:
        self.lovense.set_connection(token=token, domain=domain, port=port, secure=secure)

    def update_settings(self, min_speed: int, max_speed: int, min_depth: int, max_depth: int) -> None:
        self.handy.update_settings(min_speed, max_speed, min_depth, max_depth)
        self.lovense.update_settings(min_speed, max_speed, min_depth, max_depth)

    def move(self, speed: Any, depth: Any, stroke_range: Any) -> None:
        self.controller.move(speed, depth, stroke_range)

    def stop(self) -> None:
        self.controller.stop()

    def nudge(self, *args, **kwargs):
        if self.device_type != "handy":
            return None
        return self.handy.nudge(*args, **kwargs)

    def get_position_mm(self):
        if self.device_type != "handy":
            return None
        return self.handy.get_position_mm()

    def mm_to_percent(self, value):
        if self.device_type == "handy":
            return self.handy.mm_to_percent(value)
        return self.lovense.mm_to_percent(value)

    def is_configured(self) -> bool:
        if self.device_type == "handy":
            return bool(self.handy.handy_key)
        return self.lovense.is_configured()

    def supports_calibration(self) -> bool:
        return self.device_type == "handy"

    # Convenience accessors ------------------------------------------------
    @property
    def last_relative_speed(self):
        return self.controller.last_relative_speed

    @property
    def last_depth_pos(self):
        return self.controller.last_depth_pos

    @property
    def last_stroke_speed(self):
        return self.controller.last_stroke_speed

    @property
    def handy_key(self) -> str:
        return self.handy.handy_key

    def get_lovense_config(self) -> dict:
        return {
            "token": self.lovense.token,
            "domain": self.lovense.domain,
            "port": self.lovense.port,
            "secure": self.lovense.secure,
        }
*** End of File
