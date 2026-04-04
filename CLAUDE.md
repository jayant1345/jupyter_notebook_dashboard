# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# First-time setup (installs deps + creates sample notebooks)
python setup.py

# Run the dashboard
python app.py                          # http://localhost:8050
python app.py --port 8080 --host 0.0.0.0
python app.py --debug                  # enables Dash hot-reload

# Install dependencies only
pip install -r requirements.txt
```

## Architecture

The app is a **Dash + Flask** single-process application. Dash owns the UI; Flask routes (`server = app.server`) provide the REST API on the same process and port.

```
app.py                  ← Dash layout + all callbacks + Flask REST routes
utils/
  notebook_runner.py    ← NotebookRunner class + module-level singleton `runner`
  process_manager.py    ← ProcessManager class + module-level singleton `process_mgr`
assets/custom.css       ← All styling; dark/light mode via CSS variables on .app-wrapper
assets/clientside.js    ← Auto-scrolls the log window via MutationObserver
config/custom_buttons.json  ← Persisted pipeline button definitions (read/written at runtime)
notebooks/              ← Default notebook storage (configurable at runtime via UI)
logs/                   ← Per-run log files: <stem>_<timestamp>.log
```

### State model

`NotebookRunner._states` is the single source of truth for notebook status. It is a plain dict guarded by `threading.Lock`, keyed on absolute notebook path:

```python
{
  "/abs/path/notebook.ipynb": {
    "status": "idle|running|completed|failed|stopped",
    "progress": 0-100,
    "current_cell": int,
    "total_cells": int,
    "start_time": ISO str,
    "end_time": ISO str | None,
    "log_file": "/abs/path/logs/<stem>_<ts>.log",
    "error": str | None,
    "_thread": threading.Thread,   # excluded from serialisation
  }
}
```

The UI never writes to this dict directly — it calls `runner` methods which acquire the lock internally.

### Polling rhythm

Two `dcc.Interval` components drive all real-time updates:
- `interval-fast` (2 s) — notebook table, log window, clock, summary cards
- `interval-slow` (10 s) — process list, execution history, custom buttons

### Execution flow

`runner.run_notebook(path)` → spawns a `threading.Thread` → calls `_run_papermill` (or `_run_nbconvert` fallback) → writes timestamped lines to a `.log` file → updates `_states` in place → appends to the module-level `execution_history` list.

The UI reads log files directly via `runner.get_log_lines()` on every `interval-fast` tick.

`process_mgr.start_watchdog(runner)` spawns a separate daemon thread that polls `_timeout_map` every 30 s and calls `runner.stop_notebook()` for any execution that has exceeded its registered timeout.

### Tab navigation

Tabs are not `dcc.Tabs` — they are sidebar nav links that trigger `switch_tab()`, which returns a freshly built layout component into `#main-content`. The log panel is rendered outside `#main-content` and persists across tab switches.

### Custom buttons

Stored as a JSON array in `config/custom_buttons.json`. Each entry has `id`, `label`, `color`, `notebooks` (list of paths), `sequential` (bool). The `manage_custom_buttons` callback both creates buttons (on button click) and re-renders the list (on `interval-slow`). Running a custom button calls `runner.run_multiple()`.

### Pattern-matched callbacks

Row-level actions (run, view log, delete) use Dash pattern-matching callbacks with `{"type": "btn-run-one", "index": <nb_path>}`. The triggered `prop_id` is parsed with `re.search(r'"index":"([^"]+)"', prop)` to extract the path.

### REST API

All six routes live at the bottom of `app.py` on `server` (the Flask instance). They share the same `runner` and `process_mgr` singletons — no separate state.

### Dark mode

Toggling `#dark-mode-toggle` sets class `dark-mode` or `light-mode` on `#app-wrapper`. All theming is done via CSS custom properties in `assets/custom.css` — no JS theme swapping and no stylesheet replacement.
