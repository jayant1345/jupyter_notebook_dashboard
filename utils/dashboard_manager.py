"""
dashboard_manager.py
--------------------
Manages live Dash dashboard .py scripts as persistent background subprocesses.
Each dashboard gets its own log file under logs/dash_<name>_<ts>.log.
"""

import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
LOGS_DIR = BASE_DIR / "logs"
CONFIG_FILE = CONFIG_DIR / "dashboards.json"

CONFIG_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)


class DashboardManager:
    """Manages live Dash dashboard processes."""

    def __init__(self):
        self._processes: dict = {}    # name -> subprocess.Popen
        self._log_files: dict = {}    # name -> str log path
        self._log_handles: dict = {}  # name -> open file handle
        self._lock = threading.Lock()
        self._dashboards: list = self._load_config()

    # ── Config persistence ─────────────────────────────────────────────────────

    def _load_config(self) -> list:
        if CONFIG_FILE.exists():
            try:
                return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def _save_config(self):
        CONFIG_FILE.write_text(
            json.dumps(self._dashboards, indent=2), encoding="utf-8"
        )

    # ── Registration ───────────────────────────────────────────────────────────

    def register(self, name: str, path: str, port: int, description: str = "") -> tuple[bool, str]:
        """Register a dashboard. Returns (success, message)."""
        name = name.strip()
        if not name:
            return False, "Name is required."
        if not path.strip():
            return False, "Script path is required."
        if not Path(path).exists():
            return False, f"File not found: {path}"
        if not path.endswith(".py"):
            return False, "Only .py files are supported."
        for d in self._dashboards:
            if d["name"] == name:
                return False, f"Dashboard '{name}' already registered."
            if d["port"] == int(port):
                return False, f"Port {port} already used by '{d['name']}'."
        self._dashboards.append({
            "name": name,
            "path": str(path),
            "port": int(port),
            "description": description.strip(),
        })
        self._save_config()
        return True, f"Dashboard '{name}' registered."

    def unregister(self, name: str) -> bool:
        """Remove a dashboard from the registry (stops it first)."""
        self.stop(name)
        before = len(self._dashboards)
        self._dashboards = [d for d in self._dashboards if d["name"] != name]
        if len(self._dashboards) < before:
            self._save_config()
            return True
        return False

    def get_config(self, name: str) -> dict | None:
        return next((d for d in self._dashboards if d["name"] == name), None)

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self, name: str) -> tuple[bool, str]:
        """Start the dashboard as a background subprocess."""
        cfg = self.get_config(name)
        if not cfg:
            return False, f"Dashboard '{name}' not registered."

        with self._lock:
            proc = self._processes.get(name)
            if proc and proc.poll() is None:
                return False, f"Dashboard '{name}' is already running."

        path = cfg["path"]
        if not Path(path).exists():
            return False, f"Script not found: {path}"

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = str(LOGS_DIR / f"dash_{name}_{ts}.log")

        log_fh = open(log_path, "w", encoding="utf-8", buffering=1)
        log_fh.write(f"[{datetime.now().strftime('%H:%M:%S')}] Starting dashboard: {name}\n")
        log_fh.write(f"[{datetime.now().strftime('%H:%M:%S')}] Script : {path}\n")
        log_fh.write(f"[{datetime.now().strftime('%H:%M:%S')}] Port   : {cfg['port']}\n")
        log_fh.write(f"[{datetime.now().strftime('%H:%M:%S')}] URL    : http://localhost:{cfg['port']}\n")
        log_fh.write("-" * 60 + "\n")
        log_fh.flush()

        env = dict(os.environ)

        proc = subprocess.Popen(
            [sys.executable, path],
            stdout=log_fh,
            stderr=log_fh,
            cwd=str(Path(path).parent),
            env=env,
        )

        with self._lock:
            self._processes[name] = proc
            self._log_files[name] = log_path
            self._log_handles[name] = log_fh

        return True, f"Dashboard '{name}' started (PID {proc.pid})."

    def stop(self, name: str) -> tuple[bool, str]:
        """Terminate the dashboard process."""
        with self._lock:
            proc = self._processes.get(name)
            log_fh = self._log_handles.get(name)

        if not proc or proc.poll() is not None:
            return False, f"Dashboard '{name}' is not running."

        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

            if log_fh:
                try:
                    log_fh.write(f"\n[{datetime.now().strftime('%H:%M:%S')}] Dashboard stopped.\n")
                    log_fh.flush()
                    log_fh.close()
                except Exception:
                    pass

            return True, f"Dashboard '{name}' stopped."
        except Exception as exc:
            return False, str(exc)

    def get_status(self, name: str) -> str:
        """Returns: running | stopped | error"""
        with self._lock:
            proc = self._processes.get(name)
        if proc is None:
            return "stopped"
        rc = proc.poll()
        if rc is None:
            return "running"
        return "stopped" if rc == 0 else "error"

    def get_pid(self, name: str) -> int | None:
        with self._lock:
            proc = self._processes.get(name)
        if proc and proc.poll() is None:
            return proc.pid
        return None

    def get_log_file(self, name: str) -> str | None:
        with self._lock:
            return self._log_files.get(name)

    def get_log_lines(self, name: str, last_n: int = 300) -> list:
        log_file = self.get_log_file(name)
        if log_file and Path(log_file).exists():
            with open(log_file, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            return lines[-last_n:]
        return []

    def list_dashboards(self) -> list:
        result = []
        for d in self._dashboards:
            name = d["name"]
            result.append({
                **d,
                "status": self.get_status(name),
                "pid": self.get_pid(name),
            })
        return result


# Module-level singleton
dashboard_mgr = DashboardManager()
