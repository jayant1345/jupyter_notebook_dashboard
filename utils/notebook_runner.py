"""
notebook_runner.py
------------------
Handles Jupyter notebook execution using papermill (preferred) or nbconvert fallback.
Thread-safe state tracking, log capture, progress monitoring.
"""

import os
import json
import time
import threading
import subprocess
import traceback
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
NOTEBOOKS_DIR = BASE_DIR / "notebooks"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
NOTEBOOKS_DIR.mkdir(exist_ok=True)

# Global execution history (append-only log across sessions)
execution_history = []


class NotebookRunner:
    """Thread-safe notebook execution manager."""

    def __init__(self, timeout_default: int = 3600):
        self._states: dict = {}       # nb_path -> state dict
        self._processes: dict = {}    # nb_path -> subprocess.Popen
        self._lock = threading.Lock()
        self.timeout_default = timeout_default

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_notebooks(self, folder: str = None) -> list:
        """Return metadata for all .ipynb files in the given folder."""
        search_dir = Path(folder) if folder else NOTEBOOKS_DIR
        notebooks = []
        if not search_dir.exists():
            return notebooks
        for nb in sorted(search_dir.glob("*.ipynb")):
            stat = nb.stat()
            notebooks.append({
                "name": nb.name,
                "path": str(nb),
                "size": f"{stat.st_size / 1024:.1f} KB",
                "upload_date": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M"),
                "last_modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "status": self.get_status(str(nb)),
            })
        return notebooks

    def get_status(self, nb_path: str) -> str:
        with self._lock:
            return self._states.get(str(nb_path), {}).get("status", "idle")

    def get_all_states(self) -> dict:
        with self._lock:
            # Return a snapshot without non-serialisable fields
            return {
                k: {ck: cv for ck, cv in v.items() if ck not in ("_thread",)}
                for k, v in self._states.items()
            }

    def get_state(self, nb_path: str) -> dict:
        with self._lock:
            return dict(self._states.get(str(nb_path), {}))

    def get_log_file(self, nb_path: str) -> str | None:
        with self._lock:
            return self._states.get(str(nb_path), {}).get("log_file")

    def get_log_lines(self, nb_path: str, last_n: int = 200) -> list:
        log_file = self.get_log_file(nb_path)
        if log_file and Path(log_file).exists():
            with open(log_file, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            return lines[-last_n:]
        return []

    def get_all_log_lines(self, last_n: int = 500) -> list:
        """Aggregate last N lines from ALL recent log files."""
        all_lines = []
        for nb_path in list(self._states.keys()):
            lines = self.get_log_lines(nb_path, last_n=50)
            nb_name = Path(nb_path).name
            for line in lines:
                all_lines.append(f"[{nb_name}] {line}")
        return all_lines[-last_n:]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run_notebook(self, nb_path: str, timeout: int = None) -> bool:
        """Spawn a background thread to execute the notebook. Returns False if already running."""
        nb_path = str(nb_path)
        timeout = timeout or self.timeout_default

        with self._lock:
            current = self._states.get(nb_path, {}).get("status")
            if current == "running":
                return False

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = str(LOGS_DIR / f"{Path(nb_path).stem}_{ts}.log")

        with self._lock:
            self._states[nb_path] = {
                "status": "running",
                "progress": 0,
                "current_cell": 0,
                "total_cells": 0,
                "start_time": datetime.now().isoformat(),
                "end_time": None,
                "log_file": log_file,
                "error": None,
                "_thread": None,
            }

        thread = threading.Thread(
            target=self._execute,
            args=(nb_path, log_file, timeout),
            daemon=True,
            name=f"nb-{Path(nb_path).stem}",
        )
        with self._lock:
            self._states[nb_path]["_thread"] = thread
        thread.start()
        return True

    def run_multiple(self, nb_paths: list, sequential: bool = False, timeout: int = None):
        """Run multiple notebooks, optionally in sequence."""
        if sequential:
            def _sequential_runner():
                for path in nb_paths:
                    self.run_notebook(path, timeout)
                    # Wait for this one to finish before starting next
                    while self.get_status(path) == "running":
                        time.sleep(1)
            t = threading.Thread(target=_sequential_runner, daemon=True)
            t.start()
        else:
            for path in nb_paths:
                self.run_notebook(path, timeout)

    def stop_notebook(self, nb_path: str) -> bool:
        """Terminate a running notebook execution."""
        nb_path = str(nb_path)
        stopped = False

        with self._lock:
            proc = self._processes.get(nb_path)
            if proc:
                try:
                    proc.terminate()
                    stopped = True
                except Exception:
                    pass
            state = self._states.get(nb_path)
            if state:
                state["status"] = "stopped"
                state["end_time"] = datetime.now().isoformat()

        # Also try killing the jupyter kernel via psutil
        try:
            import psutil
            nb_name = Path(nb_path).name
            for p in psutil.process_iter(["pid", "cmdline"]):
                try:
                    cmdline = " ".join(p.info.get("cmdline") or [])
                    if nb_name in cmdline and "python" in cmdline.lower():
                        p.kill()
                        stopped = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except ImportError:
            pass

        return stopped

    def retry_failed(self, nb_path: str, timeout: int = None) -> bool:
        """Re-run a notebook that has status 'failed' or 'stopped'."""
        status = self.get_status(nb_path)
        if status in ("failed", "stopped", "idle", "completed"):
            return self.run_notebook(nb_path, timeout)
        return False

    def delete_notebook(self, nb_path: str) -> bool:
        """Delete a notebook file and clear its state."""
        nb_path = Path(nb_path)
        if nb_path.exists():
            try:
                nb_path.unlink()
            except Exception:
                return False
        with self._lock:
            self._states.pop(str(nb_path), None)
            self._processes.pop(str(nb_path), None)
        return True

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------

    def _execute(self, nb_path: str, log_file: str, timeout: int):
        try:
            try:
                import papermill  # noqa: F401
                self._run_papermill(nb_path, log_file, timeout)
            except ImportError:
                self._run_nbconvert(nb_path, log_file, timeout)
        except Exception as exc:
            self._mark_failed(nb_path, log_file, exc)

    def _run_papermill(self, nb_path: str, log_file: str, timeout: int):
        import papermill as pm

        stem = Path(nb_path).stem
        output_nb = str(NOTEBOOKS_DIR / f"{stem}_executed.ipynb")

        with open(nb_path, "r", encoding="utf-8") as fh:
            nb_json = json.load(fh)
        total_cells = sum(1 for c in nb_json.get("cells", []) if c.get("cell_type") == "code")

        with self._lock:
            self._states[nb_path]["total_cells"] = total_cells

        with open(log_file, "w", encoding="utf-8") as log:
            self._log(log, f"Starting: {Path(nb_path).name}")
            self._log(log, f"Engine  : papermill")
            self._log(log, f"Cells   : {total_cells} code cells")
            self._log(log, "-" * 60)

            cell_counter = {"n": 0}
            runner_ref = self

            class _CellCallback:
                def __call__(self, nb, cell_idx, **_kw):
                    cell_counter["n"] += 1
                    n = cell_counter["n"]
                    pct = int(n / max(total_cells, 1) * 100)
                    runner_ref._log(log, f"Cell {n}/{total_cells}  [{pct}%]")
                    with runner_ref._lock:
                        s = runner_ref._states.get(nb_path)
                        if s:
                            s["current_cell"] = n
                            s["progress"] = pct

            try:
                pm.execute_notebook(
                    nb_path,
                    output_nb,
                    log_output=True,
                    stdout_file=log,
                    stderr_file=log,
                    execution_timeout=timeout,
                    progress_bar=False,
                )
                self._mark_completed(nb_path, log)
            except Exception as exc:
                raise exc

    def _run_nbconvert(self, nb_path: str, log_file: str, timeout: int):
        cmd = [
            "jupyter", "nbconvert",
            "--to", "notebook",
            "--execute",
            "--inplace",
            f"--ExecutePreprocessor.timeout={timeout}",
            "--ExecutePreprocessor.allow_errors=False",
            nb_path,
        ]
        with open(log_file, "w", encoding="utf-8") as log:
            self._log(log, f"Starting: {Path(nb_path).name}")
            self._log(log, "Engine  : nbconvert")
            self._log(log, "-" * 60)

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            with self._lock:
                self._processes[nb_path] = proc

            for line in proc.stdout:
                ts = datetime.now().strftime("%H:%M:%S")
                log.write(f"[{ts}] {line}")
                log.flush()

            proc.wait()
            with self._lock:
                self._processes.pop(nb_path, None)

            if proc.returncode == 0:
                self._mark_completed(nb_path, log)
            else:
                raise RuntimeError(f"nbconvert exited with code {proc.returncode}")

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _mark_completed(self, nb_path: str, log=None):
        with self._lock:
            s = self._states.get(nb_path)
            if s:
                s["status"] = "completed"
                s["progress"] = 100
                s["end_time"] = datetime.now().isoformat()
        if log:
            self._log(log, "=" * 60)
            self._log(log, "EXECUTION COMPLETED SUCCESSFULLY")
        execution_history.append({
            "notebook": Path(nb_path).name,
            "status": "completed",
            "start_time": self._states.get(nb_path, {}).get("start_time"),
            "end_time": datetime.now().isoformat(),
        })

    def _mark_failed(self, nb_path: str, log_file: str, exc: Exception):
        with self._lock:
            s = self._states.get(nb_path)
            if s:
                s["status"] = "failed"
                s["end_time"] = datetime.now().isoformat()
                s["error"] = str(exc)
        with open(log_file, "a", encoding="utf-8") as log:
            self._log(log, "=" * 60)
            self._log(log, f"EXECUTION FAILED: {exc}")
            log.write(traceback.format_exc())
        execution_history.append({
            "notebook": Path(nb_path).name,
            "status": "failed",
            "start_time": self._states.get(nb_path, {}).get("start_time"),
            "end_time": datetime.now().isoformat(),
            "error": str(exc),
        })

    @staticmethod
    def _log(fh, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        fh.write(f"[{ts}] {msg}\n")
        fh.flush()


# Module-level singleton
runner = NotebookRunner()
