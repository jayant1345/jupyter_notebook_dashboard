# Jupyter Notebook Dashboard

A production-ready web dashboard for managing, executing, and monitoring Jupyter notebooks in real time — built with Python, Dash, and Flask.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Project Structure](#2-project-structure)
3. [Quick Start](#3-quick-start)
4. [How to Use the Dashboard](#4-how-to-use-the-dashboard)
   - [Notebook Management Tab](#41-notebook-management-tab)
   - [Custom Buttons Tab](#42-custom-buttons-tab)
   - [Process Manager Tab](#43-process-manager-tab)
   - [History Tab](#44-history-tab)
   - [Live Log Window](#45-live-log-window)
   - [Dark Mode](#46-dark-mode)
5. [REST API Reference](#5-rest-api-reference)
6. [Technical Design — How Everything Was Built](#6-technical-design--how-everything-was-built)
   - [Technology Stack](#61-technology-stack)
   - [Application Architecture](#62-application-architecture)
   - [Notebook Execution Engine](#63-notebook-execution-engine)
   - [Thread-Safe State Management](#64-thread-safe-state-management)
   - [Real-Time UI Updates (Polling)](#65-real-time-ui-updates-polling)
   - [File Upload Mechanism](#66-file-upload-mechanism)
   - [Custom Pipeline Buttons](#67-custom-pipeline-buttons)
   - [Process Manager & Watchdog](#68-process-manager--watchdog)
   - [Live Log Streaming](#69-live-log-streaming)
   - [Dark Mode Implementation](#610-dark-mode-implementation)
   - [REST API Layer](#611-rest-api-layer)
   - [Error Handling Strategy](#612-error-handling-strategy)
7. [Configuration](#7-configuration)
8. [Deployment on a LAN](#8-deployment-on-a-lan)

---

## 1. Overview

This dashboard solves a common problem for data engineers and analysts who run multiple Jupyter notebooks as part of scheduled jobs, data pipelines, or reporting workflows — there is no easy way to manage, trigger, monitor, and debug them from a single place.

**Key capabilities:**

| Capability | Detail |
|---|---|
| Upload notebooks | Drag & drop or file picker directly in the browser |
| Load from folder | Point to any folder on the server's filesystem |
| Execute notebooks | Run one, run all, or run a custom pipeline in sequence |
| Real-time logs | stdout/stderr streamed to the log window every 2 seconds |
| Status tracking | Idle / Running / Completed / Failed with live progress bars |
| Process control | Detect, list, and kill Jupyter OS processes via psutil |
| Custom buttons | Create named buttons that run specific notebook pipelines |
| Execution history | In-session log of every run with duration and error info |
| REST API | 6 endpoints for external automation (CI/CD, scripts, etc.) |
| Dark mode | Full theme toggle with CSS variable swap |

---

## 2. Project Structure

```
Report_dashboard/
│
├── app.py                      # Dash layout, all callbacks, Flask REST routes
│
├── utils/
│   ├── __init__.py
│   ├── notebook_runner.py      # NotebookRunner class — execution engine
│   └── process_manager.py      # ProcessManager class — OS process control
│
├── assets/
│   ├── custom.css              # All dashboard styling (dark + light mode)
│   └── clientside.js           # Auto-scroll for the live log window
│
├── config/
│   └── custom_buttons.json     # Saved custom pipeline button definitions
│
├── notebooks/                  # Default location for .ipynb files
│   ├── sample_hello.ipynb
│   └── sample_data_report.ipynb
│
├── logs/                       # Auto-created per-run log files (gitignored)
│
├── requirements.txt            # All Python dependencies
├── setup.py                    # One-shot bootstrap script
├── CLAUDE.md                   # AI assistant guidance file
└── README.md                   # This file
```

---

## 3. Quick Start

### Step 1 — Clone and set up

```bash
git clone https://github.com/jayant1345/jupyter_notebook_dashboard.git
cd jupyter_notebook_dashboard

# Run the one-shot setup (installs deps + creates sample notebooks)
python setup.py
```

### Step 2 — Start the dashboard

```bash
python app.py
```

Open your browser at **http://localhost:8050**

### Optional flags

```bash
python app.py --port 8080          # Change port
python app.py --host 0.0.0.0       # Expose on all network interfaces (LAN)
python app.py --debug              # Enable Dash hot-reload (development)
```

### Manual dependency install (if setup.py not used)

```bash
pip install -r requirements.txt
```

---

## 4. How to Use the Dashboard

The dashboard has a **sidebar** on the left and a **main panel** on the right. The sidebar shows summary counts and navigation links to four tabs. A persistent **live log window** sits at the bottom of every tab.

---

### 4.1 Notebook Management Tab

This is the default view when you open the dashboard.

#### Loading notebooks

**Option A — Default folder:**  
On startup, the dashboard automatically loads all `.ipynb` files from the `notebooks/` folder inside the project.

**Option B — Custom folder:**  
Type any absolute folder path into the "Load from folder path" input box and click **Load Folder**. The table refreshes immediately with all `.ipynb` files found in that folder.

**Option C — Upload from browser:**  
Drag one or more `.ipynb` files into the dashed upload zone, or click the zone to open a file picker. Uploaded files are saved into the `notebooks/` directory and appear in the table automatically.

- Only `.ipynb` files are accepted. Non-notebook files are rejected with a warning.
- Uploading a file with the same name as an existing file overwrites it (a warning is shown).
- The file is validated as proper JSON before saving — corrupt uploads are rejected.

#### The notebook table

Each row shows:

| Column | Description |
|---|---|
| Checkbox | Select for bulk operations |
| Name | File name with a notebook icon |
| Uploaded | File creation timestamp (ctime) |
| Modified | Last file modification timestamp |
| Size | File size in KB |
| Status | Colour-coded badge: grey=Idle, yellow=Running, green=Completed, red=Failed |
| Progress | Animated progress bar showing cell completion percentage while running |
| Duration | Elapsed or total execution time |
| Actions | Per-row Run, View Logs, and Delete buttons |

#### Search / filter

Type in the **Search** box in the toolbar to filter the table by notebook name in real time. The filter is case-insensitive.

#### Running notebooks

- **Run Selected** — tick the checkboxes on the rows you want, then click this button. All selected notebooks start simultaneously in parallel.
- **Run All** — starts every notebook in the current folder simultaneously.
- **Run** (per-row green button) — runs that single notebook immediately.
- **Stop** (toolbar) — sends a termination signal to all currently running notebooks and their associated Python/Jupyter kernel processes.
- **Retry Failed** — re-runs every notebook whose status is "failed" or "stopped".
- **Delete** (per-row red trash button) — shows a confirmation dialog before permanently deleting the file from disk.

---

### 4.2 Custom Buttons Tab

Custom buttons let you save and re-run frequently used notebook pipelines with a single click, without having to remember which notebooks to select each time.

#### Creating a custom button

Fill in the form on the left:

| Field | Description |
|---|---|
| Button Label | The display name, e.g. "Daily Report" or "MME Analysis" |
| Color | Visual colour for the button (Primary, Success, Warning, Danger, Info, Dark) |
| Description | Optional tooltip-style description shown under the label |
| Notebooks | One notebook path per line — use paths relative to the project or absolute paths |
| Run sequentially | If ON, notebooks run one after another; if OFF, all start at the same time |

Click **Create Button** and the button appears immediately in the panel on the right. Button configurations are persisted to `config/custom_buttons.json` and survive server restarts.

#### Using a custom button

Click the **Run** button on any custom button card. The dashboard starts the configured notebooks and shows a toast notification. If sequential mode is on, the next notebook only starts after the previous one finishes.

#### Deleting a custom button

Click the trash icon on the button card. The button is removed from the JSON file immediately.

---

### 4.3 Process Manager Tab

This tab gives you OS-level visibility into all Jupyter and notebook-related processes currently running on the server machine.

#### System Resources panel (left)

Shows live CPU usage percentage and RAM usage (used/total GB) as progress bars. These are read from the OS via psutil and update every 10 seconds.

#### Jupyter Processes table (right)

Lists every process whose name or command line contains any of these keywords: `jupyter`, `ipykernel`, `nbconvert`, `papermill`, `ipython`.

Columns shown: PID, Process Name, Status, CPU%, Memory (MB), Uptime (minutes), Command line snippet.

**Kill Selected** — tick the checkboxes on the rows you want to terminate, then click this button. Each process receives a SIGKILL.

**Kill All Jupyter** — immediately kills every detected Jupyter-related process on the machine. Use with caution.

#### Auto-timeout Settings panel (bottom)

| Setting | Description |
|---|---|
| Global timeout (minutes) | Notebooks running longer than this will be automatically stopped by the watchdog thread |
| Kill idle kernels after (minutes) | Threshold for the "Kill Idle Kernels" action |
| Kill Idle Kernels button | Scans all Jupyter processes, measures CPU over 0.2 seconds, and kills any that are below 0.5% CPU and have been running for the threshold duration |

---

### 4.4 History Tab

Shows an in-session log of every notebook execution since the server started. Each row records the notebook name, final status, start time, total duration, and any error message.

The list is ordered newest-first and capped at 100 entries in the display (the full list is kept in memory).

**Clear History** button (top right) empties the list for the current session.

---

### 4.5 Live Log Window

The log window is pinned to the bottom of every tab — it does not disappear when you switch tabs.

**Selecting which notebook's logs to view:**  
Either use the dropdown in the log panel header to pick a notebook, or click the eye icon on any notebook's row — this automatically selects that notebook in the dropdown.

**Log content:**  
Each line is prefixed with a timestamp in `[HH:MM:SS]` format. Lines containing the words `error`, `failed`, `traceback`, or `exception` are highlighted in red. Lines containing `warning` or `warn` are highlighted in yellow.

**Clear** — removes the displayed text from the window (the log file on disk is not affected).

**Download** — saves the full log content to a `.txt` file named `<notebook_stem>_logs_<timestamp>.txt`.

**Auto-scroll:**  
A `MutationObserver` in `assets/clientside.js` watches the log element for content changes and automatically scrolls to the bottom whenever new lines arrive.

---

### 4.6 Dark Mode

The toggle switch in the sidebar footer switches the entire dashboard between light and dark themes instantly. The preference is stored in a `dcc.Store` component for the duration of your browser session.

---

## 5. REST API Reference

The dashboard exposes a REST API on the same host and port as the UI. All endpoints return JSON.

### GET /api/notebooks

Returns all notebooks in the default folder with their current execution state.

```bash
curl http://localhost:8050/api/notebooks

# Optional: specify a different folder
curl "http://localhost:8050/api/notebooks?folder=/path/to/folder"
```

Response: array of notebook objects, each with `name`, `path`, `size`, `upload_date`, `last_modified`, and a `state` sub-object.

---

### GET /api/status/\<name\>

Returns the execution state for a specific notebook by filename or partial path.

```bash
curl http://localhost:8050/api/status/sample_hello.ipynb
```

Response:
```json
{
  "status": "completed",
  "progress": 100,
  "current_cell": 4,
  "total_cells": 4,
  "start_time": "2026-04-04T22:30:00",
  "end_time": "2026-04-04T22:30:05",
  "log_file": "logs/sample_hello_20260404_223000.log",
  "error": null
}
```

---

### GET /api/logs/\<name\>

Returns the last 500 lines of the execution log for a notebook.

```bash
curl http://localhost:8050/api/logs/sample_hello.ipynb
```

Response:
```json
{
  "notebook": "sample_hello.ipynb",
  "lines": ["[22:30:00] Starting: sample_hello.ipynb\n", "..."]
}
```

---

### POST /api/run

Triggers execution of a notebook by absolute file path.

```bash
curl -X POST http://localhost:8050/api/run \
     -H "Content-Type: application/json" \
     -d '{"notebook": "C:/Project_AI/Report_dashboard/notebooks/sample_hello.ipynb"}'

# Optional: set a custom timeout in seconds
curl -X POST http://localhost:8050/api/run \
     -H "Content-Type: application/json" \
     -d '{"notebook": "/path/to/notebook.ipynb", "timeout": 1800}'
```

Response:
```json
{"started": true, "notebook": "/path/to/notebook.ipynb"}
```

Returns `"started": false` if the notebook is already running.

---

### POST /api/upload

Upload a `.ipynb` file to the server's `notebooks/` directory.

```bash
curl -X POST http://localhost:8050/api/upload \
     -F "file=@/local/path/my_analysis.ipynb"
```

Response:
```json
{"uploaded": "my_analysis.ipynb", "path": "C:/Project_AI/Report_dashboard/notebooks/my_analysis.ipynb"}
```

---

### POST /api/stop

Stops a currently running notebook execution.

```bash
curl -X POST http://localhost:8050/api/stop \
     -H "Content-Type: application/json" \
     -d '{"notebook": "/path/to/notebook.ipynb"}'
```

---

## 6. Technical Design — How Everything Was Built

This section explains the engineering decisions and implementation details behind each major component.

---

### 6.1 Technology Stack

| Layer | Library | Reason chosen |
|---|---|---|
| Web framework | **Dash** (Plotly) | Reactive Python-native UI without writing JavaScript for callbacks |
| UI components | **Dash Bootstrap Components** | Pre-built responsive layout, cards, modals, badges, progress bars |
| Icons | **Bootstrap Icons** (CDN) | Font-based icons requiring zero image files |
| HTTP server | **Flask** (bundled with Dash) | Dash exposes `app.server` as a Flask instance — REST routes added directly |
| Notebook execution | **papermill** | Provides cell-level progress callbacks, parameter injection, output notebook saving |
| Execution fallback | **nbconvert** via subprocess | Used automatically if papermill is not importable |
| Process management | **psutil** | Cross-platform OS process enumeration and signal sending |
| Background execution | **threading** (stdlib) | Avoids multiprocessing pickle constraints; Dash state is in-process |
| CSS theming | **CSS custom properties** | Single variable swap for dark/light mode without JS stylesheet changes |

---

### 6.2 Application Architecture

The entire application runs as a **single Python process**. Dash handles the UI and its reactive callback system. Flask (which Dash runs on top of) handles the REST API routes. Background notebook execution runs in daemon threads within the same process.

```
Browser
  |
  |  HTTP (Dash UI)          HTTP (REST API)
  |                               |
  +----------+  app.py  +---------+
             |          |
         [Dash callbacks] [Flask routes]
                |                |
                +------ runner (NotebookRunner singleton)
                |                |
                +------ process_mgr (ProcessManager singleton)
                                 |
                        [daemon threads: one per running notebook]
                        [daemon thread: process watchdog]
```

The two singletons (`runner` and `process_mgr`) are imported at module load time and shared between all Dash callbacks and all Flask routes, with no duplication of state.

---

### 6.3 Notebook Execution Engine

**File:** `utils/notebook_runner.py` — class `NotebookRunner`

When a user clicks Run, `runner.run_notebook(path)` is called. The method:

1. **Guards against double-execution** — checks `_states[path]["status"]` under a lock. Returns `False` immediately if the notebook is already `"running"`.

2. **Creates a log file** — each run gets a unique file: `logs/<notebook_stem>_<YYYYMMDD_HHMMSS>.log`. This means multiple runs of the same notebook each get their own separate log history.

3. **Sets initial state** — writes the `"running"` state into `_states` under the lock, recording `start_time`, `log_file` path, and zeroed progress counters.

4. **Spawns a daemon thread** — `threading.Thread(daemon=True)` so the thread is automatically cleaned up if the main process exits. The thread name is `nb-<stem>` for debuggability.

**Inside the thread**, execution happens in `_execute()`:

```
_execute()
  ├── try: import papermill  → _run_papermill()
  └── except ImportError    → _run_nbconvert()  (fallback)
```

**papermill path (`_run_papermill`):**
- Reads the notebook JSON to count code cells upfront (for the progress percentage calculation).
- Calls `pm.execute_notebook()` with `stdout_file` and `stderr_file` both pointing to the log file, so all cell output lands there automatically.
- The output notebook is saved as `<stem>_executed.ipynb` — the original is preserved untouched.
- Progress (current cell / total cells × 100) is updated in `_states` after each cell via the cell counter.

**nbconvert fallback path (`_run_nbconvert`):**
- Builds a `jupyter nbconvert --execute --inplace` command.
- Uses `subprocess.Popen` with `stdout=PIPE, stderr=STDOUT` for combined output capture.
- Reads stdout line-by-line and writes each line with a timestamp to the log file in real time.
- Checks `proc.returncode` at completion — non-zero raises `RuntimeError`.

**Completion / failure recording:**
- `_mark_completed()` sets `status="completed"`, `progress=100`, `end_time` in `_states` and appends a record to the module-level `execution_history` list.
- `_mark_failed()` sets `status="failed"`, records the exception message and full traceback into the log file, and appends a failed record to `execution_history`.

**Stopping a notebook:**
- `stop_notebook()` calls `proc.terminate()` on the stored `subprocess.Popen` object (if using nbconvert).
- It also uses psutil to scan for any Python process whose command line contains the notebook's filename — this catches both papermill kernel processes and nbconvert subprocesses.

---

### 6.4 Thread-Safe State Management

All mutable state in `NotebookRunner` is accessed through a single `threading.Lock` (`self._lock`). The pattern used consistently is:

```python
with self._lock:
    # read or write self._states or self._processes
```

The `_states` dict maps `absolute_notebook_path → state_dict`. When the Dash callback layer reads state, `get_all_states()` returns a full copy with the `_thread` key excluded (because `threading.Thread` objects are not JSON-serialisable and would cause Dash to crash if stored in a `dcc.Store`).

The `execution_history` list is a module-level global appended to (never re-assigned), which is safe without a lock under Python's GIL for simple list `.append()` calls.

---

### 6.5 Real-Time UI Updates (Polling)

Dash does not support push-based server-sent events in its standard configuration, so the dashboard uses **interval-based polling** via two `dcc.Interval` components:

| Component | Interval | Drives |
|---|---|---|
| `interval-fast` | 2 seconds | Notebook table, live log window, navbar clock, summary cards |
| `interval-slow` | 10 seconds | Process list, execution history, custom buttons list |

Every callback that needs to show live data takes `interval-fast` or `interval-slow` as an `Input`. This means every 2 seconds, Dash re-runs those callbacks on the server and sends the updated HTML to the browser — no WebSocket or streaming protocol required.

The choice of 2 seconds for fast polling balances responsiveness against server load. For a deployment with many concurrent users, this interval could be increased.

---

### 6.6 File Upload Mechanism

Dash's `dcc.Upload` component handles file uploads entirely client-side first: the browser reads the selected file(s), encodes them as **Base64**, and sends the encoded string as a Dash callback input.

The `handle_upload` callback in `app.py`:

1. Splits the data URI: `content.split(",", 1)` gives `["data:application/json;base64", "<base64_data>"]`.
2. Decodes with `base64.b64decode(b64)`.
3. **Validates** the decoded bytes with `json.loads(data)` — this confirms the file is valid JSON before saving. Invalid files are rejected with an error alert.
4. Writes to `NOTEBOOKS_DIR / filename` with `Path.write_bytes()`.
5. Returns a `dbc.Alert` component for each file processed — success (green) or error (red/yellow).

Because the notebook table callback also takes `upload-status` as an `Input`, the table refreshes immediately after every upload without a separate "refresh" click.

---

### 6.7 Custom Pipeline Buttons

Custom buttons are the mechanism for saving named, reusable notebook pipelines.

**Storage format** (`config/custom_buttons.json`):

```json
[
  {
    "id": "btn_1712345678",
    "label": "Daily Job",
    "icon": "bi bi-play-fill",
    "color": "primary",
    "notebooks": [
      "notebooks/analysis.ipynb",
      "notebooks/report.ipynb"
    ],
    "sequential": true,
    "description": "Run daily analysis then generate report"
  }
]
```

The `id` is generated from `int(time.time())` — a Unix timestamp — making it unique without needing a database.

**Creation flow:**  
The `manage_custom_buttons` callback is triggered both by the "Create Button" click AND by `interval-slow`. When triggered by the button click, it reads the form fields, builds a new dict, appends it to the loaded list, writes back to disk, then re-renders the full button list. When triggered by the interval, it just re-renders (picks up any changes made by the delete callback).

**Sequential execution:**  
`runner.run_multiple(notebooks, sequential=True)` wraps the sequential logic in its own daemon thread:

```python
def _sequential_runner():
    for path in nb_paths:
        runner.run_notebook(path)
        while runner.get_status(path) == "running":
            time.sleep(1)   # wait for each to finish before starting next
```

This polling loop inside the sequential-runner thread does not block the UI because it runs in a separate daemon thread.

**Pattern-matched callbacks:**  
The run and delete buttons for custom button cards use Dash pattern-matching with `{"type": "custom-btn-run", "index": btn_id}`. The triggered prop_id is parsed with:

```python
re.search(r'"index":"([^"]+)"', prop).group(1)
```

This extracts the button `id` from the JSON-format Dash prop string without needing to parse the full JSON.

---

### 6.8 Process Manager & Watchdog

**File:** `utils/process_manager.py` — class `ProcessManager`

**Process detection:**  
`list_processes()` calls `psutil.process_iter()` with a set of attributes to minimise per-process syscall overhead. For each process, `_is_jupyter_process()` checks if any of the keywords `["jupyter", "ipykernel", "nbconvert", "papermill", "ipython"]` appear in either the process name or its full command line string.

**Killing:**  
`kill_process(pid)` retrieves the process object by PID and calls `.kill()` (SIGKILL on Unix, `TerminateProcess` on Windows). It handles `NoSuchProcess` gracefully in case the process died between the list call and the kill call.

**Idle kernel detection:**  
`kill_idle_kernels(threshold_min)` calls `proc.cpu_percent(interval=0.2)` which samples CPU usage over 200ms — a short but real measurement. Any process below 0.5% CPU that has been running for at least `threshold_min` minutes is killed. This catches notebooks whose kernel is alive but no longer doing any work.

**Watchdog thread:**  
`start_watchdog(runner, check_interval=30)` starts a daemon thread running `_watchdog_loop()`. This loop wakes every 30 seconds, iterates `_timeout_map` (a dict of `{nb_path: (start_unix_time, timeout_seconds)}`), and calls `runner.stop_notebook()` for any notebook that has been running longer than its registered timeout. This is the auto-timeout enforcement mechanism.

The watchdog is started in `app.py`'s `__main__` block via `process_mgr.start_watchdog(runner)` — before `app.run()` is called, ensuring it is always active.

---

### 6.9 Live Log Streaming

Logs are captured to files during execution and read back by the UI on every `interval-fast` tick (every 2 seconds).

**Writing side (execution thread):**  
The log file is opened with `open(log_file, "w", encoding="utf-8")` at the start of execution. Every log entry uses the `_log(fh, msg)` static method:

```python
fh.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
fh.flush()
```

`flush()` is called after every write so that the UI can see new content before the execution thread closes the file.

**Reading side (Dash callback):**  
`runner.get_log_lines(path, last_n=300)` opens the log file in read mode, reads all lines, and returns the last 300. This is a simple tail operation — no memory of previous reads, no seek position — making it stateless and safe to call from any callback.

**Error highlighting:**  
The `update_logs` callback iterates the returned lines and wraps any line containing error keywords in `html.Span(line, style={"color": "#ff6b6b"})`. Regular lines are returned as plain strings. Dash renders the mixed list correctly as inline elements inside the `html.Pre` container.

**Auto-scroll:**  
`assets/clientside.js` sets up a `MutationObserver` on the `#log-output` element. Whenever Dash updates the element's content (adding new log lines), the observer fires and sets `el.scrollTop = el.scrollHeight`, pinning the view to the bottom.

---

### 6.10 Dark Mode Implementation

Dark mode is implemented entirely in CSS using custom properties (CSS variables), with no JavaScript theme switching and no external stylesheet changes at runtime.

The root selector defines the light palette:

```css
:root {
  --bg-main: #f4f6fb;
  --bg-card: #ffffff;
  --text-main: #212529;
  /* ... etc ... */
}
```

The `.dark-mode` class overrides those same variables:

```css
.dark-mode {
  --bg-main: #0f1117;
  --bg-card: #1c2026;
  --text-main: #e6edf3;
  /* ... etc ... */
}
```

Every styled element uses `var(--bg-card)` etc. rather than hard-coded colours, so flipping between `.dark-mode` and `.light-mode` on the `#app-wrapper` div instantly re-themes every descendant element.

The Dash callback for the toggle:

```python
@app.callback(Output("app-wrapper", "className"), Input("dark-mode-toggle", "value"))
def toggle_dark_mode(dark):
    return "app-wrapper dark-mode" if dark else "app-wrapper light-mode"
```

CSS `transition: background-color 0.25s ease` on `.app-wrapper` gives a smooth animated fade between the two themes.

The log window intentionally keeps a dark background (`#1e1e2e`) in both modes — it mimics a terminal and is more readable for log output regardless of the overall theme.

---

### 6.11 REST API Layer

Dash is built on Flask, and `app.server` exposes the underlying Flask application instance. REST routes are added to this same instance using standard Flask decorators:

```python
server = app.server

@server.route("/api/notebooks")
def api_notebooks():
    ...
```

This means the REST API runs on the exact same host, port, and process as the Dash UI — no separate service, no CORS issues for same-origin UI calls.

All API handlers call the same `runner` and `process_mgr` singletons that the Dash callbacks use, so the state is always consistent. A `POST /api/run` from a curl command and a click of the Run button in the UI both go through `runner.run_notebook()` — there is no duplication of logic.

---

### 6.12 Error Handling Strategy

| Scenario | Handling |
|---|---|
| Non-`.ipynb` file uploaded | Rejected before saving; warning alert shown |
| Corrupt `.ipynb` file (invalid JSON) | `json.loads()` validation before write; error alert shown |
| Duplicate file upload | Overwrites with warning; no crash |
| Notebook already running | `run_notebook()` returns `False`; no second thread spawned |
| papermill not installed | Caught with `except ImportError`; falls back to nbconvert automatically |
| Notebook execution failure | Exception caught in `_mark_failed()`; full traceback written to log; status set to "failed" |
| Kernel crash / hang | Auto-timeout watchdog terminates the notebook after the configured limit |
| psutil not installed | `PSUTIL_AVAILABLE` flag disables process features gracefully; UI shows a message |
| Folder path not found | Checked before updating `store-folder-path`; error toast shown |
| Process already dead when killing | `psutil.NoSuchProcess` caught and ignored |
| Custom buttons JSON corrupt | `_load_buttons()` returns empty list on parse failure; no crash |

---

## 7. Configuration

No configuration file is needed for basic use. Runtime settings are adjusted through the UI or CLI flags.

| Setting | Where to change |
|---|---|
| Default notebook folder | UI toolbar "Load Folder" field |
| Execution timeout per notebook | Process Manager tab → "Global timeout" field |
| Idle kernel kill threshold | Process Manager tab → "Kill idle kernels after" field |
| Custom pipelines | Custom Buttons tab → saved to `config/custom_buttons.json` |
| Port | `python app.py --port <N>` |
| Host binding | `python app.py --host <IP>` |
| Log polling interval | Edit `interval-fast` `interval` prop in `app.py` layout (milliseconds) |
| Log lines shown | Edit `last_n=300` in `update_logs` callback in `app.py` |

---

## 8. Deployment on a LAN

To make the dashboard accessible to other machines on your local network:

```bash
python app.py --host 0.0.0.0 --port 8050
```

Other machines can then access it at `http://<your-machine-IP>:8050`.

To find your machine's IP on Windows:
```cmd
ipconfig
```
Look for the **IPv4 Address** under your active network adapter (e.g., `192.168.1.7`).

**For a more permanent/production deployment**, replace the development Flask server with a production WSGI server:

```bash
pip install gunicorn          # Linux/Mac
gunicorn app:server -b 0.0.0.0:8050 --workers 1 --threads 4

# Windows alternative (waitress)
pip install waitress
waitress-serve --host=0.0.0.0 --port=8050 app:server
```

Note: Use `--workers 1` with gunicorn because the notebook state lives in-memory in a single process. Multiple workers would each have their own separate state.
