"""Regressions for the workflow validation failure before any CI job started."""

from pathlib import Path
import os
import re
import shutil
import subprocess

import pytest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/tests.yml"


def test_job_environment_does_not_use_runner_context():
    # GitHub permits runner context in steps, but rejects it in jobs.<id>.env.
    # Restrict this guard to the workflow's two-space job/four-space key layout.
    in_job_env = False
    for line in WORKFLOW.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            indent = len(line) - len(line.lstrip())
            if indent <= 4:
                in_job_env = line == "    env:"
            if in_job_env:
                assert not re.search(r"\$\{\{\s*runner\.", line), line


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="Ubuntu bootstrap requires a POSIX bash host",
)
def test_bytecode_environment_bootstrap_handles_paths_with_spaces(tmp_path):
    workflow = WORKFLOW.read_text()
    match = re.search(
        r"      - name: Keep Python bytecode outside the checkout\n"
        r"        run: ([^\n]+)",
        workflow,
    )
    assert match is not None
    runner_temp = tmp_path / "runner temp"
    runner_temp.mkdir()
    env_file = tmp_path / "github environment"
    subprocess.run(
        [shutil.which("bash"), "-eu", "-c", match.group(1)],
        env={"RUNNER_TEMP": str(runner_temp), "GITHUB_ENV": str(env_file)},
        check=True,
        timeout=10,
    )
    assert env_file.read_text() == f"PYTHONPYCACHEPREFIX={runner_temp}/pycache\n"
    assert workflow.index(match.group(0)) < workflow.index("      - name: Set up Python")


def test_full_backend_suite_budget_preserves_selection_and_other_job_limits():
    workflow = WORKFLOW.read_text()
    jobs_text = workflow.split("\njobs:\n", 1)[1]
    jobs = dict(re.findall(
        r"^  ([a-z][a-z0-9-]*):\n(.*?)(?=^  [a-z][a-z0-9-]*:|\Z)",
        jobs_text, re.MULTILINE | re.DOTALL,
    ))
    assert set(jobs) == {"test", "frontend-checks", "frontend-browser", "host-compatibility"}
    expected_timeouts = {
        "test": "90", "frontend-checks": "15",
        "frontend-browser": "25", "host-compatibility": "25",
    }
    for name, expected in expected_timeouts.items():
        assert re.findall(r"^    timeout-minutes: (\d+)$", jobs[name], re.MULTILINE) == [expected]
    complete = re.search(
        r"      - name: Run complete test suite\n(?:        #[^\n]*\n)*"
        r"        run: ([^\n]+)", jobs["test"],
    )
    assert complete is not None
    # No file list, -k/-m, ignore, or skip filters: all collected tests execute
    # on a green run; the existing first-failure diagnostics remain unchanged.
    assert complete.group(1) == "python -m pytest -x -vv --tb=short"
    assert "PYTEST_ADDOPTS" not in jobs["test"]
