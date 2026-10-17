"""Run host/UI backend coverage on macOS, Linux, and native Windows.

The complete suite additionally exercises POSIX receiver programs that execute
on Zeus. Those receiver fixtures remain covered by the full Linux/macOS suite.
"""
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(
    r'^test_(platform_io|repository_paths|run_|individual_run|'
    r'zeeman_(individual|local|run_)|mot_[23]d_(individual|local|run_)|'
    r'mot_3d_campaign|workflow_api|workflow_error_catalog|pinned_ssh|'
    r'config_and_imports|thermal_beam|hybrid_stochastic_solver|simulation_progress)'
)
files = sorted(str(p.relative_to(ROOT)) for p in (ROOT / 'tests').glob('test_*.py') if PATTERN.match(p.stem))
environment = os.environ.copy()
environment['MPLBACKEND'] = 'Agg'
raise SystemExit(subprocess.call([sys.executable, '-m', 'pytest', '-q', '-ra', '--tb=short', *files, *sys.argv[1:]], cwd=ROOT, env=environment))
