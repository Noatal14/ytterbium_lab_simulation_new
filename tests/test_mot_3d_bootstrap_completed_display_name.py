"""A display name accepted at creation stays usable after real completion."""
import json
import pytest
import os

from tests.test_mot_2d_receiver_protocol_chain import _run_full_on_disk_receiver_protocol_chain
from workflow_api.mot_3d_bootstrap import Mot3DDiscoveryBootstrapService


@pytest.mark.skipif(os.name == "nt", reason="POSIX receiver and shell scheduler fixture executes on Zeus; native client contracts remain separate")
def test_genuine_completed_testonly_human_display_name_is_catalog_source(tmp_path, monkeypatch):
    name = 'TEST ONLY UI Release Mac 20261020 J'
    chain = _run_full_on_disk_receiver_protocol_chain(tmp_path, monkeypatch, True, name=name)
    assert chain.campaign.name == 'protocol-chain'
    manifest = json.loads((chain.campaign / 'campaign.json').read_bytes())
    assert manifest['name'] == name and manifest['stage'] == 'complete'
    before = {path.relative_to(chain.remote).as_posix(): path.read_bytes()
              for path in (chain.remote / 'data').rglob('*') if path.is_file()}
    from studies import mot_3d_campaign
    with monkeypatch.context() as scoped:
        # Repository-root discovery follows this isolated package installation;
        # no metadata bytes or provenance fields are relocated/relabelled.
        scoped.setattr(mot_3d_campaign, '__file__', str(chain.remote / 'studies/mot_3d_campaign.py'))
        scoped.chdir(chain.remote)
        service = Mot3DDiscoveryBootstrapService(chain.remote, acceptance_profile_id='ui_acceptance_v1')
        sources = service._sources()
    assert len(sources) == 1
    public, campaign, survivors = sources[0]
    assert public['campaign_name'] == name
    assert public['sealed_ensemble_count'] == 20
    assert campaign == chain.campaign
    assert survivors.is_relative_to(campaign / 'survivor_states')
    after = {path.relative_to(chain.remote).as_posix(): path.read_bytes()
             for path in (chain.remote / 'data').rglob('*') if path.is_file()}
    assert after == before
    assert len(chain.qsub_calls) == 9  # only the hermetic chain's fake scheduler
