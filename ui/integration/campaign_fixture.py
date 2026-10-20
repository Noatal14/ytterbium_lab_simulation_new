"""Synthetic inputs for the real-handler browser suite; never scientific evidence."""
from pathlib import Path
import json
import os
import shutil
import subprocess

from tests.test_workflow_api_creation import source
from tests.test_mot_3d_campaign import input_dir, upstream_campaign
from workflow_api.repository_snapshot import MOT_2D_INDIVIDUAL_RELEVANT_FILES
from workflow_api.mot_2d_spec import RELEVANT_FILES
from studies import mot_3d_campaign


def prepare(root: Path, code: Path) -> Path:
    root = root.resolve(strict=True)
    paths = set(RELEVANT_FILES) | set(MOT_2D_INDIVIDUAL_RELEVANT_FILES) | set(mot_3d_campaign.CAMPAIGN_FILES)
    for directory in ("workflow_api", "lab_setup", "simulations", "studies", "utils", "atomsmltr/src/atomsmltr"):
        paths.update(p.relative_to(code).as_posix() for p in (code / directory).rglob("*.py"))
    paths.update(p.relative_to(code).as_posix() for p in (code / "lab_setup").rglob("*.json"))
    for relative in paths:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(code / relative, destination)
    (root / "SYNTHETIC_TEST_INPUTS.txt").write_text(
        "Synthetic zero-state fixtures for UI contract testing only. "
        "Not measured or simulated laboratory results. Never submit these jobs.\n"
    )
    source(root)  # Canonical 35-seed schema, hashes and explicit laboratory contract.
    legacy = root / "data/particle_states/after_zeeman/zz_ui_SYNTHETIC_legacy"
    shutil.copytree(root / "data/particle_states/after_zeeman/source", legacy)
    for path in legacy.glob("*.json"):
        record = json.loads(path.read_text())
        for key in ("laboratory_spec_version", "laboratory_spec_sha256", "zeeman_profile_sha256"):
            record.pop(key)
        path.write_text(json.dumps(record))
    states = input_dir.__wrapped__(root)
    upstream = upstream_campaign.__wrapped__(root, states)
    manifest_path = upstream / "campaign.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["name"] = "ui_acceptance_SYNTHETIC_upstream"
    manifest_path.write_text(json.dumps(manifest))
    # Real validators, Git revision and code hashing; no fake snapshot provider.
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("Git is required for the isolated campaign fixture")
    subprocess.run([git, "init", "--quiet", str(root)], check=True)
    subprocess.run([git, "-C", str(root), "config", "core.autocrlf", "false"], check=True)
    subprocess.run([git, "-C", str(root), "add", "."], check=True)
    subprocess.run([git, "-C", str(root), "-c", "user.name=UI acceptance fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "--quiet",
                    "-m", "Synthetic UI inputs and frozen code; no scientific claims"], check=True)
    os.chdir(root)
    return root
