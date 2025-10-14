import sys
from typing import Any, Dict, List

import requests
from requests.adapters import HTTPAdapter, Retry

from config import Config

_session = requests.Session()
_retries = Retry(
    total=3,
    backoff_factor=0.6,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["POST", "GET"]
)
_session.mount("http://", HTTPAdapter(max_retries=_retries))
_session.mount("https://", HTTPAdapter(max_retries=_retries))


class LovenseController:
    """Controller for Lovense devices via the LAN API."""

    def __init__(
        self,
        token: str | None = None,
        domain: str | None = None,
        port: int | None = None,
        secure: bool | None = None,
    ) -> None:
        self.token = token or ""
        self.domain = domain or "127.0.0.1"
        self.port = port or 20010
        self.secure = bool(secure) if secure is not None else False

        self.last_stroke_speed = 0
        self.last_relative_speed = 0
        self.last_depth_pos = 50

        self.min_user_speed = 10
        self.max_user_speed = 80
        self.min_depth = 0
        self.max_depth = 100

    # ------------------------------------------------------------------
    # Configuration helpers
    def set_connection(
        self,
        token: str | None = None,
        domain: str | None = None,
        port: int | None = None,
        secure: bool | None = None,
    ) -> None:
        if token is not None:
            self.token = token.strip()
        if domain is not None:
            self.domain = domain.strip() or "127.0.0.1"
        if port is not None:
            try:
                self.port = int(port)
            except (TypeError, ValueError):
                self.port = 20010
        if secure is not None:
            self.secure = bool(secure)

    def update_settings(self, min_speed: int, max_speed: int, min_depth: int, max_depth: int) -> None:
        self.min_user_speed = min_speed
        self.max_user_speed = max_speed
        self.min_depth = min_depth
        self.max_depth = max_depth

    def is_configured(self) -> bool:
        return bool(self.token)

    # ------------------------------------------------------------------
    # Movement helpers
    def _base_url(self) -> str:
        scheme = "https" if self.secure else "http"
        return f"{scheme}://{self.domain}:{self.port}"

    def _safe_percent(self, value: Any, default: float = 0.0) -> float:
        if value is None:
            return default
        try:
            value = float(value)
        except (TypeError, ValueError):
            return default
        return max(0.0, min(100.0, value))

    def _send_v2(self, commands: List[Dict[str, Any]]) -> bool:
        if not self.is_configured():
            return False
        payload = {"token": self.token, "commands": commands}
        try:
            resp = _session.post(
                f"{self._base_url()}/api/lan/v2/command",
                json=payload,
                timeout=(Config.CONNECT_TIMEOUT, Config.READ_TIMEOUT),
            )
            if 200 <= resp.status_code < 300:
                return True
            if resp.status_code in {404, 405}:
                return False
        except requests.exceptions.RequestException as exc:
            print(f"[LOVENSE ERROR] LAN v2 command failed: {exc}", file=sys.stderr)
        return False

    def _send_legacy(self, command: str) -> None:
        if not self.is_configured():
            return
        params = {"token": self.token, "cmd": command}
        try:
            _session.get(
                f"{self._base_url()}/command",
                params=params,
                timeout=(Config.CONNECT_TIMEOUT, Config.READ_TIMEOUT),
            )
        except requests.exceptions.RequestException as exc:
            print(f"[LOVENSE ERROR] Legacy command failed: {exc}", file=sys.stderr)

    def move(self, speed: Any, depth: Any, stroke_range: Any) -> None:
        if not self.is_configured():
            return

        if speed is not None and speed == 0:
            self.stop()
            return

        speed_pct = self._safe_percent(speed, self.last_relative_speed)
        depth_pct = self._safe_percent(depth, self.last_depth_pos)
        stroke_pct = self._safe_percent(stroke_range, 50.0)

        vibration_level = int(round((speed_pct / 100.0) * 20))
        vibration_level = max(0, min(20, vibration_level))

        commands = [
            {"type": "vibrate", "value": vibration_level},
        ]

        if stroke_pct > 0:
            thrust_level = int(round((stroke_pct / 100.0) * 20))
            thrust_level = max(0, min(20, thrust_level))
            commands.append({
                "type": "thrust",
                "value": thrust_level,
                "position": int(round(depth_pct)),
            })

        if not self._send_v2(commands):
            self._send_legacy(f"Vibrate:{vibration_level}")
            if len(commands) > 1:
                thrust_cmd = commands[1]
                self._send_legacy(
                    f"Thrust:{thrust_cmd['value']}:{thrust_cmd['position']}"
                )

        self.last_relative_speed = speed_pct
        self.last_depth_pos = depth_pct
        self.last_stroke_speed = speed_pct

    def stop(self) -> None:
        if not self.is_configured():
            return
        if not self._send_v2([{ "type": "stop" }]):
            self._send_legacy("Stop")
        self.last_stroke_speed = 0
        self.last_relative_speed = 0

    def nudge(self, *_, **__) -> float | None:
        print("[LOVENSE] Nudge not supported for this device.")
        return None

    def get_position_mm(self) -> float | None:
        return None

    def mm_to_percent(self, value: Any) -> int:
        return int(round(self._safe_percent(value)))

*** End of File
