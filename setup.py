"""
setup.py — One-shot environment bootstrap for Notebook Dashboard
Run: python setup.py
"""

import subprocess
import sys
from pathlib import Path


def run(cmd: list, **kw):
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, **kw)
    if result.returncode != 0:
        print(f"  [WARN] Command exited with code {result.returncode}")
    return result


def main():
    print("=" * 55)
    print("  Notebook Dashboard — Environment Setup")
    print("=" * 55)

    # ── Create directories ──────────────────────────────
    dirs = ["notebooks", "logs", "config", "assets"]
    for d in dirs:
        Path(d).mkdir(exist_ok=True)
        print(f"  [ok] Directory: {d}/")

    # ── Install dependencies ────────────────────────────
    print("\n[1/3] Installing Python dependencies...")
    run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"])

    # ── Verify critical imports ─────────────────────────
    print("\n[2/3] Verifying installations...")
    checks = {
        "dash": "Dash",
        "dash_bootstrap_components": "Dash Bootstrap Components",
        "papermill": "Papermill",
        "psutil": "psutil",
        "nbconvert": "nbconvert",
    }
    all_ok = True
    for module, label in checks.items():
        try:
            __import__(module)
            print(f"  [ok] {label}")
        except ImportError:
            print(f"  [!!] {label} — NOT installed (run: pip install {module})")
            all_ok = False

    # ── Create sample notebook ──────────────────────────
    print("\n[3/3] Creating sample notebooks...")
    _create_sample_notebooks()

    print("\n" + "=" * 55)
    if all_ok:
        print("  Setup complete!  Run: python app.py")
    else:
        print("  Setup done with warnings. Check items above.")
    print("  Dashboard URL: http://localhost:8050")
    print("=" * 55)


def _create_sample_notebooks():
    import json

    samples = {
        "sample_hello.ipynb": {
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": ["# Sample Hello Notebook\nThis is a test notebook for the dashboard."]
                },
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": ["import time\nprint('Starting sample notebook...')\n"]
                },
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": [
                        "for i in range(1, 6):\n",
                        "    print(f'Step {i}/5 — processing...')\n",
                        "    time.sleep(1)\n"
                    ]
                },
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": ["print('Done! Notebook executed successfully.')"]
                },
            ],
            "metadata": {
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3"
                },
                "language_info": {"name": "python", "version": "3.x"}
            },
            "nbformat": 4,
            "nbformat_minor": 5
        },
        "sample_data_report.ipynb": {
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": ["# Data Report Notebook\nDemonstrates data processing with pandas."]
                },
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": [
                        "import time\n",
                        "import random\n",
                        "print('Loading data...')\n",
                        "time.sleep(0.5)\n"
                    ]
                },
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": [
                        "data = [random.gauss(50, 15) for _ in range(100)]\n",
                        "mean_val = sum(data) / len(data)\n",
                        "print(f'Dataset: {len(data)} rows, mean={mean_val:.2f}')\n",
                        "time.sleep(0.5)\n"
                    ]
                },
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": [
                        "print('Generating report...')\n",
                        "time.sleep(0.5)\n",
                        "print('Report complete.')\n"
                    ]
                },
            ],
            "metadata": {
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3"
                },
                "language_info": {"name": "python", "version": "3.x"}
            },
            "nbformat": 4,
            "nbformat_minor": 5
        },
    }

    nb_dir = Path("notebooks")
    for name, content in samples.items():
        dest = nb_dir / name
        if not dest.exists():
            dest.write_text(json.dumps(content, indent=2))
            print(f"  [ok] Created: notebooks/{name}")
        else:
            print(f"  [--] Skipped (exists): notebooks/{name}")


if __name__ == "__main__":
    main()
