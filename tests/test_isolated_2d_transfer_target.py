"""Execute the real receiver/publication on fixture roots, never SSH or qsub."""
import base64
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_zeus_transfer_security import initialize_git_repository
from workflow_api.zeus_transfer import _REMOTE_TRANSFER_SCRIPT


@pytest.mark.parametrize("checkout,binding,accepted", [
    ("ytterbium_lab_simulation_ui_test", "ytterbium_lab_simulation_ui_test", True),
    ("ytterbium_lab_simulation_new", None, True),
    ("ytterbium_lab_simulation_new", "ytterbium_lab_simulation_ui_test", False),
    ("ytterbium_lab_simulation_ui_test", None, False),
    ("ytterbium_lab_simulation_new", "ytterbium_lab_simulation_new", False),
])
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX receiver filesystem primitives")
def test_real_receiver_enforces_target_before_atomic_publication(tmp_path, checkout, binding, accepted):
    home = tmp_path / "home" / "tester"
    project = home / checkout
    project.mkdir(parents=True)
    commit = initialize_git_repository(project)
    manifest = {"kind": "mot_2d_s0_campaign"}
    if binding is not None:manifest["execution_checkout"] = binding
    prefix = "data/optimization/mot_2d/fresh"
    files = {prefix + "/campaign.json": json.dumps(manifest).encode(), prefix + "/jobs/01_smoke.pbs": b"#!/bin/bash\ntrue\n"}
    payload = b"".join(struct.pack("!Q", len(content)) + hashlib.sha256(content).hexdigest().encode() + content for content in files.values())
    encoded = base64.urlsafe_b64encode(json.dumps(list(files)).encode()).decode()
    # Fixture mapping changes only /home, not target authorization or publication.
    script = _REMOTE_TRANSFER_SCRIPT.replace("home = pathlib.Path('/home') / username", "home = project.resolve().parent")
    original = "from workflow_api.acceptance_remote import assert_campaign_target"
    mapping = '''from workflow_api.acceptance_remote import assert_campaign_target as checked_target
                def assert_campaign_target(value,username,root,campaign):
                    return checked_target(value,username,'/home/'+username+'/'+pathlib.Path(root).name,campaign)'''
    script = script.replace(original, mapping)
    script = "import sys;sys.path.insert(0," + repr(str(Path(__file__).resolve().parents[1])) + ")\n" + script
    result = subprocess.run([sys.executable, "-c", script, "campaign", "tester", str(project), encoded, commit], input=payload, capture_output=True, timeout=15)
    final = project / prefix
    assert (result.returncode == 0) is accepted, result.stderr.decode()
    assert final.exists() is accepted
    if accepted:
        assert all((project / name).read_bytes() == content for name, content in files.items())
    else:
        assert not list(final.parent.glob(".zeus-campaign-*"))
