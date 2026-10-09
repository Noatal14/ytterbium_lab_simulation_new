"""Pinned read-only Screening inspector and no-submit Refinement publisher."""
from __future__ import annotations
import base64,hashlib,json,math,os,re,stat,subprocess,sys,time
from pathlib import Path,PurePosixPath

def fail(code,status=20):print(json.dumps({"error":code}));raise SystemExit(status)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def no_links(root,path):
    current=root
    for part in path.relative_to(root).parts:
        current/=part
        if current.exists() and current.is_symlink():fail("transition_conflict")
def read_json(path,limit=1024*1024):
    try:
        row=path.lstat()
        if not stat.S_ISREG(row.st_mode) or path.is_symlink() or not 0<row.st_size<=limit:raise ValueError()
        return json.loads(path.read_text("utf-8"))
    except Exception:fail("transition_conflict")
def safe_status(raw,root):
    suffixes={'.json','.npy','.csv','.db','.sqlite','.png','.pdf','.pbs','.out','.err','.txt','.sh'}
    try:
        for record in raw.split(b'\0'):
            if not record:continue
            if len(record)<4 or record[:3]!=b'?? ':return False
            text=record[3:].decode();pure=PurePosixPath(text)
            if pure.is_absolute() or any(part in {'','.','..'} for part in pure.parts) or pure.parts[0] not in {'data','graphs'} or pure.suffix.lower() not in suffixes or not stat.S_ISREG(root.joinpath(*pure.parts).lstat().st_mode):return False
        return True
    except Exception:return False
def publish(path,data,mode=0o600):
    temporary=path.parent/f".{path.name}.{os.getpid()}.tmp";fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),mode)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        try:os.link(temporary,path,follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes()!=data:fail("transition_conflict")
    finally:
        try:temporary.unlink()
        except FileNotFoundError:pass
    parent=os.open(path.parent,os.O_RDONLY);os.fsync(parent);os.close(parent)
def atomic_json(path,payload):publish(path,(json.dumps(payload,sort_keys=True)+"\n").encode())
def timestamp(value):return isinstance(value,int) and not isinstance(value,bool) and 0<=value<=253402300799

def main():
    if len(sys.argv)!=5 or sys.argv[1] not in {'inspect','prepare'}:fail('invalid_request')
    operation,username,requested,encoded=sys.argv[1:]
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9._-]{0,31}',username):fail('invalid_request')
    try:root=Path(requested).resolve(strict=True);payload=json.loads(base64.urlsafe_b64decode(encoded))
    except Exception:fail('invalid_request')
    if root!=Path('/home')/username/'ytterbium_lab_simulation_new' or not isinstance(payload,dict):fail('remote_project_missing')
    inspect_keys={'campaign','commit','prepared_files','screen_files','screen_digest','screening_submission_key'};prepare_keys=inspect_keys|{'rows_digest','refine_files','nonce'}
    if set(payload)!=(inspect_keys if operation=='inspect' else prepare_keys):fail('invalid_request')
    relative=payload['campaign'];commit=payload['commit'];pure=PurePosixPath(relative)
    if not isinstance(relative,str) or pure.is_absolute() or pure.parts[:3]!=('data','optimization','mot_2d') or any(part in {'','.','..'} for part in pure.parts) or not re.fullmatch(r'[0-9a-f]{40}',str(commit)):fail('invalid_request')
    campaign=root.joinpath(*pure.parts);no_links(root,campaign)
    try:
        head=subprocess.run(['/usr/bin/git','rev-parse','--verify','HEAD^{commit}'],cwd=root,text=True,capture_output=True,timeout=10,check=True).stdout.strip()
        dirty=subprocess.run(['/usr/bin/git','status','--porcelain=v1','-z','--untracked-files=all'],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=True).stdout
        branch=subprocess.run(['/usr/bin/git','branch','--show-current'],cwd=root,text=True,capture_output=True,timeout=10,check=True).stdout.strip()
    except Exception:fail('remote_checkout_mismatch')
    if head!=commit or not safe_status(dirty,root) or not branch:fail('remote_checkout_mismatch')
    prepared=payload['prepared_files'];screen_hashes=payload['screen_files']
    if not isinstance(prepared,dict) or len(prepared)!=72 or not isinstance(screen_hashes,dict) or set(screen_hashes)!={'campaign.json','screen/tasks.json','jobs/02_screen.pbs'}:fail('invalid_request')
    if any(not re.fullmatch(r'[0-9a-f]{64}',str(value)) for value in [*prepared.values(),*screen_hashes.values(),payload['screen_digest'],payload['screening_submission_key']]):fail('invalid_request')
    if hashlib.sha256(json.dumps(screen_hashes,sort_keys=True).encode()).hexdigest()!=payload['screen_digest']:fail('invalid_request')
    for name,expected in prepared.items():
        if name==f'{relative}/campaign.json':continue
        path=root.joinpath(*PurePosixPath(name).parts);no_links(root,path)
        if not path.is_file() or sha(path)!=expected:fail('remote_preparation_invalid')
    manifest=read_json(campaign/'campaign.json')
    for name,expected in screen_hashes.items():
        if name=='campaign.json':continue
        path=campaign/name;no_links(campaign,path)
        if not path.is_file() or sha(path)!=expected:fail('transition_conflict')
    if manifest.get('stage')=='screen' and sha(campaign/'campaign.json')!=screen_hashes['campaign.json']:fail('transition_conflict')
    metadata=campaign/'.mot_ui';transitions=metadata/'transitions';submissions=metadata/'submissions'
    for path in (metadata,transitions,submissions,campaign/'screen',campaign/'jobs'):no_links(campaign,path)
    screen_transition=read_json(transitions/'screen.json');smoke_submission=read_json(submissions/'smoke.json');screen_submission=read_json(submissions/'screening.json')
    smoke_key=hashlib.sha256(json.dumps({'campaign':relative,'commit':commit,'manifest':prepared[f'{relative}/campaign.json'],'pbs':prepared[f'{relative}/jobs/01_smoke.pbs']},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    smoke_keys={'version','submission_key','nonce','job_file','commit','created_unix_s','status','job_id','completed_unix_s'}
    if set(smoke_submission)!=smoke_keys or smoke_submission.get('version')!=1 or smoke_submission.get('status')!='submitted' or smoke_submission.get('submission_key')!=smoke_key or smoke_submission.get('commit')!=commit or smoke_submission.get('job_file')!=f'{relative}/jobs/01_smoke.pbs' or not re.fullmatch(r'[0-9a-f]{32}',str(smoke_submission.get('nonce',''))) or not re.fullmatch(r'\d+(?:\[\])?\.zeus-master',str(smoke_submission.get('job_id',''))) or not timestamp(smoke_submission.get('created_unix_s')) or not timestamp(smoke_submission.get('completed_unix_s')) or smoke_submission['completed_unix_s']<smoke_submission['created_unix_s']:fail('submission_record_invalid')
    transition_keys={'status','nonce','job_id','smoke_digest','points','artifact_count','commit','submission_key','transition_files','completed_unix_s'}
    if set(screen_transition)!=transition_keys or screen_transition.get('status')!='screening_prepared' or screen_transition.get('submission_key')!=smoke_key or screen_transition.get('job_id')!=smoke_submission.get('job_id') or not re.fullmatch(r'[0-9a-f]{32}',str(screen_transition.get('nonce',''))) or not re.fullmatch(r'[0-9a-f]{64}',str(screen_transition.get('smoke_digest',''))) or not isinstance(screen_transition.get('points'),list) or screen_transition.get('artifact_count')!=3*len(screen_transition['points']) or hashlib.sha256(json.dumps(screen_transition['points'],sort_keys=True).encode()).hexdigest()!=screen_transition['smoke_digest'] or screen_transition.get('transition_files')!=screen_hashes or screen_transition.get('commit')!=commit or not timestamp(screen_transition.get('completed_unix_s')):fail('transition_conflict')
    if set(screen_submission)!={'version','status','submission_key','transition_digest','nonce','job_file','commit','job_id','created_unix_s','completed_unix_s'} or screen_submission.get('version')!=1 or screen_submission.get('status')!='submitted' or screen_submission.get('submission_key')!=payload['screening_submission_key'] or screen_submission.get('transition_digest')!=payload['screen_digest'] or screen_submission.get('commit')!=commit or screen_submission.get('job_file')!=f'{relative}/jobs/02_screen.pbs' or not re.fullmatch(r'[0-9a-f]{32}',str(screen_submission.get('nonce',''))) or not re.fullmatch(r'\d+\[\]\.zeus-master',str(screen_submission.get('job_id',''))) or not timestamp(screen_submission.get('created_unix_s')) or not timestamp(screen_submission.get('completed_unix_s')) or screen_submission['completed_unix_s']<screen_submission['created_unix_s']:fail('submission_record_invalid')
    state_dir=transitions;receipt=state_dir/'refine.json';pending=state_dir/'refine.pending.json';lock=state_dir/'refine.lock'
    if manifest.get('stage')=='refine':
        record=read_json(receipt)
        exact={'status','nonce','job_id','rows_digest','rows','refine_files','commit','screening_submission_key','screen_digest','completed_unix_s'}
        if set(record)!=exact or record.get('status')!='refinement_prepared' or record.get('job_id')!=screen_submission['job_id'] or record.get('commit')!=commit or record.get('screening_submission_key')!=payload['screening_submission_key'] or record.get('screen_digest')!=payload['screen_digest'] or not re.fullmatch(r'[0-9a-f]{32}',str(record.get('nonce',''))) or not timestamp(record.get('completed_unix_s')) or not isinstance(record.get('rows'),list) or hashlib.sha256(json.dumps(record['rows'],sort_keys=True).encode()).hexdigest()!=record.get('rows_digest') or not isinstance(record.get('refine_files'),dict) or set(record['refine_files'])!={'campaign.json','screening_candidates.json','refine/tasks.json','jobs/03_refine_round_01.pbs','jobs/03_refine_round_02.pbs','jobs/03_refine_round_03.pbs','jobs/03_refine_round_04.pbs','jobs/03_submit_refinement_chain.sh'}:fail('transition_outcome_unknown')
        for name,expected in record['refine_files'].items():
            path=campaign/name;no_links(campaign,path)
            if not re.fullmatch(r'[0-9a-f]{64}',str(expected)) or not path.is_file() or sha(path)!=expected:fail('transition_outcome_unknown')
        try:
            from copy import deepcopy
            screen_manifest=deepcopy(manifest);screen_manifest['stage']='screen';screen_manifest['stages'].pop('refine',None)
            canonical_screen=(json.dumps(screen_manifest,indent=2,sort_keys=True)+'\n').encode()
            if hashlib.sha256(canonical_screen).hexdigest()!=screen_hashes['campaign.json']:raise ValueError()
            from workflow_api.mot_2d_screen import validate_screen_outputs
            canonical_rows=validate_screen_outputs(campaign,screen_manifest)
            if canonical_rows!=record['rows']:raise ValueError()
            from workflow_api.mot_2d_plan import render_refine_transition
            canonical_refine=render_refine_transition(screen_manifest,campaign,root,canonical_rows)
            if {name:hashlib.sha256(data).hexdigest() for name,data in canonical_refine.items()}!=record['refine_files']:raise ValueError()
        except Exception:fail('transition_outcome_unknown')
        print(json.dumps({'lifecycle':'refinement_prepared','job_id':screen_submission['job_id'],'raw_state':'F','exit_status':0,'task_count':len(manifest['s0_values'])*3,'counts':{'queued':0,'running':0,'held':0,'succeeded':len(manifest['s0_values'])*3,'failed':0},'rows':record['rows'],'branch':branch}));return
    if manifest.get('stage')!='screen':fail('campaign_not_screen')
    job_id=screen_submission['job_id'];task_count=len(manifest['s0_values'])*3
    try:
        result=subprocess.run(['/usr/local/bin/qstat','-x','-t','-f',job_id],cwd=root,text=True,capture_output=True,timeout=20,check=False)
        if result.returncode or result.stderr:fail('scheduler_unavailable')
        from workflow_api.zeus_snapshot import _parse_qstat
        jobs=_parse_qstat(result.stdout)
    except Exception:fail('scheduler_unavailable')
    prefix=job_id.replace('[].zeus-master','');children={f'{prefix}[{index}].zeus-master' for index in range(task_count)};identifiers=[row.get('id') for row in jobs];by_id={row['id']:row for row in jobs}
    if len(identifiers)!=len(set(identifiers)) or set(identifiers) not in (children,children|{job_id}) or len(jobs) not in {task_count,task_count+1}:fail('scheduler_unavailable')
    child_rows=[by_id[name] for name in sorted(children)];counts={'queued':0,'running':0,'held':0,'succeeded':0,'failed':0}
    unknown=False
    for row in child_rows:
        if not {'id','state','raw_state','exit_status'}<=set(row) or row['state'] not in {'queued','running','held_attention','completed_success','completed_failed','unknown'} or not isinstance(row['raw_state'],str) or row['exit_status'] is not None and (not isinstance(row['exit_status'],int) or isinstance(row['exit_status'],bool)):fail('scheduler_unavailable')
        if row['state']=='completed_success' and row['exit_status']!=0:fail('scheduler_unavailable')
        unknown|=row['state']=='unknown';key={'queued':'queued','running':'running','held_attention':'held','completed_success':'succeeded'}.get(row['state'],'failed');counts[key]+=1
    if counts['held']:lifecycle='screen_held'
    elif counts['running']:lifecycle='screen_running'
    elif counts['queued']:lifecycle='screen_queued'
    elif unknown:lifecycle='screen_status_unknown'
    elif counts['failed']:lifecycle='screen_failed'
    else:
        from workflow_api.mot_2d_screen import ScreenValidationError,validate_screen_outputs
        required=[]
        for task in read_json(campaign/'screen/tasks.json'):
            directory=campaign/'screen'/(f"s0_{float(task['s0']):.6f}".replace('.','p'))/f"worker{int(task['worker'])}"
            required.extend([directory/'summary.json',directory/'joint_screening.db',*[directory/'trials'/f'trial_{number:04d}.json' for number in range(17)]])
        if any(not path.exists() for path in required):lifecycle='awaiting_outputs';rows=[]
        else:
            try:rows=validate_screen_outputs(campaign,manifest)
            except Exception:lifecycle='outputs_invalid';rows=[]
            else:lifecycle='ready_to_prepare_refinement'
    if lifecycle!='ready_to_prepare_refinement' or operation=='inspect':
        print(json.dumps({'lifecycle':lifecycle,'job_id':job_id,'raw_state':'F' if sum((counts['succeeded'],counts['failed']))==task_count else '?','exit_status':0 if counts['succeeded']==task_count else None,'task_count':task_count,'counts':counts,'rows':rows if lifecycle=='ready_to_prepare_refinement' else [],'branch':branch}));return
    rows_digest=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
    if rows_digest!=payload['rows_digest']:fail('transition_conflict')
    from workflow_api.mot_2d_plan import render_refine_transition
    rendered=render_refine_transition(manifest,campaign,root,rows);hashes={name:hashlib.sha256(data).hexdigest() for name,data in rendered.items()}
    if hashes!=payload['refine_files']:fail('transition_conflict')
    nonce=payload['nonce']
    if not re.fullmatch(r'[0-9a-f]{32}',str(nonce)):fail('invalid_request')
    try:lock.mkdir()
    except FileExistsError:fail('transition_busy')
    try:
        if receipt.exists() or pending.exists():fail('transition_outcome_unknown')
        # Re-establish every mutable authorization fact while holding the lock.
        latest_transition=read_json(transitions/'screen.json');latest_smoke=read_json(submissions/'smoke.json');latest_submission=read_json(submissions/'screening.json')
        if latest_transition!=screen_transition or latest_smoke!=smoke_submission or latest_submission!=screen_submission:fail('transition_conflict')
        check=subprocess.run(['/usr/local/bin/qstat','-x','-t','-f',job_id],cwd=root,text=True,capture_output=True,timeout=20,check=False)
        if check.returncode or check.stderr:fail('scheduler_unavailable')
        from workflow_api.zeus_snapshot import _parse_qstat
        locked_list=_parse_qstat(check.stdout);locked_ids=[row.get('id') for row in locked_list];locked_jobs={row['id']:row for row in locked_list}
        if len(locked_ids)!=len(set(locked_ids)) or set(locked_ids) not in (children,children|{job_id}) or any(locked_jobs[name]['state']!='completed_success' or locked_jobs[name]['exit_status']!=0 for name in children):fail('screen_status_unknown')
        try:locked_rows=validate_screen_outputs(campaign,manifest)
        except Exception:fail('screen_outputs_invalid')
        if hashlib.sha256(json.dumps(locked_rows,sort_keys=True).encode()).hexdigest()!=rows_digest:fail('transition_conflict')
        locked_rendered=render_refine_transition(manifest,campaign,root,locked_rows);locked_hashes={name:hashlib.sha256(data).hexdigest() for name,data in locked_rendered.items()}
        if locked_hashes!=hashes:fail('transition_conflict')
        atomic_json(pending,{'status':'refinement_pending','nonce':nonce,'job_id':job_id,'rows_digest':rows_digest,'refine_files':hashes,'commit':commit,'screening_submission_key':payload['screening_submission_key'],'screen_digest':payload['screen_digest'],'created_unix_s':int(time.time())})
        for name,data in rendered.items():
            if name=='campaign.json':continue
            target=campaign/name;target.parent.mkdir(parents=True,exist_ok=True);no_links(campaign,target);publish(target,data,0o755 if target.suffix in {'.pbs','.sh'} else 0o644)
        current=(campaign/'campaign.json').read_bytes()
        if hashlib.sha256(current).hexdigest()!=screen_hashes['campaign.json']:fail('transition_conflict')
        temporary=campaign/f'.campaign.{nonce}.tmp'
        with temporary.open('xb') as stream:stream.write(rendered['campaign.json']);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,campaign/'campaign.json');parent=os.open(campaign,os.O_RDONLY);os.fsync(parent);os.close(parent)
        record={'status':'refinement_prepared','nonce':nonce,'job_id':job_id,'rows_digest':rows_digest,'rows':locked_rows,'refine_files':hashes,'commit':commit,'screening_submission_key':payload['screening_submission_key'],'screen_digest':payload['screen_digest'],'completed_unix_s':int(time.time())};atomic_json(receipt,record);pending.unlink();parent=os.open(state_dir,os.O_RDONLY);os.fsync(parent);os.close(parent)
    finally:
        try:lock.rmdir()
        except OSError:pass
    print(json.dumps({'lifecycle':'refinement_prepared','job_id':job_id,'raw_state':'F','exit_status':0,'task_count':task_count,'counts':counts,'rows':rows,'branch':branch}))
if __name__=='__main__':main()
