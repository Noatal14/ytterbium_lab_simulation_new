"""Classify only output-free OpenSSH connection timeouts on read operations.

The runner result is synthetic transport evidence, not a remote workflow run.
"""
import subprocess
from unittest.mock import Mock

import pytest

from workflow_api.mot_3d_preliminary_transition import (
    PinnedSshMot3DPreliminaryTransitionTransport,
)
from workflow_api.mot_3d_finalist_transition_remote_client import (
    PinnedSshMot3DFinalistTransitionTransport,
)
from workflow_api.pinned_ssh import ReceiverOperation
from workflow_api.zeus_snapshot import ZeusProfile


TIMEOUT = b"ssh: connect to host zeus.technion.ac.il port 22: Operation timed out\r\n"


def adapter(kind, *, returncode=255, stdout=b"", stderr=TIMEOUT):
    transport = object.__new__(kind)
    transport.profile = ZeusProfile("tal.noa", "/home/tal.noa/isolated-test")
    transport.runner = Mock()
    transport.runner.run.return_value = subprocess.CompletedProcess(
        ["ssh"], returncode, stdout, stderr
    )
    return transport


@pytest.mark.parametrize("kind", [PinnedSshMot3DPreliminaryTransitionTransport,
                                 PinnedSshMot3DFinalistTransitionTransport])
@pytest.mark.parametrize("operation, selected", [
    ("inspect", ReceiverOperation.INSPECT),
    ("status", ReceiverOperation.STATUS),
    ("retrieve", ReceiverOperation.RETRIEVE),
])
@pytest.mark.parametrize("stderr", [TIMEOUT, TIMEOUT.replace(b"Operation", b"Connection")])
def test_readonly_openssh_timeout_uses_existing_communication_error(kind, operation, selected, stderr):
    transport = adapter(kind, stderr=stderr)
    payload = {"original_payload": "unchanged"}
    with pytest.raises(transport.error_type) as error:
        transport._call(operation, payload)
    assert error.value.code == "zeus_timeout"
    transport.runner.run.assert_called_once_with(selected, transport.profile, payload)


@pytest.mark.parametrize("kind", [PinnedSshMot3DPreliminaryTransitionTransport,
                                 PinnedSshMot3DFinalistTransitionTransport])
def test_prepare_timeout_remains_unknown_without_retry(kind):
    transport = adapter(kind)
    with pytest.raises(transport.error_type) as error:
        transport._call("prepare", {"nonce": "original"})
    assert error.value.code == "transition_outcome_unknown"
    assert transport.runner.run.call_count == 1


@pytest.mark.parametrize("returncode, stdout, stderr", [
    (1, b"", TIMEOUT),
    (0, b"", TIMEOUT),
    (255, b'{"error":"invalid_request"}', TIMEOUT),
    (255, b"not JSON", TIMEOUT),
    (20, b'{"error":"invalid_request"}', b""),
    (255, b"", b"remote calculation timed out\n"),
    (255, b"", TIMEOUT.replace(b"zeus.technion.ac.il", b"foreign.example")),
    (255, b"", TIMEOUT.replace(b"port 22", b"port 2222")),
    (255, b"", TIMEOUT + b"additional diagnostic\n"),
    (255, b"", b"Permission denied (publickey).\n"),
    (255, b"", b""),
])
def test_other_failed_or_malformed_results_remain_fail_closed(returncode, stdout, stderr):
    transport = adapter(PinnedSshMot3DPreliminaryTransitionTransport,
                        returncode=returncode, stdout=stdout, stderr=stderr)
    with pytest.raises(transport.error_type) as error:
        transport._call("status", {})
    assert error.value.code == "remote_response_invalid"
    assert transport.runner.run.call_count == 1


@pytest.mark.parametrize("operation, code", [("status", "zeus_timeout"),
                                            ("prepare", "transition_outcome_unknown")])
def test_python_deadline_behavior_is_unchanged(operation, code):
    transport = adapter(PinnedSshMot3DPreliminaryTransitionTransport)
    transport.runner.run.side_effect = subprocess.TimeoutExpired(["ssh"], 90)
    with pytest.raises(transport.error_type) as error:
        transport._call(operation, {})
    assert error.value.code == code
    assert transport.runner.run.call_count == 1
