"""
app.py  ─  Jupyter Notebook Dashboard
======================================
A production-ready Dash application for managing, executing, and monitoring
Jupyter notebooks with real-time logs, process control, and custom pipelines.

Run:
    python app.py [--port 8050] [--host 0.0.0.0]

REST API endpoints:
    GET  /api/notebooks
    GET  /api/status/<name>
    GET  /api/logs/<name>
    POST /api/run        JSON: {"notebook": "path"}
    POST /api/upload     multipart/form-data: file=<.ipynb>
"""

import base64
import json
import os
import re
import time
import argparse
from datetime import datetime
from pathlib import Path

import dash
import dash_bootstrap_components as dbc
from dash import (
    ALL, MATCH, Input, Output, State,
    callback_context, dcc, html, no_update,
)
from flask import jsonify, request

# ── Local imports ──────────────────────────────────────────────────────────────
from utils.notebook_runner import runner, execution_history, NOTEBOOKS_DIR, LOGS_DIR
from utils.process_manager import process_mgr

BASE_DIR = Path(__file__).parent
CONFIG_DIR = BASE_DIR / "config"
CONFIG_DIR.mkdir(exist_ok=True)
BUTTONS_FILE = CONFIG_DIR / "custom_buttons.json"

# ── Bootstrap theme (swappable via dark-mode toggle) ──────────────────────────
THEME_LIGHT = dbc.themes.FLATLY
THEME_DARK = dbc.themes.DARKLY

# ── Dash app ───────────────────────────────────────────────────────────────────
app = dash.Dash(
    __name__,
    external_stylesheets=[
        THEME_LIGHT,
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css",
    ],
    suppress_callback_exceptions=True,
    title="Notebook Dashboard",
    update_title=None,
)
server = app.server  # Expose Flask for REST API

# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_buttons() -> list:
    if BUTTONS_FILE.exists():
        try:
            return json.loads(BUTTONS_FILE.read_text())
        except Exception:
            return []
    return []


def _save_buttons(buttons: list):
    BUTTONS_FILE.write_text(json.dumps(buttons, indent=2))


def _status_badge(status: str):
    colours = {
        "idle": "secondary",
        "running": "warning",
        "completed": "success",
        "failed": "danger",
        "stopped": "dark",
    }
    return dbc.Badge(status.capitalize(), color=colours.get(status, "secondary"),
                     className="status-badge")


def _duration(start_iso: str, end_iso: str | None) -> str:
    if not start_iso:
        return "—"
    try:
        s = datetime.fromisoformat(start_iso)
        e = datetime.fromisoformat(end_iso) if end_iso else datetime.now()
        secs = int((e - s).total_seconds())
        return f"{secs // 60}m {secs % 60}s"
    except Exception:
        return "—"


def _notebook_rows(notebooks: list, states: dict) -> list:
    rows = []
    for nb in notebooks:
        path = nb["path"]
        state = states.get(path, {})
        status = state.get("status", "idle")
        progress = state.get("progress", 0)
        duration = _duration(state.get("start_time"), state.get("end_time"))

        rows.append(
            html.Tr(
                [
                    html.Td(dbc.Checkbox(id={"type": "nb-check", "index": path},
                                        value=False, className="nb-checkbox")),
                    html.Td(html.Span([
                        html.I(className="bi bi-journal-code me-2 text-primary"),
                        nb["name"],
                    ], className="nb-name")),
                    html.Td(nb["upload_date"], className="text-muted small"),
                    html.Td(nb["last_modified"], className="text-muted small"),
                    html.Td(nb["size"], className="text-muted small"),
                    html.Td(_status_badge(status)),
                    html.Td(
                        dbc.Progress(
                            value=progress, striped=status == "running",
                            animated=status == "running",
                            color="success" if status == "completed" else
                            "danger" if status == "failed" else "warning",
                            style={"height": "8px", "minWidth": "80px"},
                        ) if status != "idle" else html.Span("—", className="text-muted"),
                    ),
                    html.Td(duration, className="text-muted small"),
                    html.Td([
                        dbc.Button(html.I(className="bi bi-play-fill"), color="success", size="sm",
                                   id={"type": "btn-run-one", "index": path},
                                   className="me-1", title="Run"),
                        dbc.Button(html.I(className="bi bi-eye"), color="info", size="sm",
                                   id={"type": "btn-view-log", "index": path},
                                   className="me-1", title="View Logs"),
                        dbc.Button(html.I(className="bi bi-trash3"), color="danger", size="sm",
                                   id={"type": "btn-del-one", "index": path},
                                   title="Delete"),
                    ], className="d-flex"),
                ],
                className=f"table-row status-{status}",
                id={"type": "nb-row", "index": path},
            )
        )
    return rows


# ── Layout components ──────────────────────────────────────────────────────────

def _sidebar():
    return html.Div(
        id="sidebar",
        className="sidebar",
        children=[
            html.Div([
                html.I(className="bi bi-journal-richtext me-2", style={"fontSize": "1.5rem"}),
                html.Span("NB Dashboard", className="fw-bold fs-5"),
            ], className="sidebar-header d-flex align-items-center p-3 border-bottom"),

            # Summary cards
            html.Div(id="summary-cards", className="p-2"),

            html.Hr(),

            # Navigation
            html.Div([
                dbc.Nav(
                    [
                        dbc.NavLink([html.I(className="bi bi-grid-3x3-gap me-2"), "Notebooks"],
                                    href="#", id="nav-notebooks", active=True,
                                    className="sidebar-nav-link"),
                        dbc.NavLink([html.I(className="bi bi-toggles me-2"), "Custom Buttons"],
                                    href="#", id="nav-buttons", className="sidebar-nav-link"),
                        dbc.NavLink([html.I(className="bi bi-cpu me-2"), "Processes"],
                                    href="#", id="nav-processes", className="sidebar-nav-link"),
                        dbc.NavLink([html.I(className="bi bi-clock-history me-2"), "History"],
                                    href="#", id="nav-history", className="sidebar-nav-link"),
                    ],
                    vertical=True,
                    pills=True,
                ),
            ], className="p-2"),

            html.Hr(),

            # Dark mode toggle
            html.Div([
                html.I(className="bi bi-moon me-2"),
                dbc.Switch(id="dark-mode-toggle", label="Dark Mode", value=False,
                           className="d-inline-block"),
            ], className="p-3 d-flex align-items-center"),

            # System info
            html.Div(id="sys-info", className="p-2 small text-muted"),
        ],
    )


def _toolbar():
    return dbc.Card(
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.InputGroup([
                        dbc.InputGroupText(html.I(className="bi bi-search")),
                        dbc.Input(id="search-input", placeholder="Search notebooks...",
                                  debounce=True, type="search"),
                    ], size="sm"),
                ], width=3),
                dbc.Col([
                    dbc.Input(id="folder-path", placeholder="Load from folder path…",
                              type="text", size="sm"),
                ], width=3),
                dbc.Col([
                    dbc.Button([html.I(className="bi bi-folder2-open me-1"), "Load Folder"],
                               id="btn-load-folder", color="outline-secondary", size="sm",
                               className="me-2"),
                    dbc.Button([html.I(className="bi bi-play-circle-fill me-1"), "Run Selected"],
                               id="btn-run-selected", color="success", size="sm",
                               className="me-2"),
                    dbc.Button([html.I(className="bi bi-skip-forward-fill me-1"), "Run All"],
                               id="btn-run-all", color="primary", size="sm",
                               className="me-2"),
                    dbc.Button([html.I(className="bi bi-stop-circle-fill me-1"), "Stop"],
                               id="btn-stop-all", color="danger", size="sm",
                               className="me-2"),
                    dbc.Button([html.I(className="bi bi-arrow-repeat me-1"), "Retry Failed"],
                               id="btn-retry-failed", color="warning", size="sm"),
                ], width=6, className="d-flex align-items-center"),
            ])
        ]),
        className="mb-3 toolbar-card",
    )


def _upload_zone():
    return dbc.Card([
        dbc.CardHeader([
            html.I(className="bi bi-cloud-upload me-2"),
            "Upload Notebooks",
        ]),
        dbc.CardBody([
            dcc.Upload(
                id="upload-notebook",
                children=html.Div([
                    html.I(className="bi bi-file-earmark-plus",
                           style={"fontSize": "2.5rem", "color": "#6c757d"}),
                    html.P("Drag & Drop .ipynb files here", className="mt-2 mb-1"),
                    html.P("or click to browse", className="text-muted small"),
                ], className="text-center py-3"),
                multiple=True,
                accept=".ipynb",
                className="upload-zone",
            ),
            html.Div(id="upload-status", className="mt-2"),
        ]),
    ], className="mb-3")


def _notebooks_tab():
    return html.Div([
        _toolbar(),
        _upload_zone(),
        dbc.Card([
            dbc.CardHeader([
                html.I(className="bi bi-table me-2"),
                "Notebooks",
                dbc.Badge("0", id="nb-count-badge", color="primary", className="ms-2"),
                dbc.Button([html.I(className="bi bi-arrow-clockwise")],
                           id="btn-refresh", color="link", size="sm",
                           className="ms-auto p-0 float-end"),
            ], className="d-flex align-items-center"),
            dbc.CardBody([
                html.Div(
                    dbc.Table([
                        html.Thead(html.Tr([
                            html.Th("", style={"width": "40px"}),
                            html.Th("Name"),
                            html.Th("Uploaded"),
                            html.Th("Modified"),
                            html.Th("Size"),
                            html.Th("Status"),
                            html.Th("Progress"),
                            html.Th("Duration"),
                            html.Th("Actions"),
                        ])),
                        html.Tbody(id="notebooks-tbody"),
                    ], bordered=False, hover=True, responsive=True,
                       className="notebooks-table align-middle"),
                    className="table-container",
                ),
            ]),
        ]),
    ])


def _custom_buttons_tab():
    return html.Div([
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-plus-circle me-2"),
                        "Create Custom Button",
                    ]),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Button Label"),
                                dbc.Input(id="new-btn-label", placeholder="e.g. Daily Job",
                                          type="text"),
                            ], width=6),
                            dbc.Col([
                                dbc.Label("Color"),
                                dbc.Select(
                                    id="new-btn-color",
                                    options=[
                                        {"label": "Primary (Blue)", "value": "primary"},
                                        {"label": "Success (Green)", "value": "success"},
                                        {"label": "Warning (Yellow)", "value": "warning"},
                                        {"label": "Danger (Red)", "value": "danger"},
                                        {"label": "Info (Cyan)", "value": "info"},
                                        {"label": "Dark", "value": "dark"},
                                    ],
                                    value="primary",
                                ),
                            ], width=6),
                        ], className="mb-2"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Description (optional)"),
                                dbc.Input(id="new-btn-desc", placeholder="What does this button do?",
                                          type="text"),
                            ]),
                        ], className="mb-2"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Notebooks (paths, one per line)"),
                                dbc.Textarea(
                                    id="new-btn-notebooks",
                                    placeholder="notebooks/analysis.ipynb\nnotebooks/report.ipynb",
                                    rows=4,
                                ),
                            ]),
                        ], className="mb-2"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Switch(id="new-btn-sequential", label="Run sequentially",
                                           value=True),
                            ]),
                        ], className="mb-3"),
                        dbc.Button([html.I(className="bi bi-plus-lg me-1"), "Create Button"],
                                   id="btn-create-custom", color="primary"),
                        html.Div(id="create-btn-status", className="mt-2"),
                    ]),
                ]),
            ], width=5),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([html.I(className="bi bi-collection me-2"), "Custom Buttons"]),
                    dbc.CardBody(html.Div(id="custom-buttons-container")),
                ]),
            ], width=7),
        ]),
    ])


def _process_tab():
    return html.Div([
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([html.I(className="bi bi-cpu me-2"), "System Resources"]),
                    dbc.CardBody(html.Div(id="sys-resources")),
                ]),
            ], width=4),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-activity me-2"),
                        "Jupyter Processes",
                        dbc.Button([html.I(className="bi bi-x-octagon-fill me-1"),
                                    "Kill All Jupyter"],
                                   id="btn-kill-all", color="danger", size="sm",
                                   className="ms-auto float-end"),
                    ], className="d-flex align-items-center"),
                    dbc.CardBody([
                        html.Div(id="process-table-container"),
                        dbc.Button([html.I(className="bi bi-trash3 me-1"), "Kill Selected"],
                                   id="btn-kill-selected", color="warning", size="sm",
                                   className="mt-2"),
                        html.Div(id="kill-status", className="mt-2"),
                    ]),
                ]),
            ], width=8),
        ]),
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Auto-timeout Settings"),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label("Global timeout (minutes)"),
                                dbc.Input(id="timeout-input", type="number", value=60,
                                          min=1, max=1440),
                            ], width=4),
                            dbc.Col([
                                dbc.Label("Kill idle kernels after (minutes)"),
                                dbc.Input(id="idle-timeout-input", type="number", value=30,
                                          min=5, max=240),
                            ], width=4),
                            dbc.Col([
                                dbc.Button([html.I(className="bi bi-power me-1"),
                                            "Kill Idle Kernels"],
                                           id="btn-kill-idle", color="outline-warning",
                                           className="mt-4"),
                                html.Div(id="idle-kill-status", className="mt-1 small"),
                            ], width=4),
                        ]),
                    ]),
                ], className="mt-3"),
            ]),
        ]),
    ])


def _history_tab():
    return html.Div([
        dbc.Card([
            dbc.CardHeader([
                html.I(className="bi bi-clock-history me-2"),
                "Execution History",
                dbc.Button([html.I(className="bi bi-trash3")], id="btn-clear-history",
                           color="link", size="sm", className="ms-auto float-end text-danger"),
            ], className="d-flex align-items-center"),
            dbc.CardBody(html.Div(id="history-table-container")),
        ]),
    ])


def _log_panel():
    return dbc.Card([
        dbc.CardHeader([
            html.Div([
                html.I(className="bi bi-terminal me-2"),
                html.Span("Live Logs", className="fw-semibold"),
                dbc.Select(
                    id="log-notebook-select",
                    placeholder="Select notebook…",
                    size="sm",
                    className="ms-3",
                    style={"width": "220px", "display": "inline-block"},
                ),
            ], className="d-flex align-items-center"),
            html.Div([
                dbc.Button([html.I(className="bi bi-eraser me-1"), "Clear"],
                           id="btn-clear-logs", color="outline-secondary", size="sm",
                           className="me-2"),
                dbc.Button([html.I(className="bi bi-download me-1"), "Download"],
                           id="btn-download-logs", color="outline-primary", size="sm"),
                dcc.Download(id="download-log-file"),
            ], className="d-flex align-items-center"),
        ], className="d-flex align-items-center justify-content-between"),
        dbc.CardBody([
            html.Pre(
                id="log-output",
                className="log-window",
                children="Select a notebook to view its logs…",
            ),
        ], className="p-0"),
    ], className="log-panel mt-3")


# ── Root layout ────────────────────────────────────────────────────────────────

app.layout = html.Div(
    id="app-wrapper",
    className="app-wrapper light-mode",
    children=[
        # Hidden stores
        dcc.Store(id="store-dark-mode", data=False),
        dcc.Store(id="store-folder-path", data=str(NOTEBOOKS_DIR)),
        dcc.Store(id="store-active-tab", data="notebooks"),
        dcc.Store(id="store-selected-log-nb", data=None),
        dcc.Store(id="store-log-cleared", data=0),   # increment to clear display
        dcc.Store(id="store-selected-processes", data=[]),
        dcc.Store(id="store-history-cleared", data=0),

        # Polling intervals
        dcc.Interval(id="interval-fast", interval=2_000, n_intervals=0),   # 2 s
        dcc.Interval(id="interval-slow", interval=10_000, n_intervals=0),  # 10 s

        # Toast notification
        html.Div(id="toast-container",
                 style={"position": "fixed", "top": 20, "right": 20, "zIndex": 9999}),

        # Main layout
        dbc.Row([
            dbc.Col(_sidebar(), width=2, className="p-0"),
            dbc.Col([
                # Top navbar
                dbc.Navbar(
                    dbc.Container([
                        html.Span("Jupyter Notebook Dashboard",
                                  className="navbar-brand fw-bold"),
                        html.Span(id="navbar-clock",
                                  className="ms-auto text-muted small"),
                    ], fluid=True),
                    color="primary",
                    dark=True,
                    className="mb-3 top-navbar",
                ),
                # Tab content
                html.Div(id="main-content", className="px-3"),
                # Log panel (always visible at bottom)
                html.Div(_log_panel(), className="px-3 pb-3"),
            ], width=10, className="p-0 main-col"),
        ], className="g-0 vh-100"),

        # Confirm dialog
        dcc.ConfirmDialog(id="confirm-delete", message="Delete this notebook?"),
        dcc.Store(id="store-pending-delete", data=None),
    ],
)


# ══════════════════════════════════════════════════════════════════════════════
# Callbacks
# ══════════════════════════════════════════════════════════════════════════════

# ── Dark mode ─────────────────────────────────────────────────────────────────
@app.callback(
    Output("app-wrapper", "className"),
    Input("dark-mode-toggle", "value"),
)
def toggle_dark_mode(dark):
    return "app-wrapper dark-mode" if dark else "app-wrapper light-mode"


# ── Clock ─────────────────────────────────────────────────────────────────────
@app.callback(
    Output("navbar-clock", "children"),
    Input("interval-fast", "n_intervals"),
)
def update_clock(_):
    return datetime.now().strftime("%A, %d %b %Y  %H:%M:%S")


# ── Active tab switching ──────────────────────────────────────────────────────
@app.callback(
    Output("main-content", "children"),
    Output("store-active-tab", "data"),
    Input("nav-notebooks", "n_clicks"),
    Input("nav-buttons", "n_clicks"),
    Input("nav-processes", "n_clicks"),
    Input("nav-history", "n_clicks"),
    State("store-active-tab", "data"),
    prevent_initial_call=False,
)
def switch_tab(nb_clicks, btn_clicks, proc_clicks, hist_clicks, current_tab):
    ctx = callback_context
    if not ctx.triggered:
        return _notebooks_tab(), "notebooks"
    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
    mapping = {
        "nav-notebooks": ("notebooks", _notebooks_tab()),
        "nav-buttons": ("buttons", _custom_buttons_tab()),
        "nav-processes": ("processes", _process_tab()),
        "nav-history": ("history", _history_tab()),
    }
    tab_name, tab_content = mapping.get(trigger_id, ("notebooks", _notebooks_tab()))
    return tab_content, tab_name


# ── File upload ───────────────────────────────────────────────────────────────
@app.callback(
    Output("upload-status", "children"),
    Input("upload-notebook", "contents"),
    State("upload-notebook", "filename"),
    prevent_initial_call=True,
)
def handle_upload(contents_list, filenames):
    if not contents_list:
        return no_update
    messages = []
    for content, name in zip(contents_list, filenames):
        if not name.endswith(".ipynb"):
            messages.append(dbc.Alert(f"⚠ {name} — not a .ipynb file", color="warning",
                                      dismissable=True))
            continue
        dest = NOTEBOOKS_DIR / name
        if dest.exists():
            messages.append(dbc.Alert(f"⚠ {name} already exists (overwritten)",
                                      color="warning", dismissable=True))
        try:
            _, b64 = content.split(",", 1)
            data = base64.b64decode(b64)
            # Validate JSON
            json.loads(data)
            dest.write_bytes(data)
            messages.append(dbc.Alert(
                [html.I(className="bi bi-check-circle me-2"), f"{name} uploaded successfully"],
                color="success", dismissable=True,
            ))
        except Exception as exc:
            messages.append(dbc.Alert(f"✗ {name} — {exc}", color="danger", dismissable=True))
    return messages


# ── Notebook table ────────────────────────────────────────────────────────────
@app.callback(
    Output("notebooks-tbody", "children"),
    Output("nb-count-badge", "children"),
    Output("log-notebook-select", "options"),
    Output("summary-cards", "children"),
    Input("interval-fast", "n_intervals"),
    Input("btn-refresh", "n_clicks"),
    Input("upload-status", "children"),        # refresh after upload
    Input("btn-load-folder", "n_clicks"),
    State("store-folder-path", "data"),
    State("search-input", "value"),
    prevent_initial_call=False,
)
def update_notebooks_table(_, _r, _up, _lf, folder_path, search):
    notebooks = runner.get_notebooks(folder_path)
    states = runner.get_all_states()

    # Filter by search
    if search:
        q = search.lower()
        notebooks = [n for n in notebooks if q in n["name"].lower()]

    rows = _notebook_rows(notebooks, states)

    # Summary counts
    statuses = [states.get(n["path"], {}).get("status", "idle") for n in notebooks]
    total = len(notebooks)
    running = statuses.count("running")
    completed = statuses.count("completed")
    failed = statuses.count("failed")

    cards = dbc.Row([
        dbc.Col(_mini_card("Total", total, "bi-journals", "primary"), width=6),
        dbc.Col(_mini_card("Running", running, "bi-play-circle", "warning"), width=6),
        dbc.Col(_mini_card("Done", completed, "bi-check-circle", "success"), width=6),
        dbc.Col(_mini_card("Failed", failed, "bi-x-circle", "danger"), width=6),
    ], className="g-1")

    options = [{"label": n["name"], "value": n["path"]} for n in notebooks]
    return rows, str(total), options, cards


def _mini_card(label, value, icon, color):
    return dbc.Card(
        dbc.CardBody([
            html.I(className=f"bi {icon} me-1 text-{color}"),
            html.Span(str(value), className=f"fw-bold text-{color}"),
            html.Br(),
            html.Span(label, className="small text-muted"),
        ], className="p-2 text-center"),
        className="mb-1",
    )


# ── Run one notebook (row action button) ─────────────────────────────────────
@app.callback(
    Output("toast-container", "children", allow_duplicate=True),
    Input({"type": "btn-run-one", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def run_one(n_clicks_list):
    ctx = callback_context
    if not ctx.triggered:
        return no_update
    prop = ctx.triggered[0]["prop_id"]
    match = re.search(r'"index":"([^"]+)"', prop)
    if not match:
        return no_update
    nb_path = match.group(1)
    if not any(n_clicks_list):
        return no_update
    runner.run_notebook(nb_path)
    return _toast(f"Started: {Path(nb_path).name}", "success")


# ── Run selected ─────────────────────────────────────────────────────────────
@app.callback(
    Output("toast-container", "children", allow_duplicate=True),
    Input("btn-run-selected", "n_clicks"),
    State({"type": "nb-check", "index": ALL}, "value"),
    State({"type": "nb-check", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def run_selected(n, check_values, check_ids):
    if not n:
        return no_update
    selected = [cid["index"] for cid, val in zip(check_ids, check_values) if val]
    if not selected:
        return _toast("No notebooks selected", "warning")
    for path in selected:
        runner.run_notebook(path)
    return _toast(f"Started {len(selected)} notebook(s)", "success")


# ── Run all ───────────────────────────────────────────────────────────────────
@app.callback(
    Output("toast-container", "children", allow_duplicate=True),
    Input("btn-run-all", "n_clicks"),
    State("store-folder-path", "data"),
    prevent_initial_call=True,
)
def run_all(n, folder_path):
    if not n:
        return no_update
    notebooks = runner.get_notebooks(folder_path)
    for nb in notebooks:
        runner.run_notebook(nb["path"])
    return _toast(f"Started all {len(notebooks)} notebooks", "primary")


# ── Stop all ─────────────────────────────────────────────────────────────────
@app.callback(
    Output("toast-container", "children", allow_duplicate=True),
    Input("btn-stop-all", "n_clicks"),
    State("store-folder-path", "data"),
    prevent_initial_call=True,
)
def stop_all(n, folder_path):
    if not n:
        return no_update
    states = runner.get_all_states()
    count = 0
    for path, state in states.items():
        if state.get("status") == "running":
            runner.stop_notebook(path)
            count += 1
    return _toast(f"Stopped {count} notebook(s)", "danger")


# ── Retry failed ─────────────────────────────────────────────────────────────
@app.callback(
    Output("toast-container", "children", allow_duplicate=True),
    Input("btn-retry-failed", "n_clicks"),
    State("store-folder-path", "data"),
    prevent_initial_call=True,
)
def retry_failed(n, folder_path):
    if not n:
        return no_update
    states = runner.get_all_states()
    count = 0
    for path, state in states.items():
        if state.get("status") in ("failed", "stopped"):
            runner.retry_failed(path)
            count += 1
    return _toast(f"Retrying {count} notebook(s)", "warning") if count else \
           _toast("No failed notebooks to retry", "info")


# ── Delete notebook ───────────────────────────────────────────────────────────
@app.callback(
    Output("confirm-delete", "displayed"),
    Output("store-pending-delete", "data"),
    Input({"type": "btn-del-one", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def request_delete(n_clicks_list):
    ctx = callback_context
    if not ctx.triggered or not any(c for c in n_clicks_list if c):
        return False, no_update
    prop = ctx.triggered[0]["prop_id"]
    match = re.search(r'"index":"([^"]+)"', prop)
    if not match:
        return False, no_update
    return True, match.group(1)


@app.callback(
    Output("toast-container", "children", allow_duplicate=True),
    Input("confirm-delete", "submit_n_clicks"),
    State("store-pending-delete", "data"),
    prevent_initial_call=True,
)
def confirm_delete(submit_n, nb_path):
    if not submit_n or not nb_path:
        return no_update
    runner.delete_notebook(nb_path)
    return _toast(f"Deleted: {Path(nb_path).name}", "danger")


# ── Load folder ───────────────────────────────────────────────────────────────
@app.callback(
    Output("store-folder-path", "data"),
    Output("toast-container", "children", allow_duplicate=True),
    Input("btn-load-folder", "n_clicks"),
    State("folder-path", "value"),
    prevent_initial_call=True,
)
def load_folder(n, folder_path):
    if not n or not folder_path:
        return no_update, no_update
    p = Path(folder_path)
    if not p.exists():
        return no_update, _toast(f"Folder not found: {folder_path}", "danger")
    return str(p), _toast(f"Loaded folder: {p.name}", "success")


# ── View log for row ──────────────────────────────────────────────────────────
@app.callback(
    Output("store-selected-log-nb", "data"),
    Output("log-notebook-select", "value"),
    Input({"type": "btn-view-log", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_log_nb(n_clicks_list):
    ctx = callback_context
    if not ctx.triggered or not any(c for c in n_clicks_list if c):
        return no_update, no_update
    prop = ctx.triggered[0]["prop_id"]
    match = re.search(r'"index":"([^"]+)"', prop)
    if not match:
        return no_update, no_update
    path = match.group(1)
    return path, path


# ── Live logs ─────────────────────────────────────────────────────────────────
@app.callback(
    Output("log-output", "children"),
    Input("interval-fast", "n_intervals"),
    Input("btn-clear-logs", "n_clicks"),
    Input("log-notebook-select", "value"),
    Input("store-selected-log-nb", "data"),
    State("store-log-cleared", "data"),
    prevent_initial_call=False,
)
def update_logs(_, clear_n, selected_dropdown, selected_store, _cleared):
    ctx = callback_context
    if ctx.triggered and ctx.triggered[0]["prop_id"] == "btn-clear-logs.n_clicks":
        return "Logs cleared."

    nb_path = selected_dropdown or selected_store
    if not nb_path:
        return "Select a notebook to view its logs…"

    lines = runner.get_log_lines(nb_path, last_n=300)
    if not lines:
        return f"No logs yet for {Path(nb_path).name}"

    # Colour error lines red, warnings orange
    spans = []
    for line in lines:
        line = line.rstrip("\n")
        if any(k in line.lower() for k in ("error", "failed", "traceback", "exception")):
            spans.append(html.Span(line + "\n", style={"color": "#ff6b6b"}))
        elif any(k in line.lower() for k in ("warning", "warn")):
            spans.append(html.Span(line + "\n", style={"color": "#ffd43b"}))
        else:
            spans.append(line + "\n")
    return spans


# ── Download logs ─────────────────────────────────────────────────────────────
@app.callback(
    Output("download-log-file", "data"),
    Input("btn-download-logs", "n_clicks"),
    State("log-notebook-select", "value"),
    State("store-selected-log-nb", "data"),
    prevent_initial_call=True,
)
def download_logs(n, selected_dropdown, selected_store):
    if not n:
        return no_update
    nb_path = selected_dropdown or selected_store
    if not nb_path:
        return no_update
    lines = runner.get_log_lines(nb_path, last_n=10000)
    content = "".join(lines)
    filename = f"{Path(nb_path).stem}_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    return dcc.send_string(content, filename)


# ── Custom buttons ────────────────────────────────────────────────────────────
@app.callback(
    Output("custom-buttons-container", "children"),
    Output("create-btn-status", "children"),
    Input("btn-create-custom", "n_clicks"),
    Input("interval-slow", "n_intervals"),
    State("new-btn-label", "value"),
    State("new-btn-color", "value"),
    State("new-btn-desc", "value"),
    State("new-btn-notebooks", "value"),
    State("new-btn-sequential", "value"),
    prevent_initial_call=False,
)
def manage_custom_buttons(create_n, _, label, color, desc, nb_text, sequential):
    ctx = callback_context
    status_msg = no_update

    if ctx.triggered and ctx.triggered[0]["prop_id"] == "btn-create-custom.n_clicks":
        if not label:
            return no_update, dbc.Alert("Button label is required", color="warning",
                                        dismissable=True)
        notebooks = [l.strip() for l in (nb_text or "").splitlines() if l.strip()]
        buttons = _load_buttons()
        new_btn = {
            "id": f"btn_{int(time.time())}",
            "label": label,
            "icon": "bi bi-play-fill",
            "color": color or "primary",
            "notebooks": notebooks,
            "sequential": sequential,
            "description": desc or "",
        }
        buttons.append(new_btn)
        _save_buttons(buttons)
        status_msg = dbc.Alert(
            [html.I(className="bi bi-check-circle me-2"), f'Button "{label}" created!'],
            color="success", dismissable=True,
        )

    buttons = _load_buttons()
    if not buttons:
        return html.P("No custom buttons yet. Create one →", className="text-muted"), status_msg

    btn_elements = []
    for btn in buttons:
        btn_elements.append(
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.H6([
                                html.I(className=f"{btn.get('icon', 'bi bi-play')} me-2"),
                                btn["label"],
                            ]),
                            html.P(btn.get("description", ""), className="text-muted small mb-1"),
                            html.P(
                                f"{len(btn.get('notebooks', []))} notebook(s) · "
                                f"{'Sequential' if btn.get('sequential') else 'Parallel'}",
                                className="small",
                            ),
                        ], width=8),
                        dbc.Col([
                            dbc.Button(
                                [html.I(className="bi bi-play-fill me-1"), "Run"],
                                id={"type": "custom-btn-run", "index": btn["id"]},
                                color=btn.get("color", "primary"),
                                size="sm",
                                className="me-1",
                            ),
                            dbc.Button(
                                html.I(className="bi bi-trash3"),
                                id={"type": "custom-btn-del", "index": btn["id"]},
                                color="outline-danger",
                                size="sm",
                            ),
                        ], width=4, className="text-end d-flex align-items-start justify-content-end"),
                    ]),
                ]),
            ], className="mb-2 custom-btn-card")
        )
    return btn_elements, status_msg


@app.callback(
    Output("toast-container", "children", allow_duplicate=True),
    Input({"type": "custom-btn-run", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def run_custom_button(n_clicks_list):
    ctx = callback_context
    if not ctx.triggered or not any(c for c in n_clicks_list if c):
        return no_update
    prop = ctx.triggered[0]["prop_id"]
    match = re.search(r'"index":"([^"]+)"', prop)
    if not match:
        return no_update
    btn_id = match.group(1)
    buttons = _load_buttons()
    btn = next((b for b in buttons if b["id"] == btn_id), None)
    if not btn:
        return _toast("Button not found", "danger")
    notebooks = btn.get("notebooks", [])
    if not notebooks:
        return _toast("No notebooks configured for this button", "warning")
    runner.run_multiple(notebooks, sequential=btn.get("sequential", False))
    return _toast(f"'{btn['label']}' started {len(notebooks)} notebook(s)", "success")


@app.callback(
    Output("toast-container", "children", allow_duplicate=True),
    Input({"type": "custom-btn-del", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def delete_custom_button(n_clicks_list):
    ctx = callback_context
    if not ctx.triggered or not any(c for c in n_clicks_list if c):
        return no_update
    prop = ctx.triggered[0]["prop_id"]
    match = re.search(r'"index":"([^"]+)"', prop)
    if not match:
        return no_update
    btn_id = match.group(1)
    buttons = _load_buttons()
    buttons = [b for b in buttons if b["id"] != btn_id]
    _save_buttons(buttons)
    return _toast("Button deleted", "secondary")


# ── Process manager ───────────────────────────────────────────────────────────
@app.callback(
    Output("process-table-container", "children"),
    Output("sys-resources", "children"),
    Output("sys-info", "children"),
    Input("interval-slow", "n_intervals"),
    prevent_initial_call=False,
)
def update_processes(_):
    procs = process_mgr.list_processes()
    summary = process_mgr.system_summary()

    # System resources card content
    res_content = [
        dbc.Progress(value=summary.get("cpu_pct", 0), label=f"CPU {summary.get('cpu_pct', 0):.0f}%",
                     color="info", className="mb-2", style={"height": "20px"}),
        dbc.Progress(value=summary.get("mem_pct", 0),
                     label=f"RAM {summary.get('mem_used_gb', 0):.1f}/{summary.get('mem_total_gb', 0):.1f} GB",
                     color="warning", style={"height": "20px"}),
        html.P(f"Jupyter processes: {summary.get('jupyter_count', 0)}",
               className="mt-2 small text-muted"),
    ]

    # Sidebar sys-info
    sidebar_info = [
        html.Div(f"CPU: {summary.get('cpu_pct', 0):.0f}%"),
        html.Div(f"RAM: {summary.get('mem_pct', 0):.0f}%"),
    ]

    if not procs or "error" in (procs[0] if procs else {}):
        return (html.P("psutil not available — install it for process monitoring",
                       className="text-muted"),
                res_content, sidebar_info)

    if not procs:
        return html.P("No Jupyter processes detected.", className="text-muted"), res_content, sidebar_info

    rows = []
    for p in procs:
        rows.append(html.Tr([
            html.Td(dbc.Checkbox(id={"type": "proc-check", "index": str(p["pid"])},
                                 value=False)),
            html.Td(str(p["pid"])),
            html.Td(p.get("name", "?")),
            html.Td(p.get("status", "?")),
            html.Td(f"{p.get('cpu_pct', 0)}%"),
            html.Td(f"{p.get('mem_mb', 0)} MB"),
            html.Td(f"{p.get('elapsed_min', 0)} min"),
            html.Td(html.Small(p.get("cmdline", ""), className="text-muted",
                               style={"maxWidth": "200px", "display": "block",
                                      "overflow": "hidden", "textOverflow": "ellipsis",
                                      "whiteSpace": "nowrap"})),
        ]))

    table = dbc.Table(
        [
            html.Thead(html.Tr([html.Th(""), html.Th("PID"), html.Th("Name"),
                                html.Th("Status"), html.Th("CPU"), html.Th("Memory"),
                                html.Th("Uptime"), html.Th("Command")])),
            html.Tbody(rows),
        ],
        bordered=False, hover=True, responsive=True, size="sm",
    )
    return table, res_content, sidebar_info


@app.callback(
    Output("kill-status", "children"),
    Input("btn-kill-selected", "n_clicks"),
    State({"type": "proc-check", "index": ALL}, "value"),
    State({"type": "proc-check", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def kill_selected_procs(n, values, ids):
    if not n:
        return no_update
    pids = [int(pid_id["index"]) for pid_id, val in zip(ids, values) if val]
    if not pids:
        return dbc.Alert("No processes selected", color="warning", dismissable=True)
    results = process_mgr.kill_processes(pids)
    killed = sum(1 for v in results.values() if v)
    return dbc.Alert(f"Killed {killed}/{len(pids)} process(es)", color="success", dismissable=True)


@app.callback(
    Output("toast-container", "children", allow_duplicate=True),
    Input("btn-kill-all", "n_clicks"),
    prevent_initial_call=True,
)
def kill_all_jupyter(n):
    if not n:
        return no_update
    count = process_mgr.kill_all_jupyter()
    return _toast(f"Killed {count} Jupyter process(es)", "danger")


@app.callback(
    Output("idle-kill-status", "children"),
    Input("btn-kill-idle", "n_clicks"),
    State("idle-timeout-input", "value"),
    prevent_initial_call=True,
)
def kill_idle(n, threshold):
    if not n:
        return no_update
    count = process_mgr.kill_idle_kernels(float(threshold or 30))
    return dbc.Alert(f"Killed {count} idle kernel(s)", color="success", dismissable=True)


# ── Execution history ─────────────────────────────────────────────────────────
@app.callback(
    Output("history-table-container", "children"),
    Input("interval-slow", "n_intervals"),
    Input("btn-clear-history", "n_clicks"),
    prevent_initial_call=False,
)
def update_history(_, clear_n):
    ctx = callback_context
    if ctx.triggered and ctx.triggered[0]["prop_id"] == "btn-clear-history.n_clicks":
        execution_history.clear()

    if not execution_history:
        return html.P("No execution history yet.", className="text-muted")

    rows = []
    for h in reversed(execution_history[-100:]):
        status = h.get("status", "?")
        badge = _status_badge(status)
        duration = _duration(h.get("start_time"), h.get("end_time"))
        rows.append(html.Tr([
            html.Td(h.get("notebook", "?")),
            html.Td(badge),
            html.Td(h.get("start_time", "?")[:19].replace("T", " ")),
            html.Td(duration),
            html.Td(h.get("error", "") or "—", className="text-danger small"),
        ]))

    return dbc.Table(
        [
            html.Thead(html.Tr([html.Th("Notebook"), html.Th("Status"),
                                html.Th("Started"), html.Th("Duration"), html.Th("Error")])),
            html.Tbody(rows),
        ],
        bordered=False, hover=True, responsive=True, size="sm",
    )


# ── Toast helper ──────────────────────────────────────────────────────────────
def _toast(msg: str, color: str = "primary"):
    return dbc.Toast(
        msg,
        header="Notebook Dashboard",
        is_open=True,
        dismissable=True,
        duration=4000,
        color=color,
        style={"minWidth": "280px"},
    )


# ══════════════════════════════════════════════════════════════════════════════
# REST API  (Flask routes on the Dash server)
# ══════════════════════════════════════════════════════════════════════════════

@server.route("/api/notebooks")
def api_notebooks():
    folder = request.args.get("folder", str(NOTEBOOKS_DIR))
    notebooks = runner.get_notebooks(folder)
    states = runner.get_all_states()
    for nb in notebooks:
        nb["state"] = {k: v for k, v in states.get(nb["path"], {}).items()
                       if k not in ("_thread",)}
    return jsonify(notebooks)


@server.route("/api/status/<path:name>")
def api_status(name):
    notebooks = runner.get_notebooks()
    nb = next((n for n in notebooks if n["name"] == name or n["path"].endswith(name)), None)
    if not nb:
        return jsonify({"error": "not found"}), 404
    return jsonify(runner.get_state(nb["path"]))


@server.route("/api/logs/<path:name>")
def api_logs(name):
    notebooks = runner.get_notebooks()
    nb = next((n for n in notebooks if n["name"] == name or n["path"].endswith(name)), None)
    if not nb:
        return jsonify({"error": "not found"}), 404
    lines = runner.get_log_lines(nb["path"], last_n=500)
    return jsonify({"notebook": nb["name"], "lines": lines})


@server.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json(silent=True) or {}
    nb_path = data.get("notebook")
    if not nb_path:
        return jsonify({"error": "notebook path required"}), 400
    if not Path(nb_path).exists():
        return jsonify({"error": "file not found"}), 404
    ok = runner.run_notebook(nb_path, timeout=data.get("timeout", 3600))
    return jsonify({"started": ok, "notebook": nb_path})


@server.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "no file provided"}), 400
    f = request.files["file"]
    if not f.filename.endswith(".ipynb"):
        return jsonify({"error": "only .ipynb files accepted"}), 400
    dest = NOTEBOOKS_DIR / f.filename
    try:
        data = f.read()
        json.loads(data)   # validate JSON
        dest.write_bytes(data)
        return jsonify({"uploaded": f.filename, "path": str(dest)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@server.route("/api/stop", methods=["POST"])
def api_stop():
    data = request.get_json(silent=True) or {}
    nb_path = data.get("notebook")
    if not nb_path:
        return jsonify({"error": "notebook path required"}), 400
    ok = runner.stop_notebook(nb_path)
    return jsonify({"stopped": ok})


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jupyter Notebook Dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Host address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8050, help="Port number (default: 8050)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    # Start process watchdog
    process_mgr.start_watchdog(runner)

    print(f"""
╔══════════════════════════════════════════════╗
║       Jupyter Notebook Dashboard             ║
║  URL: http://{args.host}:{args.port:<28} ║
║  Press Ctrl+C to stop                        ║
╚══════════════════════════════════════════════╝
""")

    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug,
        use_reloader=False,   # avoid double-starting background threads
    )
