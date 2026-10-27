"""A fresh receiver process must accept valid retained products, including zero rows."""
import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from workflow_api.platform_io import executable
from workflow_api.run_records import encode_record


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX receiver executes on Zeus; host transport is tested natively")
@pytest.mark.parametrize("family", ["mot_2d", "mot_3d"])
@pytest.mark.parametrize("count", [0, 1])
@pytest.mark.parametrize("corrupt", [False, True])
def test_fresh_receiver_validates_retained_product(tmp_path, family, count, corrupt):
    project = tmp_path / "project"; project.mkdir()
    git = str(executable("git"))
    subprocess.run([git, "init", str(project)], check=True, capture_output=True)
    subprocess.run([git, "-C", str(project), "-c", "user.name=Acceptance", "-c", "user.email=acceptance@example.invalid", "commit", "--allow-empty", "-m", "fixture"], check=True, capture_output=True)
    commit = subprocess.check_output([git, "-C", str(project), "rev-parse", "HEAD"], text=True).strip()
    key, package_hash, job_id = "a" * 64, "b" * 64, "12345.zeus-master"
    run_id = "mot2d-retained" if family == "mot_2d" else "mot3d-retained"
    directory = project / ".workflow" / family.replace("_", "-").replace("mot-", "individual-mot-")
    submissions = directory / "submissions"; submissions.mkdir(parents=True)
    receipt = {"job_id": job_id, "username": "tal.noa", "project_directory": str(project), "commit": commit, "package_sha256": package_hash, "run_id": run_id}
    (submissions / f"{key}.json").write_text(json.dumps(receipt))
    stream = BytesIO(); np.save(stream, np.zeros((count, 6), dtype=np.float64)); raw = stream.getvalue()
    metrics = {"n_survivors": count} if family == "mot_2d" else {"usable_at_end_count": count + 1, "residence_qualified_captured_count": count}
    results = {"schema_version": "run-results-v1", "run_id": run_id, "completed_utc": "2026-10-18T17:00:00+00:00", "states_retained": True, "suitability": "individual_only", "metrics": metrics,
               "artifacts": [{"kind": "particle_states", "path": "results/states.npy", "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}]}
    encode_record("results", results)
    product = {"version": 1, "run_id": run_id, "job_id": job_id, "package_sha256": package_hash, "submission_key": key,
               "results": results, "receipt": None, "artifacts": {"results/states.npy": base64.b64encode(raw if not corrupt else raw[:-1] + b"x").decode()}}
    target = directory / package_hash; target.mkdir(); (target / "worker_product.json").write_text(json.dumps(product))
    root = Path(__file__).resolve().parents[1]
    source = (root / "workflow_api" / f"{family}_zeus_remote.py").read_text()
    source = source.replace('allowed = {Path("/home") / username / name for name in ("ytterbium_lab_simulation_new", "ytterbium_lab_simulation_ui_test")}', 'allowed = {project}')
    source = source.replace('sys.path.insert(0, str(project))', f'sys.path.insert(0, {str(root)!r})')
    source = source.replace('"/usr/bin/git"', repr(git))
    script = tmp_path / "receiver.py"; script.write_text(source)
    payload = base64.urlsafe_b64encode(json.dumps({"job_id": job_id, "submission_key": key, "package_sha256": package_hash}).encode()).decode()
    returned = subprocess.run([sys.executable, str(script), "retrieve", "tal.noa", str(project), payload], capture_output=True, text=True)
    if corrupt:
        assert returned.returncode != 0
        assert json.loads(returned.stdout) == {"error": "result_unavailable"}
    else:
        assert returned.returncode == 0, returned.stdout + returned.stderr
        assert json.loads(returned.stdout)["results"] == results
