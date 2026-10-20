"""Read-only namespace reconciliation; callers retain exact chain schemas."""
import json
from pathlib import Path
import pytest
from workflow_api.smoke_receipt import resolve_refinement_receipts

NAMES = ('refinement_chain', *(f'refinement_round_{i:02d}' for i in range(1,5)))

def write_bundle(root, leaf):
    directory=root/'.mot_ui'/leaf
    directory.mkdir(parents=True)
    for i,name in enumerate(NAMES):
        (directory/f'{name}.json').write_text(json.dumps({'ordinal':i,'status':'submitted'}))
    return directory

@pytest.mark.parametrize('layout',['transitions','submissions','equal_dual'])
def test_refinement_bundle_selects_without_writes(tmp_path,layout):
    primary=write_bundle(tmp_path,'submissions' if layout=='submissions' else 'transitions')
    if layout=='equal_dual':write_bundle(tmp_path,'submissions')
    before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result=resolve_refinement_receipts(tmp_path)
    assert result==tuple(primary/f'{name}.json' for name in NAMES)
    assert before=={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}

@pytest.mark.parametrize('fault',['conflict','missing','pending','lock','parent_symlink','receipt_symlink','duplicate','nonfinite'])
@pytest.mark.parametrize('leaf',['transitions','submissions'])
def test_refinement_bundle_fails_closed(tmp_path,fault,leaf):
    write_bundle(tmp_path,'transitions');write_bundle(tmp_path,'submissions')
    directory=tmp_path/'.mot_ui'/leaf
    target=directory/'refinement_round_02.json'
    if fault=='conflict':target.write_text('{"ordinal":99}')
    elif fault=='missing':
        target.unlink();(tmp_path/'.mot_ui'/('submissions' if leaf=='transitions' else 'transitions')/target.name).unlink()
    elif fault=='pending':(directory/'refinement_round_04.pending.json').write_text('{}')
    elif fault=='lock':(directory/'refinement_chain.lock').mkdir()
    elif fault=='parent_symlink':
        moved=tmp_path/(leaf+'-real');directory.rename(moved);directory.symlink_to(moved,target_is_directory=True)
    elif fault=='receipt_symlink':target.unlink();target.symlink_to(directory/'refinement_round_01.json')
    elif fault=='duplicate':target.write_text('{"a":1,"a":1}')
    elif fault=='nonfinite':target.write_text('{"a":NaN}')
    with pytest.raises((ValueError,FileNotFoundError)):resolve_refinement_receipts(tmp_path)
