"""Real validator -> coordinator -> loopback HTTP -> strict TypeScript parser.

Only the scheduler transport and repository planning authority are fixture seams.
No physical simulation, SSH, scheduler submission, or remote mutation occurs.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.test_mot_2d_smoke_security import (
    _manifest, _valid_smoke, _screening_coordinator, _screening_request,
)
from tests.test_workflow_api_server import running_server, request_json, _session_headers
from workflow_api.mot_2d_smoke import validate_smoke_outputs
from workflow_api.zeus_screening import RemoteSmokeState


def _parse_with_actual_client(payloads):
    root = Path(__file__).resolve().parents[1]
    vite = root / 'ui/node_modules/vite/dist/node/index.js'
    node = shutil.which('node')
    bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    if node is None and bundled.is_file():
        node = str(bundled)
    if node is None or not vite.is_file():
        pytest.skip('Cross-language HTTP contract requires the UI Node/Vite dependencies')
    script = '''
import {createServer} from VITE_MODULE;
let input='';for await (const chunk of process.stdin) input+=chunk;
const payloads=JSON.parse(input);
const server=await createServer({root:UI_ROOT,configFile:false,server:{middlewareMode:true,hmr:false},appType:'custom'});
try {
 const client=await server.ssrLoadModule('/src/api/schema/domain.ts');
 const status=client.parseSmokeLifecycle(payloads.status);
 const preview=client.parseScreeningPreview(payloads.preview);
 // The strict client continues rejecting private/unknown point keys.
 const altered=structuredClone(payloads.status);
 altered.validation.points[0].artifacts={summary_sha256:'a'.repeat(64)};
 let rejected=false;try{client.parseSmokeLifecycle(altered);}catch{rejected=true;}
 if(!rejected)throw Error('Public point schema was weakened');
 console.log('SMOKE_CONTRACT_RESULT:'+JSON.stringify({status:status.validation.points,preview:preview.smoke.points}));
} finally {await server.close();}
'''.replace('VITE_MODULE', json.dumps(vite.as_uri())).replace('UI_ROOT', json.dumps(str(root/'ui')))
    result = subprocess.run([node,'--input-type=module','-e',script],input=json.dumps(payloads),capture_output=True,text=True,timeout=45)
    assert result.returncode == 0, result.stderr + result.stdout
    line = next(row for row in result.stdout.splitlines() if row.startswith('SMOKE_CONTRACT_RESULT:'))
    return json.loads(line.split(':',1)[1])


@pytest.mark.parametrize('captured', [0, 1])
def test_validated_hash_bearing_smoke_points_cross_real_http_into_strict_client(tmp_path, captured):
    artifact_root = tmp_path / 'validated-outputs'
    manifest = _manifest()
    _valid_smoke(artifact_root, manifest, 1.3, captured=captured)
    points = tuple(validate_smoke_outputs(artifact_root, manifest))
    assert set(points[0]) == {'s0','captured','input','efficiency','artifacts'}
    assert set(points[0]['artifacts']) == {'summary_sha256','trial_sha256','database_sha256'}
    full_digest = hashlib.sha256(json.dumps([dict(row) for row in points],sort_keys=True).encode()).hexdigest()

    class Transport:
        preparations = []
        def inspect(self, **payload):
            return RemoteSmokeState('ready_to_prepare_screen','12345.zeus-master','F',0,points,3,'main')
        def prepare(self, **payload):
            self.preparations.append(payload)
            assert payload['smoke_digest'] == full_digest
            return RemoteSmokeState('screen_prepared','12345.zeus-master','F',0,points,3,'main')

    transport = Transport()
    coordinator, _ = _screening_coordinator(tmp_path/'repo', transport)
    public_point = {'s0':1.3,'captured':captured,'input':2,'efficiency':captured/2}
    with running_server(request_count=4,screening_service=coordinator) as base:
        _, headers, session = request_json(base+'/api/v1/session',headers={'Sec-Fetch-Site':'same-origin'})
        trusted = _session_headers(base,headers['Set-Cookie'].split(';',1)[0],session['data']['csrf_token'])
        status_code, _, status = request_json(base+'/api/v1/zeus/smoke/status',method='POST',headers=trusted,body=json.dumps(_screening_request()))
        preview_code, _, preview = request_json(base+'/api/v1/zeus/screening/preview',method='POST',headers=trusted,body=json.dumps(_screening_request()))
        assert status_code == preview_code == 200
        assert status['data']['validation']['points'] == preview['data']['smoke']['points'] == [public_point]
        parsed = _parse_with_actual_client({'status':status['data'],'preview':preview['data']})
        assert parsed == {'status':[public_point],'preview':[public_point]}
        # Full three-artifact attestation remains private and binds confirmation.
        pending = coordinator._previews.get(preview['data']['preview_token']).value
        assert pending.smoke_digest == full_digest
        assert pending.smoke_digest != hashlib.sha256(json.dumps([public_point],sort_keys=True).encode()).hexdigest()
        confirm_code, _, confirmed = request_json(base+'/api/v1/zeus/screening/confirm',method='POST',headers=trusted,body=json.dumps({'preview_token':preview['data']['preview_token']}))
        assert confirm_code == 201
        assert confirmed['data']['submitted_to_zeus'] is False
        assert len(transport.preparations) == 1
    assert set(points[0]) == {'s0','captured','input','efficiency','artifacts'}


@pytest.mark.parametrize('row', [None, {'s0':1.3}, {'s0':1.3,'captured':1,'input':2,'efficiency':0.5,'unexpected':True}])
@pytest.mark.parametrize('action', ['status','preview'])
def test_malformed_private_point_is_typed_failure_before_publication(tmp_path, row, action):
    from workflow_api.zeus_screening import ZeusScreeningError
    class Transport:
        def inspect(self, **payload):
            return RemoteSmokeState('ready_to_prepare_screen','12345.zeus-master','F',0,(row,),3,'main')
    coordinator, _ = _screening_coordinator(tmp_path/'repo', Transport())
    with pytest.raises(ZeusScreeningError) as error:
        getattr(coordinator,action)(_screening_request(),session_id='session')
    assert error.value.code == 'remote_response_invalid'
