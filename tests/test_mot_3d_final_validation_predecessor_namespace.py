"""Actual final-validation receiver keeps prior linear ledgers distinct."""
import hashlib
import json
import shutil

import pytest

from tests.test_mot_3d_final_validation_submission_backend import _repository, _invoke
from tests.test_mot_3d_final_validation_transition_backend import _repository as _linear_repository
from workflow_api import mot_3d_final_validation_submission_remote as receiver


def _fixture(tmp_path):
    root,campaign,payload,frozen=_repository(tmp_path/'current')
    _,prior,key=_linear_repository(tmp_path/'prior')
    names={'final_validation_input_generation.json','final_validation_input_generation.lock',
           *(f'final_validation_input_generation_{step}.json' for step in ('zeeman','mot_2d','freeze'))}
    for name in names:
        source=prior/'.mot_ui/submissions'/name
        destination=campaign/'.mot_ui/submissions'/name
        destination.parent.mkdir(parents=True,exist_ok=True)
        if source.exists():shutil.copyfile(source,destination)
        else:destination.write_bytes(b'')
    shutil.copytree(prior/'jobs/final_validation_inputs',campaign/'jobs/final_validation_inputs')
    shutil.copyfile(prior/'final_validation_input_generation_submission.json',campaign/'final_validation_input_generation_submission.json')
    path=campaign/'.mot_ui/transitions/final_validation_inputs_to_final_validation.json'
    transition=json.loads(path.read_bytes());transition['submission_key']=key
    transition['files']={'final_validation_input_generation_submission.json':hashlib.sha256((campaign/'final_validation_input_generation_submission.json').read_bytes()).hexdigest()}
    path.write_bytes(receiver.canonical(transition)+b'\n')
    payload['identity']['remote_transition_receipt_sha256']=hashlib.sha256(receiver.canonical(transition)).hexdigest()
    payload['submission_key']=receiver.digest({'campaign':payload['campaign'],'commit':payload['commit'],**payload['identity']})
    return root,campaign,payload


def _runner(calls):
    jobs=iter([b'910[].zeus-master\n',b'911.zeus-master\n',b'912[].zeus-master\n',b'913.zeus-master\n'])
    def run(argv,input_data=None,limit=None):
        if argv[:2]==['/usr/bin/git','-C']:
            return (0, b'a'*40+b'\n' if argv[3]=='rev-parse' else b'main\n' if argv[3]=='branch' else b'', b'')
        if argv[0]=='/usr/local/bin/qsub':
            calls.append(argv);return 0,next(jobs),b''
        raise AssertionError(argv)
    return run


def test_prior_exact_authenticated_ledgers_allow_review_submit_and_dedup(tmp_path,monkeypatch,capsys):
    root,campaign,payload=_fixture(tmp_path);calls=[];run=_runner(calls)
    _invoke(monkeypatch,root,'inspect',payload,run)
    assert json.loads(capsys.readouterr().out)['lifecycle']=='eligible'
    assert not calls
    submitted={**payload,'nonce':'8'*32}
    _invoke(monkeypatch,root,'submit',submitted,run)
    assert json.loads(capsys.readouterr().out)['lifecycle']=='submitted'
    assert len(calls)==4
    _invoke(monkeypatch,root,'submit',submitted,run)
    assert json.loads(capsys.readouterr().out)['lifecycle']=='submitted'
    assert len(calls)==4


@pytest.mark.parametrize('attack',['pending','unknown','missing_step','wrong_nonce','symlink','directory','wrong_transition_key','compat_changed'])
def test_ambiguous_or_unattested_prior_ledgers_never_submit(tmp_path,monkeypatch,capsys,attack):
    root,campaign,payload=_fixture(tmp_path);directory=campaign/'.mot_ui/submissions'
    path=directory/'final_validation_input_generation_mot_2d.json'
    if attack=='pending':(directory/'final_validation_input_generation.pending.json').write_text('{}')
    elif attack=='unknown':(directory/'final_validation_input_generation_extra.json').write_text('{}')
    elif attack=='missing_step':path.unlink()
    elif attack=='wrong_nonce':
        row=json.loads(path.read_bytes());row['nonce']='0'*32;path.write_bytes(receiver.canonical(row))
    elif attack=='symlink':path.unlink();path.symlink_to(directory/'final_validation_input_generation.json')
    elif attack=='directory':path.unlink();path.mkdir()
    elif attack=='compat_changed':
        path=campaign/'final_validation_input_generation_submission.json'
        row=json.loads(path.read_bytes());row['nonce']='0'*32;path.write_bytes(receiver.canonical(row))
    else:
        transition_path=campaign/'.mot_ui/transitions/final_validation_inputs_to_final_validation.json'
        row=json.loads(transition_path.read_bytes());row['submission_key']='0'*64
        transition_path.write_bytes(receiver.canonical(row)+b'\n')
        payload['identity']['remote_transition_receipt_sha256']=hashlib.sha256(receiver.canonical(row)).hexdigest()
        payload['submission_key']=receiver.digest({'campaign':payload['campaign'],'commit':payload['commit'],**payload['identity']})
    calls=[]
    with pytest.raises(SystemExit):_invoke(monkeypatch,root,'submit',{**payload,'nonce':'8'*32},_runner(calls))
    assert not calls
    assert json.loads(capsys.readouterr().out)['error']=='final_validation_submission_outcome_unknown'


def test_new_prior_pending_after_first_qsub_stops_remaining_jobs(tmp_path,monkeypatch,capsys):
    root,campaign,payload=_fixture(tmp_path);calls=[];base_run=_runner(calls)
    def run(argv,input_data=None,limit=None):
        result=base_run(argv,input_data=input_data,limit=limit)
        if argv[0]=='/usr/local/bin/qsub' and len(calls)==1:
            (campaign/'.mot_ui/submissions/final_validation_input_generation.pending.json').write_text('{}')
        return result
    with pytest.raises(SystemExit):
        _invoke(monkeypatch,root,'submit',{**payload,'nonce':'8'*32},run)
    assert len(calls)==1
    assert json.loads(capsys.readouterr().out)['error']=='final_validation_submission_outcome_unknown'
    # Durable current-stage intent makes repeated calls fail closed too.
    with pytest.raises(SystemExit):
        _invoke(monkeypatch,root,'submit',{**payload,'nonce':'8'*32},run)
    assert len(calls)==1
    assert json.loads(capsys.readouterr().out)['error']=='final_validation_submission_outcome_unknown'
