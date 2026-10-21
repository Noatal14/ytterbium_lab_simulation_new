"""Pinned stdin framing must reach the unchanged receiver validation boundary."""
import base64
import io
import json
import sys

import pytest

from workflow_api import mot_3d_discovery_transition_remote as discovery
from workflow_api import mot_3d_preliminary_transition_remote as preliminary
from workflow_api.pinned_ssh import ReceiverKind, _RECEIVERS


@pytest.mark.parametrize('receiver', [discovery, preliminary])
@pytest.mark.parametrize('raw', [b'', b'{', b'null', b'[]', b'x' * (1024 * 1024 + 1)])
def test_stdin_invalid_or_oversized_request_remains_rejected(monkeypatch, capsys, receiver, raw):
    monkeypatch.setattr(sys, 'argv', ['receiver', 'status', 'tal.noa', '/home/tal.noa/ytterbium_lab_simulation_ui_acceptance', '-'])
    monkeypatch.setattr(sys, 'stdin', io.TextIOWrapper(io.BytesIO(raw)))
    with pytest.raises(SystemExit) as stopped:
        receiver.main()
    assert stopped.value.code == 20
    assert json.loads(capsys.readouterr().out) == {'error': 'invalid_request'}


@pytest.mark.parametrize('kind', [ReceiverKind.MOT_3D_DISCOVERY_TRANSITION,
    ReceiverKind.MOT_3D_PRELIMINARY_TRANSITION, ReceiverKind.MOT_3D_REFINEMENT_TRANSITION,
    ReceiverKind.MOT_3D_CLOSURE_TRANSITION])
def test_affected_transport_contract_is_stdin(kind):
    assert _RECEIVERS[kind].payload_stdin is True


class DecodedPayloadBoundary(BaseException):
    pass


@pytest.mark.parametrize('receiver', [discovery, preliminary])
@pytest.mark.parametrize('stdin', [False, True], ids=['legacy-base64', 'pinned-stdin'])
def test_exact_payload_limit_reaches_unchanged_filesystem_boundary(monkeypatch, receiver, stdin):
    raw = json.dumps({'campaign': 'data/optimization/mot_3d/ui_acceptance/test'}).encode()
    raw += b' ' * (1024 * 1024 - len(raw))
    monkeypatch.setattr(sys, 'argv', ['receiver', 'status', 'tal.noa', '/home/tal.noa/ytterbium_lab_simulation_ui_acceptance',
        '-' if stdin else base64.urlsafe_b64encode(raw).decode()])
    monkeypatch.setattr(sys, 'stdin', io.TextIOWrapper(io.BytesIO(raw)))
    def filesystem_boundary(*_args):
        raise DecodedPayloadBoundary
    monkeypatch.setattr(receiver, 'Path', filesystem_boundary)
    with pytest.raises(DecodedPayloadBoundary):
        receiver.main()


@pytest.mark.parametrize('receiver', [discovery, preliminary])
@pytest.mark.parametrize('raw', [b'{} {}', b'{}' + b' ' * (1024 * 1024 - 1)])
def test_trailing_json_or_one_byte_over_limit_cannot_reach_filesystem(monkeypatch, capsys, receiver, raw):
    monkeypatch.setattr(sys, 'argv', ['receiver', 'status', 'tal.noa', '/home/tal.noa/ytterbium_lab_simulation_ui_acceptance', '-'])
    monkeypatch.setattr(sys, 'stdin', io.TextIOWrapper(io.BytesIO(raw)))
    monkeypatch.setattr(receiver, 'Path', lambda *_args: pytest.fail('invalid payload reached filesystem'))
    with pytest.raises(SystemExit):
        receiver.main()
    assert json.loads(capsys.readouterr().out) == {'error': 'invalid_request'}
