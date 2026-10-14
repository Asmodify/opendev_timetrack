"""Desktop helper for the company time tracker.

It tells the server, about once a minute, whether this computer is being used
(keyboard or mouse input in the last few minutes). The server opens a session
when work starts and closes it after the idle timeout. Nothing else is sent:
no keystrokes, screenshots, window titles, apps or websites.

Usage:
    timetrack-agent pair --server https://time.example.com --code ABCD-EF12-3456
    timetrack-agent run
    timetrack-agent install-autostart
    timetrack-agent status
    timetrack-agent unpair
Only the Python standard library is used, so it packages cleanly with PyInstaller.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

APP = "OpenDevTimeTrack"
INTERVAL_SECONDS = 60
ACTIVE_IF_INPUT_WITHIN = 5 * 60  # seconds without input before this computer counts as idle

log = logging.getLogger("timetrack-agent")


# ---------- config ----------

def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / APP
    path.mkdir(parents=True, exist_ok=True)
    return path


CONFIG = config_dir() / "config.json"


def load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    CONFIG.write_text(json.dumps(cfg, indent=2))
    try:
        os.chmod(CONFIG, 0o600)  # the device token is a credential
    except OSError:
        pass


# ---------- idle detection ----------

def idle_seconds() -> int:
    """Seconds since the last keyboard or mouse input on this computer."""
    try:
        if sys.platform == "win32":
            import ctypes

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            info = LASTINPUTINFO()
            info.cbSize = ctypes.sizeof(info)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
            return max(0, (ctypes.windll.kernel32.GetTickCount() - info.dwTime) // 1000)
        if sys.platform == "darwin":
            out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True, timeout=5).stdout
            for line in out.splitlines():
                if "HIDIdleTime" in line:
                    return int(line.split("=")[-1].strip()) // 1_000_000_000
        else:
            out = subprocess.run(["xprintidle"], capture_output=True, text=True, timeout=5).stdout.strip()
            if out:
                return int(out) // 1000
    except Exception as exc:  # noqa: BLE001 - never crash the loop over idle detection
        log.debug("idle detection failed: %s", exc)
    return 0  # unknown: treat as active rather than silently dropping hours


# ---------- server calls ----------

def call(server: str, path: str, body: dict, token: str | None = None, timeout: int = 15) -> dict:
    req = urllib.request.Request(server.rstrip("/") + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as err:
        try:
            detail = json.loads(err.read()).get("detail", "")
        except ValueError:
            detail = ""
        raise ServerError(err.code, detail or f"HTTP {err.code}") from None


class ServerError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status


# ---------- commands ----------

def cmd_pair(args) -> int:
    name = args.name or socket.gethostname()
    plat = f"{platform.system()} {platform.release()}"
    try:
        res = call(args.server, "/api/agent/pair", {"code": args.code, "device_name": name, "platform": plat})
    except (ServerError, OSError) as exc:
        print(f"Could not link this computer: {exc}")
        return 1
    save_config({"server": args.server.rstrip("/"), "token": res["token"], "device_name": name})
    print(f"Linked '{name}' to {res['user_name']}. Run 'timetrack-agent install-autostart' to start it at login.")
    return 0


def cmd_unpair(_args) -> int:
    if CONFIG.exists():
        CONFIG.unlink()
    print("This computer is unlinked here. Also remove it under 'My computers' in the dashboard.")
    return 0


def cmd_status(_args) -> int:
    cfg = load_config()
    if not cfg.get("token"):
        print("Not linked. Run: timetrack-agent pair --server URL --code CODE")
        return 1
    print(f"Linked as '{cfg.get('device_name')}' to {cfg['server']}")
    print(f"Idle for {idle_seconds()} s (counts as working if under {ACTIVE_IF_INPUT_WITHIN} s)")
    return 0


def cmd_run(_args) -> int:
    cfg = load_config()
    if not cfg.get("token"):
        print("Not linked. Run: timetrack-agent pair --server URL --code CODE")
        return 1
    server, token = cfg["server"], cfg["token"]
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, stop)  # Windows console close / logoff

    backoff = INTERVAL_SECONDS
    last_state = None
    log.info("Running. Reporting to %s every %s s.", server, INTERVAL_SECONDS)
    while not stopping:
        idle = idle_seconds()
        try:
            res = call(server, "/api/agent/heartbeat", {"active": idle < ACTIVE_IF_INPUT_WITHIN, "idle_seconds": idle}, token)
            backoff = INTERVAL_SECONDS
            state = (res.get("state"), res.get("location"))
            if state != last_state:
                log.info("State: %s%s", res.get("state"), f" ({res['location']})" if res.get("location") else "")
                last_state = state
        except ServerError as exc:
            if exc.status == 401:
                log.error("%s", exc)
                return 2
            if exc.status == 403:
                if last_state != "consent":
                    log.warning("%s", exc)
                    last_state = "consent"
            else:
                log.warning("Server error: %s", exc)
        except OSError as exc:
            # Offline: the server closes the session where activity stopped; we pick up again when back.
            log.warning("Can't reach the server (%s). Retrying.", exc)
            backoff = min(backoff * 2, 600)
        slept = 0
        wait = backoff if backoff > INTERVAL_SECONDS else INTERVAL_SECONDS
        while slept < wait and not stopping:
            time.sleep(1)
            slept += 1
    try:
        call(server, "/api/agent/stop", {"reason": "shutdown"}, token, timeout=5)
    except Exception:  # noqa: BLE001 - best effort; the server times the session out anyway
        pass
    log.info("Stopped.")
    return 0


def cmd_install_autostart(_args) -> int:
    exe = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" "{Path(__file__).resolve()}"'
    if sys.platform == "win32":
        startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        target = startup / "OpenDevTimeTrack.vbs"
        cmd = (f'"{exe}" run' if getattr(sys, "frozen", False) else f"{exe} run").replace('"', '""')
        # A .vbs launcher starts the helper without a console window.
        target.write_text(f'CreateObject("WScript.Shell").Run "{cmd}", 0, False\n')
    elif sys.platform == "darwin":
        target = Path.home() / "Library" / "LaunchAgents" / "mn.opendev.timetrack.plist"
        target.parent.mkdir(parents=True, exist_ok=True)
        args = [sys.executable, "run"] if getattr(sys, "frozen", False) else [sys.executable, str(Path(__file__).resolve()), "run"]
        items = "".join(f"<string>{a}</string>" for a in args)
        target.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>mn.opendev.timetrack</string>
<key>ProgramArguments</key><array>{items}</array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>StandardErrorPath</key><string>{config_dir() / 'agent.log'}</string>
</dict></plist>
""")
        subprocess.run(["launchctl", "load", "-w", str(target)], check=False)
    else:
        target = Path.home() / ".config" / "autostart" / "opendev-timetrack.desktop"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"[Desktop Entry]\nType=Application\nName=OpenDev Time Tracking\nExec={exe} run\nX-GNOME-Autostart-enabled=true\n")
    print(f"The helper will start at login ({target}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="timetrack-agent", description="Company time-tracking desktop helper")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("pair", help="link this computer to your account")
    p.add_argument("--server", required=True)
    p.add_argument("--code", required=True)
    p.add_argument("--name", help="computer name shown in the dashboard")
    p.set_defaults(func=cmd_pair)
    sub.add_parser("run", help="start tracking").set_defaults(func=cmd_run)
    sub.add_parser("status", help="show link and idle status").set_defaults(func=cmd_status)
    sub.add_parser("unpair", help="forget this computer's link").set_defaults(func=cmd_unpair)
    sub.add_parser("install-autostart", help="start the helper at login").set_defaults(func=cmd_install_autostart)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(config_dir() / "agent.log")])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
