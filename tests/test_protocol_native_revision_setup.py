"""Native host setup qualification, separate from Linux receiver execution.

Git and coordinator revision checks are real; transport is forbidden. The source
bank is an explicitly synthetic protocol fixture, not physical acceptance data.
"""
import pathlib
import shutil
import subprocess

import pytest

from tests.test_mot_2d_receiver_protocol_chain import CODE, _source
from workflow_api.mot_2d_plan import build_plan, materialize
from workflow_api.repository_snapshot import RepositorySnapshot
from workflow_api.zeus_submission import ZeusSmokeSubmissionCoordinator


@pytest.mark.parametrize("layout", ["materialized", "fresh-clone"])
@pytest.mark.parametrize("acceptance", [False, True], ids=["scientific", "TEST-ONLY"])
def test_native_protocol_setup_passes_first_real_revision_guard(tmp_path, acceptance, layout):
    root = tmp_path / "Native protocol Git root with spaces"
    root.mkdir()
    git = pathlib.Path(shutil.which("git")).resolve(strict=True)
    ssh = pathlib.Path(shutil.which("ssh")).resolve(strict=True)
    for name in ("workflow_api", "studies", "simulations", "utils", "lab_setup", "atomsmltr/src"):
        shutil.copytree(CODE / name, root / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copyfile(CODE / "config.py", root / "config.py")
    # Match the real repository/Quickstart checkout rather than omitting its
    # canonical LF attributes while Git installation autocrlf remains enabled.
    shutil.copyfile(CODE / ".gitattributes", root / ".gitattributes")
    (root / ".gitignore").write_text("data/\n__pycache__/\n*.pyc\n")
    for args in (["init", "-q"], ["add", "."], ["-c", "user.name=Protocol fixture", "-c", "user.email=protocol@example.invalid", "commit", "-qm", "Native setup"]):
        subprocess.run([str(git), "-C", str(root), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    commit = subprocess.check_output([str(git), "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if layout == "fresh-clone":
        target = tmp_path / "Fresh Quickstart Git clone with spaces"
        subprocess.run([str(git), "clone", "--no-local", "--no-hardlinks", str(root), str(target)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        root = target
    source = _source(root, commit, acceptance)
    plan = build_plan(root, name="protocol-chain", slug="protocol-chain", s0_values=[1.3], source=source,
                      snapshot=RepositorySnapshot(commit), acceptance_profile_id="ui_acceptance_v1" if acceptance else None)
    materialize(plan)
    class ForbiddenTransport:
        def __init__(self, *args):
            raise AssertionError("Native revision qualification must never invoke transport")
    coordinator = ZeusSmokeSubmissionCoordinator(root, ssh, git, transport_factory=ForbiddenTransport)
    # FIRST service-environment revision read; do not refresh index with an
    # ordinary full-environment git status before this assertion.
    assert coordinator._revision() == (commit, True)
    assert plan.manifest["provenance"]["git_commit"] == commit
    assert subprocess.check_output([str(git), "-C", str(root), "rev-parse", "HEAD"], text=True).strip() == commit
