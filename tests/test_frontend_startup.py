"""Regression coverage for Streamlit's direct-file import context."""

import subprocess
import sys
from pathlib import Path


def test_app_imports_when_repository_root_is_not_on_initial_python_path():
    app_path = Path(__file__).resolve().parents[1] / "frontend" / "app.py"
    script = (
        "import runpy, sys\n"
        f"sys.path.insert(0, {str(app_path.parent)!r})\n"
        f"runpy.run_path({str(app_path)!r}, run_name='startup_import_check')\n"
    )

    subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=app_path.parent.parent,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
