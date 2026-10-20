"""Strict Vite-loaded 3D client contracts over real protocol public DTOs."""
import json
from pathlib import Path
import shutil
import subprocess


def assert_3d_contracts(rows):
    root = Path(__file__).resolve().parents[1]
    node = shutil.which('node')
    if node is None:
        node = str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
    script = '''
import {createServer} from VITE;
let raw='';for await(const chunk of process.stdin)raw+=chunk;
const rows=JSON.parse(raw);
const server=await createServer({root:UI,mode:'ui-acceptance',configFile:false,server:{middlewareMode:true,hmr:false},appType:'custom'});
try{
 for(const row of rows){
  const module=await server.ssrLoadModule('/src/api/clients/'+row.client+'.ts');
  try{
   if(row.parser==='completionClient'){
    let call=0;
    globalThis.fetch=async()=>new Response(JSON.stringify({api_version:1,data:call++===0?row.preview:row.value}),{status:200});
    const api=module.createMot3DFinalValidationCompletionApi(async()=>'fixture-session');
    await api.preview(...row.args);
    await api.confirm({preview_token:row.preview.preview_token});
    if(call!==2)throw Error('Unexpected completion client request count');
   }else{
    if(typeof module[row.parser]!=='function')throw Error('Missing parser '+row.parser);
    module[row.parser](row.value,...row.args);
   }
  }catch(error){throw Error(row.label+': '+String(error));}
 }
 console.log('3D_PROTOCOL_CONTRACTS:'+rows.length);
}finally{await server.close();}
'''.replace('VITE', json.dumps((root / 'ui/node_modules/vite/dist/node/index.js').as_uri())).replace('UI', json.dumps(str(root / 'ui')))
    result = subprocess.run([node, '--input-type=module', '-e', script],
                            input=json.dumps(rows, allow_nan=False), capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f'3D_PROTOCOL_CONTRACTS:{len(rows)}' in result.stdout
