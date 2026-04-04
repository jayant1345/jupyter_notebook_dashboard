"""
process_manager.py
------------------
Detects, lists, and kills Jupyter-related processes using psutil.
Provides auto-timeout enforcement for long-running kernels.
"""

import threading
import time
from datetime import datetime

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# Keywords that identify Jupyter / notebook processes
JUPYTER_KEYWORDS = [
    "jupyter", "ipykernel", "nbconvert", "papermill", "ipython",
]


def _is_jupyter_process(proc) -> bool:
    try:
        name = (proc.name() or "").lower()
        cmdline = " ".join(proc.cmdline() or []).lower()
        return any(kw in name or kw in cmdline for kw in JUPYTER_KEYWORDS)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


class ProcessManager:
    """Manages detection and termination of Jupyter-related OS processes."""

    def __init__(self):
        self._watchdog_thread: threading.Thread | None = None
        self._watchdog_running = False
        self._timeout_map: dict = {}   # nb_path -> (start_time, timeout_sec)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Process discovery
    # ------------------------------------------------------------------

    def list_processes(self) -> list:
        """Return a list of dicts describing active Jupyter processes."""
        if not PSUTIL_AVAILABLE:
            return [{"error": "psutil not installed"}]

        results = []
        for proc in psutil.process_iter(["pid", "name", "status", "cpu_percent",
                                          "memory_info", "create_time", "cmdline"]):
            if not _is_jupyter_process(proc):
                continue
            try:
                mem_mb = proc.info["memory_info"].rss / (1024 ** 2) if proc.info.get("memory_info") else 0
                elapsed = time.time() - (proc.info.get("create_time") or time.time())
                cmdline = " ".join(proc.info.get("cmdline") or [])
                results.append({
                    "pid": proc.info["pid"],
                    "name": proc.info.get("name", "unknown"),
                    "status": proc.info.get("status", "unknown"),
                    "cpu_pct": round(proc.info.get("cpu_percent", 0) or 0, 1),
                    "mem_mb": round(mem_mb, 1),
                    "elapsed_min": round(elapsed / 60, 1),
                    "cmdline": cmdline[:120] + ("..." if len(cmdline) > 120 else ""),
                    "start_time": datetime.fromtimestamp(
                        proc.info.get("create_time") or time.time()
                    ).strftime("%H:%M:%S"),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return results

    # ------------------------------------------------------------------
    # Kill helpers
    # ------------------------------------------------------------------

    def kill_process(self, pid: int) -> bool:
        """Kill a single process by PID."""
        if not PSUTIL_AVAILABLE:
            return False
        try:
            proc = psutil.Process(pid)
            proc.kill()
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def kill_processes(self, pids: list) -> dict:
        """Kill multiple processes. Returns {pid: success}."""
        return {pid: self.kill_process(pid) for pid in pids}

    def kill_all_jupyter(self) -> int:
        """Kill every detected Jupyter process. Returns count killed."""
        if not PSUTIL_AVAILABLE:
            return 0
        count = 0
        for proc in psutil.process_iter(["pid"]):
            if _is_jupyter_process(proc):
                try:
                    proc.kill()
                    count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        return count

    def kill_idle_kernels(self, idle_threshold_min: float = 30.0) -> int:
        """Kill kernels that have been running with 0% CPU for >= threshold minutes."""
        if not PSUTIL_AVAILABLE:
            return 0
        count = 0
        for proc in psutil.process_iter(["pid", "cpu_percent", "create_time", "name", "cmdline"]):
            if not _is_jupyter_process(proc):
                continue
            try:
                # Sample CPU twice to get a real reading
                cpu = proc.cpu_percent(interval=0.2)
                elapsed_min = (time.time() - (proc.create_time() or time.time())) / 60
                if cpu < 0.5 and elapsed_min >= idle_threshold_min:
                    proc.kill()
                    count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return count

    # ------------------------------------------------------------------
    # Auto-timeout watchdog
    # ------------------------------------------------------------------

    def register_timeout(self, nb_path: str, timeout_sec: int):
        """Register a notebook for timeout enforcement."""
        with self._lock:
            self._timeout_map[nb_path] = (time.time(), timeout_sec)

    def unregister_timeout(self, nb_path: str):
        with self._lock:
            self._timeout_map.pop(nb_path, None)

    def start_watchdog(self, runner, check_interval: int = 30):
        """
        Start background watchdog that kills notebooks exceeding their timeout.
        `runner` must be a NotebookRunner instance.
        """
        if self._watchdog_running:
            return
        self._watchdog_running = True
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            args=(runner, check_interval),
            daemon=True,
            name="process-watchdog",
        )
        self._watchdog_thread.start()

    def stop_watchdog(self):
        self._watchdog_running = False

    def _watchdog_loop(self, runner, check_interval: int):
        while self._watchdog_running:
            now = time.time()
            with self._lock:
                snapshot = dict(self._timeout_map)
            for nb_path, (start, timeout_sec) in snapshot.items():
                if now - start > timeout_sec:
                    status = runner.get_status(nb_path)
                    if status == "running":
                        runner.stop_notebook(nb_path)
                        self.unregister_timeout(nb_path)
            time.sleep(check_interval)

    # ------------------------------------------------------------------
    # System summary
    # ------------------------------------------------------------------

    def system_summary(self) -> dict:
        """Return high-level system resource info."""
        if not PSUTIL_AVAILABLE:
            return {}
        try:
            mem = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=0.1)
            return {
                "cpu_pct": cpu,
                "mem_total_gb": round(mem.total / (1024 ** 3), 1),
                "mem_used_gb": round(mem.used / (1024 ** 3), 1),
                "mem_pct": mem.percent,
                "jupyter_count": len(self.list_processes()),
            }
        except Exception:
            return {}


# Module-level singleton
process_mgr = ProcessManager()
