"""Bridge interpolation is one pass over JSON literals, independent of root text."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from ui_3d_protocol_contract_bridge import render_bridge_script


@pytest.mark.parametrize('name', [
    'UI Release Candidate12 Mac',
    'UI __UI_ROOT_JSON__ __VITE_URI_JSON__ "quoted" `not executed` $(not-executed)',
])
def test_bridge_root_literals_survive_single_pass_interpolation(tmp_path, name):
    root = tmp_path / name
    script = render_bridge_script(root)
    uri_literal = script.split('import {createServer} from ', 1)[1].split(';', 1)[0]
    assert json.loads(uri_literal) == (root / 'ui/node_modules/vite/dist/node/index.js').as_uri()
    root_literal = script.split('createServer({root:', 1)[1].split(",mode:'ui-acceptance'", 1)[0]
    assert json.loads(root_literal) == str(root / 'ui')
    node = shutil.which('node')
    if node is None:
        node = str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
    result = subprocess.run([node, '--input-type=module', '--check'], input=script,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
