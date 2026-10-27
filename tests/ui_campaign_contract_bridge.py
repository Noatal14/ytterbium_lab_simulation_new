"""Cross-language assertion for real public campaign coordinator responses.

Invoked by on-disk protocol integration; this is not a browser or Zeus test.
"""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


def assert_campaign_client_contracts(cases, *, acceptance):
    """Pass unmodified public DTOs through the actual Vite-loaded TS parsers."""
    root = Path(__file__).resolve().parents[1]
    vite = root / 'ui/node_modules/vite/dist/node/index.js'
    node = shutil.which('node')
    bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    if node is None and bundled.is_file():
        node = str(bundled)
    if node is None or not vite.is_file():
        pytest.skip('Cross-language campaign contract requires installed Node/Vite UI dependencies')
    assert cases, 'No real public coordinator DTOs were collected'
    script = '''
import {createServer} from VITE_MODULE;
let raw='';for await(const chunk of process.stdin)raw+=chunk;
const input=JSON.parse(raw);
const server=await createServer({root:UI_ROOT,envFile:false,mode:input.acceptance?'ui-acceptance':'development',configFile:false,server:{middlewareMode:true,hmr:false},appType:'custom'});
try {
 const domain=await server.ssrLoadModule('/src/api/schema/domain.ts');
 for(const row of input.cases){
  const parser=domain[row.parser];
  if(typeof parser!=='function')throw Error('Missing strict campaign parser '+row.parser);
  try{parser(row.value);}catch(error){throw Error((row.label??(row.coordinator+'/'+row.method))+' ['+row.parser+']: '+String(error));}
 }
 console.log('CAMPAIGN_CLIENT_CONTRACT_COUNT:'+input.cases.length);
}finally{await server.close();}
'''.replace('VITE_MODULE', json.dumps(vite.as_uri())).replace('UI_ROOT', json.dumps(str(root/'ui')))
    result = subprocess.run([node, '--input-type=module', '-e', script],
                            input=json.dumps({'cases':cases,'acceptance':acceptance}, allow_nan=False),
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f'CAMPAIGN_CLIENT_CONTRACT_COUNT:{len(cases)}' in result.stdout
