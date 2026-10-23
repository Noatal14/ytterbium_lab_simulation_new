"""Fixture lifecycle regression: clone preparation must not leak run wrappers."""
import hashlib
import os
import subprocess
from types import SimpleNamespace

import pytest
import test_mot_3d_receiver_protocol_chain as protocol


def inventory(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


@pytest.mark.skipif(os.name == 'nt', reason='POSIX temporary Git/Zeus protocol fixture')
def test_two_real_upstream_fixture_contexts_restore_subprocess_run(tmp_path, monkeypatch):
    baseline = subprocess.run
    expected_docs = inventory(protocol.two_d.CODE / 'docs')
    for number in range(2):
        parent = tmp_path / str(number)
        parent.mkdir()
        with monkeypatch.context() as child:
            chain = protocol._Upstream(parent, child, True)
            assert chain._real_run is baseline
            assert subprocess.run is not baseline  # Scheduler fake is active only in this context.
            assert inventory(chain.local / 'docs') == expected_docs
            assert inventory(chain.remote / 'docs') == expected_docs
        assert subprocess.run is baseline


def test_clone_docs_provisioning_refuses_existing_destination(tmp_path):
    local = tmp_path / 'local'
    (local / 'docs').mkdir(parents=True)
    sentinel = local / 'docs' / 'unrelated.txt'
    sentinel.write_bytes(b'preserve unrelated fixture data')
    baseline = subprocess.run
    with pytest.raises(FileExistsError):
        protocol._Upstream._prepare_clone(SimpleNamespace(local=local))
    assert sentinel.read_bytes() == b'preserve unrelated fixture data'
    assert subprocess.run is baseline
