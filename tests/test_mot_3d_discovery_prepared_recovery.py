"""Canonical completed-Discovery recovery; real writers/receivers, fake solver only."""
import json
import os
from copy import deepcopy

import pytest

from workflow_api.mot_3d_discovery_transition import Mot3DDiscoveryTransitionError
from workflow_api.zeus_discovery_submission import ZeusMot3DDiscoverySubmissionError
from test_mot_3d_receiver_protocol_chain import _completed_upstream, _ThreeD


@pytest.mark.skipif(os.name == 'nt', reason='Hermetic POSIX Zeus receiver/scheduler fixture')
def test_prepared_discovery_status_recovers_only_authenticated_preliminary(tmp_path, monkeypatch):
    upstream = _completed_upstream(tmp_path, monkeypatch)
    chain = _ThreeD(upstream, monkeypatch)
    discovery = chain.coordinator('zeus_discovery_submission', 'ZeusMot3DDiscoverySubmissionCoordinator')
    chain.confirm(discovery)
    chain.work_submitted_jobs()
    transition = chain.coordinator('mot_3d_discovery_transition', 'Mot3DDiscoveryTransitionCoordinator')
    chain.confirm(transition)
    campaign = chain.local / chain.relative
    before = {p.relative_to(campaign): p.read_bytes() for p in campaign.rglob('*') if p.is_file()}
    submitted = len(upstream.qsub_calls)
    status = transition.status(chain.request)
    assert status['campaign']['stage'] == 'preliminary_check'
    assert status['discovery']['status'] == 'preliminary_check_prepared'
    assert status['validation'] == {'status': 'valid', 'completed_trials': 24, 'expected_trials': 24}
    assert status['local_sync']['status'] == 'synchronized'
    # Submission authority does not inherit the transition's recovery option.
    with pytest.raises(ZeusMot3DDiscoverySubmissionError, match='discovery_not_prepared'):
        discovery._plan(chain.request)
    receipt = campaign / '.mot_ui/sync/discovery_to_preliminary.json'
    original = receipt.read_bytes()
    for attack in ('missing', 'wrong_hash', 'unknown_file'):
        changed = deepcopy(json.loads(original))
        name = next(n for n in changed['files'] if '/trials/' in n)
        if attack == 'missing': changed['files'].pop(name)
        elif attack == 'wrong_hash': changed['files'][name] = '0' * 64
        else: changed['files']['discovery/unreviewed.json'] = '0' * 64
        receipt.write_text(json.dumps(changed))
        try:
            with pytest.raises(Mot3DDiscoveryTransitionError, match='preliminary_preparation_invalid'):
                transition.status(chain.request)
        finally:
            receipt.write_bytes(original)
    bootstrap_job = campaign / 'jobs/angled_donut/round_01.pbs'
    original_job = bootstrap_job.read_bytes()
    bootstrap_job.write_bytes(original_job + b'\n# altered bootstrap job\n')
    try:
        with pytest.raises(Mot3DDiscoveryTransitionError, match='discovery_preparation_invalid'):
            transition.status(chain.request)
    finally:
        bootstrap_job.write_bytes(original_job)
    with pytest.raises(Mot3DDiscoveryTransitionError):
        transition.status({**chain.request, 'project_directory': '/home/tal.noa/ytterbium_lab_simulation_new'})
    manifest_path = campaign / 'campaign.json'
    raw_manifest = manifest_path.read_bytes()
    changed = json.loads(raw_manifest); changed['unreviewed_field'] = True
    manifest_path.write_text(json.dumps(changed))
    try:
        with pytest.raises(Mot3DDiscoveryTransitionError):
            transition.status(chain.request)
    finally:
        manifest_path.write_bytes(raw_manifest)
    bootstrap_receipt = campaign / '.mot_ui/transitions/discovery_bootstrap.json'
    original_bootstrap = bootstrap_receipt.read_bytes()
    changed_bootstrap = json.loads(original_bootstrap); changed_bootstrap['bootstrap_key'] = '0' * 64
    bootstrap_receipt.write_text(json.dumps(changed_bootstrap))
    try:
        with pytest.raises(Mot3DDiscoveryTransitionError, match='discovery_preparation_invalid'):
            transition.status(chain.request)
    finally:
        bootstrap_receipt.write_bytes(original_bootstrap)
    changed = json.loads(raw_manifest); changed['stage'] = 'refinement'
    manifest_path.write_text(json.dumps(changed))
    try:
        with pytest.raises(Mot3DDiscoveryTransitionError):
            transition.status(chain.request)
    finally:
        manifest_path.write_bytes(raw_manifest)
    assert len(upstream.qsub_calls) == submitted
    assert {p.relative_to(campaign): p.read_bytes() for p in campaign.rglob('*') if p.is_file()} == before
