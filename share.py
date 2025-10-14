"""Helper script to share a local StrokeGPT session over the internet.

This script launches the main Flask application and then exposes it via an
ngrok tunnel.  It is intended for casual "invite a friend" sessions where the
host wants to keep their computer running the core app but make the web UI
reachable from anywhere.

Usage::

    python share.py --port 5000 --pin 1234

Command line options let you pick the local port, require a room PIN, and
control whether a browser is opened automatically once the tunnel is ready.
The script prints the tunnel URL so you can share it with other participants.

Requirements:
    * The core StrokeGPT dependencies.
    * The ``pyngrok`` package (listed in ``requirements.txt``).
    * An optional ``NGROK_AUTHTOKEN`` environment variable for improved tunnel
      stability.  The free plan works, but ngrok may limit uptime or
      concurrent connections without an auth token.

This module deliberately avoids try/except around imports to comply with the
repository's contribution guidelines.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser

import requests
from pyngrok import ngrok


def parse_args() -> argparse.Namespace:
    """Return parsed command-line arguments."""

    parser = argparse.ArgumentParser(description="Share StrokeGPT over ngrok")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "5000")),
        help="Local port where StrokeGPT will listen (default: 5000)",
    )
    parser.add_argument(
        "--pin",
        type=str,
        default=os.environ.get("ROOM_PIN", ""),
        help="Optional room PIN required to load the UI",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically open the local or public URL in a browser",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=45,
        help="Seconds to wait for the health check before giving up",
    )
    return parser.parse_args()


def wait_for_healthcheck(url: str, timeout: int) -> bool:
    """Poll the /health endpoint until it succeeds or timeout expires."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = requests.get(url, timeout=3)
            if response.ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def start_app_subprocess(port: int, pin: str) -> subprocess.Popen[bytes]:
    """Launch the Flask app in a background subprocess."""

    env = os.environ.copy()
    env.setdefault("FLASK_ENV", "production")
    env["PORT"] = str(port)
    if pin:
        env["ROOM_PIN"] = pin

    python = sys.executable
    return subprocess.Popen([python, "app.py"], env=env)


def open_urls(local_url: str, public_url: str | None, *, pin: str, skip_browser: bool) -> None:
    """Open the local and public URLs in the default browser when allowed."""

    if skip_browser:
        return

    webbrowser.open(local_url)
    if public_url:
        url_to_open = f"{public_url}/?pin={pin}" if pin else public_url
        threading.Thread(target=webbrowser.open, args=(url_to_open,), daemon=True).start()


def build_banner(local_url: str, public_url: str | None, pin: str) -> str:
    """Format a banner showing the important connection details."""

    lines = [
        "\n" + "=" * 70,
        "🚀 StrokeGPT Share Mode",
        "=" * 70,
        "",
        "Local access:",
        f"  → {local_url}",
    ]

    if public_url:
        display_url = f"{public_url}/?pin={pin}" if pin else public_url
        lines.extend(
            [
                "",
                "Public access:",
                f"  → {display_url}",
                "",
                "Share this address with your friends so they can join your session.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Public access:",
                "  (ngrok tunnel is still starting; check the logs for status)",
            ]
        )

    if pin:
        lines.extend(
            [
                "",
                "Room PIN:",
                f"  → {pin}",
            ]
        )

    lines.extend(["", "Press Ctrl+C to stop sharing.", "", "=" * 70 + "\n"])
    return "\n".join(lines)


def main() -> None:
    args = parse_args()

    # If the user supplied an auth token, configure ngrok before connecting.
    authtoken = os.environ.get("NGROK_AUTHTOKEN")
    if authtoken:
        ngrok.set_auth_token(authtoken)

    flask_process = start_app_subprocess(args.port, args.pin)

    def _terminate_child(signum: int, frame: object) -> None:
        del frame  # unused
        ngrok.kill()
        if flask_process.poll() is None:
            flask_process.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, _terminate_child)
    signal.signal(signal.SIGTERM, _terminate_child)

    health_url = f"http://127.0.0.1:{args.port}/health"
    if not wait_for_healthcheck(health_url, args.timeout):
        print("⚠️  StrokeGPT did not become ready within the timeout window.")
        _terminate_child(signal.SIGTERM, None)

    tunnel = ngrok.connect(args.port, proto="http")
    public_url = tunnel.public_url
    local_url = f"http://127.0.0.1:{args.port}"

    print(build_banner(local_url, public_url, args.pin))
    open_urls(local_url, public_url, pin=args.pin, skip_browser=args.no_browser)

    try:
        flask_process.wait()
    finally:
        ngrok.disconnect(public_url)
        ngrok.kill()


if __name__ == "__main__":
    main()
