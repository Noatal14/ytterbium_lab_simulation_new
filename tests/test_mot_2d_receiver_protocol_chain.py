"""On-disk protocol integration: real workers, receipts and receiver transitions.

The SSH boundary maps a logical Zeus checkout to a temporary clone. Only the
physical trajectory solver and scheduler are replaced; public coordinator
payloads, receiver programs, Git, NPY hashes, Optuna and validators stay real.
"""
from __future__ import annotations

import base64
from contextlib import redirect_stdout
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

CODE = Path(__file__).resolve().parents[1]


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(root, commit, acceptance):
    from lab_setup.physical_specification import (LABORATORY_PHYSICAL_SPECIFICATION,
        LABORATORY_SPEC_VERSION, LABORATORY_SPEC_SHA256, CANONICAL_ZEEMAN_PROFILE_SHA256,
        CANONICAL_ZEEMAN_PROFILE_NAME)
    from workflow_api.acceptance_profile import load_acceptance_profile
    from workflow_api.mot_2d_sources import inspect_source
    directory = root / 'data/particle_states/after_zeeman' / ('ui_acceptance/source' if acceptance else 'source')
    directory.mkdir(parents=True)
    initial, available = (32, 32) if acceptance else (50000, 40000)
    profile = LABORATORY_PHYSICAL_SPECIFICATION['canonical_zeeman_profile']
    arrays = {key: list(profile[key]) for key in ('radii_m', 'positions_m', 'tilt_angles_deg')}
    for seed in range(3000, 3035):
        path = directory / f'production_zeeman_n{initial}_dt40us_seed{seed}.npy'
        np.save(path, np.zeros((available, 6)))
        metadata = {'shape': [available, 6], 'dtype': 'float64', 'n_survivors': available,
                    'survival_fraction': available / initial, 'output_sha256': _sha(path),
                    'laboratory_spec_version': LABORATORY_SPEC_VERSION,
                    'laboratory_spec_sha256': LABORATORY_SPEC_SHA256,
                    'zeeman_profile_sha256': CANONICAL_ZEEMAN_PROFILE_SHA256,
                    'parameters': {'seed': seed, 'resolved_zeeman_magnet_profile': CANONICAL_ZEEMAN_PROFILE_NAME,
                                   'n_initial_atoms': initial, 'dt_s': 4e-5, 'zeeman_field_config': arrays},
                    'software': {'git_commit': commit}}
        if acceptance:
            metadata['acceptance'] = load_acceptance_profile().provenance()
        path.with_suffix('.json').write_text(json.dumps(metadata))
    return inspect_source(directory, root, acceptance_profile_id='ui_acceptance_v1' if acceptance else None)


class _Protocol:
    def __init__(self, tmp_path, monkeypatch, acceptance):
        from workflow_api.mot_2d_plan import build_plan, materialize
        from workflow_api.repository_snapshot import RepositorySnapshot
        self.mp = monkeypatch
        self.local = tmp_path / 'local'
        self.local.mkdir()
        self.git = Path(shutil.which('git')).resolve()
        self.ssh = Path(shutil.which('ssh')).resolve()
        for name in ('workflow_api', 'studies', 'simulations', 'utils', 'lab_setup', 'atomsmltr/src'):
            shutil.copytree(CODE / name, self.local / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copyfile(CODE / 'config.py', self.local / 'config.py')
        (self.local / '.gitignore').write_text('data/\n__pycache__/\n*.pyc\n')
        for args in (['init', '-q'], ['add', '.'], ['-c', 'user.name=Protocol test', '-c', 'user.email=protocol@example.invalid', 'commit', '-qm', 'Frozen protocol code']):
            subprocess.run([str(self.git), '-C', str(self.local), *args], check=True)
        self.commit = subprocess.check_output([str(self.git), '-C', str(self.local), 'rev-parse', 'HEAD'], text=True).strip()
        source = _source(self.local, self.commit, acceptance)
        plan = build_plan(self.local, name='protocol-chain', slug='protocol-chain', s0_values=[1.3], source=source,
                          snapshot=RepositorySnapshot(self.commit), acceptance_profile_id='ui_acceptance_v1' if acceptance else None)
        materialize(plan)
        self.relative = 'data/optimization/mot_2d/' + ('ui_acceptance/' if acceptance else '') + 'protocol-chain'
        self.logical = '/home/tal.noa/' + ('ytterbium_lab_simulation_ui_acceptance' if acceptance else 'ytterbium_lab_simulation_new')
        self.remote = tmp_path / 'home/tal.noa' / Path(self.logical).name
        self.remote.parent.mkdir(parents=True)
        subprocess.run([str(self.git), 'clone', '-q', str(self.local), str(self.remote)], check=True)
        shutil.copytree(self.local / 'data', self.remote / 'data')
        self.campaign = self.remote / self.relative
        self.jobs = {}
        self.qsub_calls = []
        self.boundary_calls = []
        self.dto = []
        self.mode = 'acceptance' if acceptance else 'scientific'
        self.smoke_qsub = tmp_path / 'smoke-qsub'
        self.smoke_capture = tmp_path / 'smoke-qsub-input'
        self.smoke_qsub.write_text('#!/bin/sh\ncat > ' + str(self.smoke_capture) + "\nprintf '70000.zeus-master\\n'\n")
        self.smoke_qsub.chmod(0o700)
        self._real_run = subprocess.run
        self._install_scheduler()
        self._install_transport()
        self._install_workers()
        from workflow_api.discovery import build_registry
        self.campaign_id = next(key for key, value in build_registry(self.local).items() if value.manifest.parent.name == 'protocol-chain')
        self.request = {'campaign_id': self.campaign_id, 'username': 'tal.noa', 'project_directory': self.logical}

    def _install_scheduler(self):
        def run(argv, *args, **kwargs):
            def emitted(raw):
                sink = kwargs.get('stdout')
                if hasattr(sink, 'write'):
                    sink.write(raw)
                    return subprocess.CompletedProcess(argv, 0)
                return subprocess.CompletedProcess(argv, 0, raw.decode() if kwargs.get('text') else raw, '' if kwargs.get('text') else b'')
            command = str(argv[0])
            if command.endswith('/qsub'):
                content = kwargs.get('input', b'')
                if isinstance(content, str): content = content.encode()
                array = bool(re.search(rb'#PBS -J', content)) or '-J' in argv or b'PBS_ARRAY_INDEX' in content
                job = str(70000 + len(self.jobs)) + ('[]' if array else '') + '.zeus-master'
                dep = next((str(x).split('depend=afterok:', 1)[1] for x in argv if str(x).startswith('depend=afterok:')), None)
                array_spec = str(argv[argv.index('-J') + 1]) if '-J' in argv else ''
                self.jobs[job] = {'data': content, 'dependency': dep, 'array_spec': array_spec}
                self.qsub_calls.append((tuple(argv), content))
                raw = (job + '\n').encode()
                return emitted(raw)
            if command.endswith('/qstat'):
                job = str(argv[-1]); data = self.jobs[job]; content = data['data']
                match = re.search(rb'#PBS -J 0-(\d+)', content)
                count = int(match[1]) + 1 if match else (int(data.get('array_spec', '').split(':')[0].split('-')[-1]) + 1 if data.get('array_spec') else 1)
                rows = [f'Job Id: {job}', '    Job_Name = protocol', '    job_state = F', '    Exit_status = 0']
                if data['dependency']: rows.append('    depend = afterok:' + data['dependency'] + '@zeus-master')
                if '[]' in job:
                    rows += ['    array = True', f'    array_indices_submitted = 0-{count-1}', '    array_state_count = Queued:0 Running:0 Exiting:0 Expired:' + str(count)]
                    for index in range(count):
                        rows += [f'Job Id: {job.replace("[]", f"[{index}]")}', '    Job_Name = protocol', '    job_state = F', '    Exit_status = 0']
                raw = ('\n'.join(rows) + '\n').encode()
                return emitted(raw)
            if len(argv) > 2 and argv[1] == '-m' and argv[2] in {'studies.mot_2d.optimization', 'studies.mot_2d.production'}:
                from studies.mot_2d import optimization, production
                if argv[2].endswith('optimization'):
                    parsed = optimization.parse_args(argv[3:]); optimization.optimize_mot(parsed)
                else:
                    production.run_seeds(production.parse_args(argv[3:]))
                return subprocess.CompletedProcess(argv, 0)
            return self._real_run(argv, *args, **kwargs)
        self.mp.setattr(subprocess, 'run', run)

    def _install_workers(self):
        from studies import mot_2d_s0_campaign as worker
        from studies.mot_2d import optimization
        self.mp.setattr(worker, 'REPOSITORY_ROOT', self.remote)
        self.mp.setattr(optimization, '__file__', str(self.remote / 'studies/mot_2d/optimization.py'))
        # Return one actual-shaped survivor per ensemble through the ordinary
        # evaluator/writers, without evaluating physical forces in this test.
        self.mp.setattr(optimization, 'mot_simulation_paired_ensembles',
                        lambda **kwargs: [([], 1, np.zeros((1, 6))) for _ in kwargs['survivor_state_ensembles']])

    def _install_transport(self):
        from workflow_api import pinned_ssh, acceptance_remote
        original_authorize = acceptance_remote.assert_campaign_target
        def authorize(manifest, username, project, campaign_path=None):
            physical = Path(str(project))
            if physical == self.remote:
                if campaign_path is not None:
                    path = Path(str(campaign_path))
                    if path.is_absolute(): campaign_path = path.relative_to(self.remote).as_posix()
                project = self.logical
            return original_authorize(manifest, username, project, campaign_path)
        self.mp.setattr(acceptance_remote, 'assert_campaign_target', authorize)
        def call(runner, operation, profile, payload):
            definition = pinned_ssh._RECEIVERS[runner._policy.receiver]
            old_cwd = Path.cwd(); stdout = io.StringIO()
            self.boundary_calls.append((runner._policy.receiver.value, operation.value, dict(payload)))
            with self.mp.context() as child:
                child.chdir(self.remote)
                if definition.embedded_smoke_receiver:
                    from workflow_api.zeus_submission import _REMOTE_SCRIPT
                    source = _REMOTE_SCRIPT.replace("home=pathlib.Path('/home')/username", f"home=pathlib.Path({str(self.remote.parent)!r})")
                    source = source.replace('/usr/local/bin/qsub', str(self.smoke_qsub))
                    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
                    child.setattr(sys, 'argv', ['receiver', operation.value, profile.username, str(self.remote), encoded])
                    with redirect_stdout(stdout):
                        try: exec(compile(source, '<actual-smoke-receiver>', 'exec'), {'__name__': '__main__'})
                        except SystemExit as error: code = error.code or 0
                        else: code = 0
                else:
                    module = importlib.import_module('workflow_api.' + definition.filename.removesuffix('.py'))
                    real_path = Path
                    def mapped(value='.'):
                        text = str(value)
                        if text == '/home': return self.remote.parent.parent
                        if text == self.logical: return self.remote
                        return real_path(value)
                    mapped.cwd = Path.cwd
                    child.setattr(module, 'Path', mapped)
                    if runner._policy.receiver in {pinned_ssh.ReceiverKind.SENSITIVITY_PREPARATION, pinned_ssh.ReceiverKind.PRODUCTION_PREPARATION, pinned_ssh.ReceiverKind.FINALIZATION}:
                        child.setattr(sys, 'argv', ['receiver', operation.value])
                        child.setattr(sys, 'stdin', io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode())))
                    else:
                        child.setattr(sys, 'argv', ['receiver', operation.value, profile.username, self.logical, base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()])
                    with redirect_stdout(stdout):
                        try: module.main()
                        except SystemExit as error:
                            code = error.code or 0
                            trace = error.__traceback__
                            while trace:
                                if trace.tb_frame.f_code.co_name == 'main':
                                    print('failure-site', trace.tb_lineno, {key: trace.tb_frame.f_locals.get(key) for key in ('hashes', 'payload')}, file=stdout)
                                trace = trace.tb_next
                        else: code = 0
            if self.smoke_capture.exists() and '70000.zeus-master' not in self.jobs:
                content = self.smoke_capture.read_bytes()
                self.jobs['70000.zeus-master'] = {'data': content, 'dependency': None}
                self.qsub_calls.append((('fake-embedded-qsub',), content))
            os.chdir(old_cwd)
            if code:
                raise AssertionError(f'Actual receiver {runner._policy.receiver.value}/{operation.value} failed {code}: {stdout.getvalue()}')
            return subprocess.CompletedProcess([], code, stdout.getvalue().encode(), b'')
        self.mp.setattr(pinned_ssh.PinnedSshRunner, 'run', call)

    def coordinator(self, module, name):
        coordinator = getattr(importlib.import_module('workflow_api.' + module), name)(self.local, self.ssh, self.git)
        parsers = {
            'zeus_submission': (None, 'parseSmokeSubmissionPreview', 'parseSmokeSubmissionResult'),
            'zeus_screening': ('parseSmokeLifecycle', 'parseScreeningPreview', 'parseScreeningResult'),
            'zeus_screen_submission': (None, 'parseScreeningSubmissionPreview', 'parseScreeningSubmissionResult'),
            'zeus_refinement': ('parseScreeningLifecycle', 'parseRefinementPreview', 'parseRefinementResult'),
            'zeus_refinement_submission': ('parseRefinementChainStatus', 'parseRefinementSubmissionPreview', 'parseRefinementSubmissionResult'),
            'zeus_confirmation': ('parseRefinementLifecycle', 'parseConfirmationPreview', 'parseConfirmationResult'),
            'zeus_confirmation_submission': ('parseConfirmationSubmissionStatus', 'parseConfirmationSubmissionPreview', 'parseConfirmationSubmissionResult'),
            'zeus_sensitivity': ('parseSensitivityStatus', 'parseSensitivityPreview', 'parseSensitivityResult'),
            'zeus_sensitivity_submission': ('parseSensitivitySubmissionStatus', 'parseSensitivitySubmissionPreview', 'parseSensitivitySubmissionResult'),
            'zeus_production': ('parseProductionStatus', 'parseProductionPreview', 'parseProductionResult'),
            'zeus_production_submission': ('parseProductionSubmissionStatus', 'parseProductionSubmissionPreview', 'parseProductionSubmissionResult'),
            'zeus_finalization': ('parseFinalizationStatus', 'parseFinalizationPreview', 'parseFinalizationResult'),
        }
        for method, parser in zip(('status', 'preview', 'confirm'), parsers[module]):
            if parser is None or not hasattr(coordinator, method): continue
            original = getattr(coordinator, method)
            def wrapped(*args, _original=original, _method=method, _parser=parser, **kwargs):
                result = _original(*args, **kwargs)
                self.dto.append({'module': 'domain', 'parser': _parser, 'coordinator': module, 'method': _method, 'value': result})
                directory = os.environ.get('UI_PROTOCOL_DTO_DIRECTORY')
                if directory:
                    target = Path(directory); target.mkdir(parents=True, exist_ok=True)
                    (target / (self.mode + '.json')).write_text(json.dumps({'kind': 'TEST_ONLY_hermetic_protocol_DTOs', 'mode': self.mode, 'responses': self.dto}, indent=2) + '\n')
                return result
            setattr(coordinator, method, wrapped)
        return coordinator

    def confirm(self, coordinator):
        preview = coordinator.preview(self.request, session_id='protocol')
        token = {'preview_token': preview['preview_token']}
        before = len(self.qsub_calls)
        result = coordinator.confirm(token, session_id='protocol')
        assert coordinator.confirm(token, session_id='protocol') == result
        assert len(self.qsub_calls) - before <= 4
        return result

    def work(self, stage):
        from studies import mot_2d_s0_campaign as worker
        with self.mp.context() as child:
            child.chdir(self.remote)
            if stage == 'smoke': worker.smoke(SimpleNamespace(campaign=str(self.campaign), s0_index=0))
            elif stage in {'screen', 'refine'}:
                tasks = json.loads((self.campaign / stage / 'tasks.json').read_text())
                for index in range(len(tasks)):
                    args = SimpleNamespace(campaign=str(self.campaign), task_index=index)
                    if stage == 'screen': worker.screen_task(args)
                    else:
                        from workflow_api.mot_2d_spec import refinement_targets
                        for target in refinement_targets(json.loads((self.campaign / 'campaign.json').read_text())):
                            args.target_trials = target
                            worker.refine_task(args)
            else:
                tasks = json.loads((self.campaign / stage / 'tasks.json').read_text())
                for index in range(len(tasks)):
                    args = SimpleNamespace(campaign=str(self.campaign), task_index=index)
                    getattr(worker, stage + '_task')(args)


@pytest.mark.parametrize('acceptance', [False, True], ids=['scientific', 'TEST-ONLY'])
def test_full_on_disk_receiver_protocol_chain(tmp_path, monkeypatch, acceptance):
    chain = _Protocol(tmp_path, monkeypatch, acceptance)
    smoke = chain.coordinator('zeus_submission', 'ZeusSmokeSubmissionCoordinator')
    chain.confirm(smoke)
    chain.work('smoke')
    screen_prepare = chain.coordinator('zeus_screening', 'ZeusScreeningCoordinator')
    assert screen_prepare.status(chain.request, session_id='protocol')['lifecycle'] == 'ready_to_prepare_screen'
    chain.confirm(screen_prepare)
    assert screen_prepare.status(chain.request, session_id='protocol')['lifecycle'] == 'screen_prepared'
    screen_submit = chain.coordinator('zeus_screen_submission', 'ZeusScreenSubmissionCoordinator')
    chain.confirm(screen_submit)
    chain.work('screen')
    refine_prepare = chain.coordinator('zeus_refinement', 'ZeusRefinementCoordinator')
    assert refine_prepare.status(chain.request)['lifecycle'] == 'ready_to_prepare_refinement'
    chain.confirm(refine_prepare)
    assert refine_prepare.status(chain.request)['lifecycle'] == 'refinement_prepared'
    refine_submit = chain.coordinator('zeus_refinement_submission', 'ZeusRefinementSubmissionCoordinator')
    chain.confirm(refine_submit)
    chain.work('refine')
    from workflow_api.mot_2d_screen import validate_refine_outputs
    validate_refine_outputs(chain.campaign, json.loads((chain.campaign / 'campaign.json').read_text()))
    confirmation_prepare = chain.coordinator('zeus_confirmation', 'ZeusConfirmationCoordinator')
    assert confirmation_prepare.status(chain.request)['chain']['status'] == 'ready_to_prepare_confirmation'
    chain.confirm(confirmation_prepare)
    assert confirmation_prepare.status(chain.request)['chain']['status'] == 'confirmation_prepared'
    confirmation_submit = chain.coordinator('zeus_confirmation_submission', 'ZeusConfirmationSubmissionCoordinator')
    chain.confirm(confirmation_submit)
    chain.work('confirmation')
    from workflow_api.mot_2d_validation import validated_evaluation_outputs
    validated_evaluation_outputs(chain.campaign, json.loads((chain.campaign / 'campaign.json').read_text()), 'confirmation')
    sensitivity_prepare = chain.coordinator('zeus_sensitivity', 'ZeusSensitivityCoordinator')
    assert sensitivity_prepare.status(chain.request)['confirmation']['status'] == 'ready_to_prepare_sensitivity'
    chain.confirm(sensitivity_prepare)
    assert sensitivity_prepare.status(chain.request)['confirmation']['status'] == 'sensitivity_prepared'
    sensitivity_submit = chain.coordinator('zeus_sensitivity_submission', 'ZeusSensitivitySubmissionCoordinator')
    chain.confirm(sensitivity_submit)
    chain.work('sensitivity')
    production_prepare = chain.coordinator('zeus_production', 'ZeusProductionCoordinator')
    assert production_prepare.status(chain.request)['sensitivity']['status'] == 'ready_to_prepare_production'
    chain.confirm(production_prepare)
    assert production_prepare.status(chain.request)['sensitivity']['status'] == 'production_prepared'
    production_submit = chain.coordinator('zeus_production_submission', 'ZeusProductionSubmissionCoordinator')
    chain.confirm(production_submit)
    chain.work('production')
    from workflow_api.mot_2d_validation import validated_sealed_production_outputs
    validated_sealed_production_outputs(chain.campaign, json.loads((chain.campaign / 'campaign.json').read_text()), chain.remote)
    finalization = chain.coordinator('zeus_finalization', 'ZeusFinalizationCoordinator')
    assert finalization.status(chain.request)['production']['status'] == 'ready_to_finalize'
    chain.confirm(finalization)
    assert finalization.status(chain.request)['production']['status'] == 'campaign_complete'
    assert len(chain.qsub_calls) == 9  # smoke, screen, four refine rounds, confirmation, sensitivity, production
    # Reopening starts from the unchanged local smoke manifest. Every historical
    # status must prove its own receipt chain without changing remote artifacts.
    assert json.loads((chain.local / chain.relative / 'campaign.json').read_text())['stage'] == 'smoke'
    before = {p.relative_to(chain.remote).as_posix(): _sha(p) for p in (chain.remote / 'data').rglob('*') if p.is_file()}
    screen_prepare.status(chain.request, session_id='protocol')
    for coordinator in (refine_prepare, refine_submit, confirmation_prepare, confirmation_submit,
                        sensitivity_prepare, sensitivity_submit, production_prepare,
                        production_submit, finalization):
        coordinator.status(chain.request)
    after = {p.relative_to(chain.remote).as_posix(): _sha(p) for p in (chain.remote / 'data').rglob('*') if p.is_file()}
    assert after == before
    assert len(chain.qsub_calls) == 9
    assert json.loads((chain.campaign / 'campaign.json').read_text())['stage'] == 'complete'

    # Production preparation must bind the caller's nonce/job identity to the
    # exact durable Sensitivity submission, including during historical reads.
    from workflow_api.pinned_ssh import PinnedSshPolicy, PinnedSshRunner, ReceiverOperation
    from workflow_api.zeus_snapshot import ZeusProfile
    from copy import deepcopy
    original = next(payload for kind, operation, payload in reversed(chain.boundary_calls)
                    if kind == 'production_preparation' and operation == 'inspect')
    runner = PinnedSshRunner(PinnedSshPolicy.production_preparation(chain.local, chain.ssh, timeout=30))
    profile = ZeusProfile.parse({'username': 'tal.noa', 'project_directory': chain.logical})
    for key, value in [('sensitivity_submission_nonce', '0' * 32), ('sensitivity_job_id', '999[].zeus-master')]:
        changed = deepcopy(original); changed[key] = value
        with pytest.raises(AssertionError, match='sensitivity_submission_invalid'):
            runner.run(ReceiverOperation.INSPECT, profile, changed)
    # Even a completed manifest must retain its exact authenticated Sensitivity
    # predecessor.  A changed frozen field cannot hide behind a later stage.
    target = chain.campaign / 'campaign.json'
    saved_manifest = target.read_bytes()
    changed_manifest = json.loads(saved_manifest)
    changed_manifest['name'] = 'altered predecessor'
    target.write_text(json.dumps(changed_manifest, indent=2, sort_keys=True) + '\n')
    try:
        with pytest.raises(AssertionError, match='sensitivity_preparation_invalid'):
            runner.run(ReceiverOperation.INSPECT, profile, original)
    finally:
        target.write_bytes(saved_manifest)
    assert len(chain.qsub_calls) == 9
    from ui_campaign_contract_bridge import assert_campaign_client_contracts
    assert_campaign_client_contracts(chain.dto, acceptance=acceptance)
