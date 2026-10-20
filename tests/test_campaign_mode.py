"""A TEST ONLY browser mode cannot grant scientific mutation authority."""
import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import pytest
from workflow_api.acceptance_profile import load_acceptance_profile
from workflow_api.campaign_mode import authorize_campaign_request, campaign_visible
from workflow_api.discovery import build_registry
from workflow_api.server import WorkflowHandler


def make_campaign(root, acceptance):
    relative = 'data/optimization/mot_2d/' + ('ui_acceptance/canary' if acceptance else 'science')
    path = root / relative / 'campaign.json'
    path.parent.mkdir(parents=True)
    model = {'kind': 'mot_2d_ui_acceptance_v1' if acceptance else 'mot_2d_s0_campaign'}
    if acceptance: model['acceptance'] = load_acceptance_profile().provenance()
    path.write_text(json.dumps(model))
    return next(row.campaign_id for row in build_registry(root).values() if row.manifest == path)


@pytest.mark.parametrize('active_acceptance', [False, True])
def test_crossed_campaign_is_rejected_before_service_or_scheduler(tmp_path, active_acceptance):
    campaign_id = make_campaign(tmp_path, not active_acceptance)
    calls = []
    class Forbidden:
        def preview(self, *args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError('Crossed authority reached a service')
    class Handler(WorkflowHandler):
        repository_root = tmp_path
        acceptance_profile_id = 'ui_acceptance_v1' if active_acceptance else None
        submission_service = Forbidden()
        sessions = {}
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = HTTPConnection('127.0.0.1', server.server_port)
        client.request('GET', '/api/v1/session', headers={'Sec-Fetch-Site':'same-origin'})
        response = client.getresponse()
        cookie = response.getheader('Set-Cookie').split(';')[0]
        csrf = json.loads(response.read())['data']['csrf_token']
        body = json.dumps({'campaign_id':campaign_id, 'username':'tal.noa', 'project_directory':'/home/tal.noa/ytterbium_lab_simulation_new'})
        client.request('POST', '/api/v1/zeus/submissions/smoke/preview', body, headers={
            'Sec-Fetch-Site':'same-origin', 'Content-Type':'application/json',
            'Origin':f'http://127.0.0.1:{server.server_port}',
            'Cookie':cookie, 'X-CSRF-Token':csrf})
        response = client.getresponse()
        assert response.status == 412
        response.read()
        assert calls == []
        client.close()
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_visibility_and_direct_authority_use_both_identity_directions(tmp_path):
    scientific = make_campaign(tmp_path, False)
    acceptance = make_campaign(tmp_path, True)
    authorize_campaign_request(tmp_path, {'campaign_id':scientific}, None)
    authorize_campaign_request(tmp_path, {'campaign_id':acceptance}, 'ui_acceptance_v1')
    assert campaign_visible({'kind':'mot_2d_ui_acceptance_v1'}, 'ui_acceptance_v1')
    assert not campaign_visible({'kind':'mot_2d_s0_campaign'}, 'ui_acceptance_v1')
    assert not campaign_visible({'kind':'mot_2d_ui_acceptance_v1'}, None)
    with pytest.raises(ValueError):
        authorize_campaign_request(tmp_path, {'campaign_id':'missing'}, 'ui_acceptance_v1')
