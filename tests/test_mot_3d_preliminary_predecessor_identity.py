"""Discovery and Preliminary use distinct, independently authenticated keys."""
import copy
import json

import pytest

from workflow_api import mot_3d_preliminary_transition_remote as remote
from workflow_api.zeus_discovery_submission import FILES, canonical_digest


def _proof():
    campaign = 'data/optimization/mot_3d/ui_acceptance/TESTONLY'
    commit = 'a' * 40
    fields = ('physical_model_sha256', 'source_2d_campaign_sha256',
              'source_2d_final_report_sha256', 'input_registry_sha256', 'timestep_policy_sha256')
    row = {'status': 'discovery_prepared', 'nonce': 'b' * 32, 'commit': commit,
           **{key: 'c' * 64 for key in fields},
           'files': {name: 'd' * 64 for name in FILES}, 'completed_unix_s': 1.0}
    row['bootstrap_key'] = canonical_digest({
        'campaign_name': 'TESTONLY', 'commit': commit,
        **{key: row[key] for key in fields}, 'files': row['files'], 'nonce': row['nonce'],
    })
    prior = {'bootstrap_digest': canonical_digest(row)}
    expected = canonical_digest({'campaign': campaign, 'commit': commit,
        'bootstrap_digest': canonical_digest(row), 'bootstrap_key': row['bootstrap_key'],
        'bootstrap_nonce': row['nonce'], 'files': row['files']})
    return row, prior, {'campaign': campaign, 'commit': commit, 'submission_key': 'e' * 64}, expected


def test_previous_discovery_key_is_not_current_preliminary_key(monkeypatch):
    row, prior, payload, expected = _proof()
    monkeypatch.setattr(remote, 'read_relative_at', lambda *args: json.dumps(row).encode())
    assert remote._discovery_predecessor_key(0, payload, prior) == expected
    assert expected != payload['submission_key']
    swapped = {**payload, 'campaign': payload['campaign'] + '_other'}
    with pytest.raises(SystemExit) as error:
        remote._discovery_predecessor_key(0, swapped, prior)
    assert error.value.code == 20


@pytest.mark.parametrize('attack', ['nonce', 'files', 'commit', 'extra', 'bootstrap_key'])
def test_changed_bootstrap_cannot_authenticate_prior_receipt(monkeypatch, attack):
    row, prior, payload, _ = _proof()
    row = copy.deepcopy(row)
    if attack == 'files':
        row['files'].pop('campaign.json')
    elif attack == 'extra':
        row['unreviewed'] = True
    else:
        row[attack] = 'f' * (40 if attack == 'commit' else 64)
    monkeypatch.setattr(remote, 'read_relative_at', lambda *args: json.dumps(row).encode())
    with pytest.raises(SystemExit) as error:
        remote._discovery_predecessor_key(0, payload, prior)
    assert error.value.code == 20


def test_saved_sync_semantic_digest_keeps_exact_producer_bytes():
    row = {"value": 1}
    raw = remote.canonical(row) + b"\n"
    assert remote._producer_receipt_digest(raw, row) == canonical_digest(row)


@pytest.mark.parametrize('raw', [b'{"value":1}', b'{ "value":1}\n',
                                 b'{"value":0,"value":1}\n', b'{"value":1}\r\n'])
def test_nonproducer_receipt_bytes_are_rejected(raw):
    with pytest.raises(SystemExit) as error:
        remote._producer_receipt_digest(raw, {"value": 1})
    assert error.value.code == 20
