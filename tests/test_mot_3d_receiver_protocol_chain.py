"""TEST ONLY hermetic 3D protocol: actual writers/receivers, fake force solver.

The completed upstream is produced by the real 2D protocol integration. Copying
its verified bytes is explicit fixture provisioning, not a claimed UI handoff.
"""
from contextlib import redirect_stdout
import base64
import hashlib
import importlib
import io
import inspect
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import shutil
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

import test_mot_2d_receiver_protocol_chain as two_d


class _Upstream(two_d._Protocol):
    def __init__(self, *args, **kwargs):
        mp = args[1]
        original_run = subprocess.run
        def prepare_clone(argv, *positional, **keywords):
            if 'init' in argv and '-C' in argv:
                destination = Path(argv[argv.index('-C') + 1]) / 'docs'
                shutil.copytree(two_d.CODE / 'docs', destination)
            return original_run(argv, *positional, **keywords)
        with mp.context() as child:
            child.setattr(subprocess, 'run', prepare_clone)
            super().__init__(*args, **kwargs)
        self._install_scheduler()

    def _install_workers(self):
        super()._install_workers()
        from studies.mot_2d import optimization
        # Two outputs exercise all_available loading beyond one search particle.
        self.mp.setattr(optimization, 'mot_simulation_paired_ensembles',
                        lambda **kw: [([], 2, np.zeros((2, 6))) for _ in kw['survivor_state_ensembles']])


def _completed_upstream(tmp_path, monkeypatch):
    created = []
    def factory(*args, **kwargs):
        chain = _Upstream(*args, **kwargs)
        created.append(chain)
        return chain
    with monkeypatch.context() as child:
        child.setattr(two_d, '_Protocol', factory)
        two_d.test_full_on_disk_receiver_protocol_chain(tmp_path, child, True)
    return created[0]


class _ThreeD:
    def __init__(self, upstream, monkeypatch):
        self.upstream, self.mp = upstream, monkeypatch
        self.local, self.remote = upstream.local, upstream.remote
        self.logical, self.git, self.ssh = upstream.logical, upstream.git, upstream.ssh
        self.dto = []
        # Existing bootstrap catalog consumes a completed local sealed source.
        shutil.copytree(upstream.remote / 'data', self.local / 'data', dirs_exist_ok=True)
        # Genuine source revision A -> independent 3D worker revision B.
        self.source_commit = upstream.commit
        upstream._real_run([str(self.git), '-C', str(self.local), '-c', 'user.name=Protocol test',
                            '-c', 'user.email=protocol@example.invalid', 'commit', '--allow-empty',
                            '-qm', 'Independent 3D protocol revision'], check=True)
        upstream.commit = upstream._real_run([str(self.git), '-C', str(self.local),
                                             'rev-parse', 'HEAD'], check=True,
                                            capture_output=True, text=True).stdout.strip()
        assert upstream.commit != self.source_commit
        upstream._real_run([str(self.git), '-C', str(self.remote), 'fetch', '-q',
                            str(self.local), 'HEAD'], check=True)
        upstream._real_run([str(self.git), '-C', str(self.remote), 'checkout', '-q',
                            '-B', 'main', 'FETCH_HEAD'], check=True)
        upstream.mp = monkeypatch
        upstream._install_scheduler()
        upstream._install_transport()
        upstream._install_workers()
        self._transport()
        from workflow_api.mot_3d_bootstrap import Mot3DDiscoveryBootstrapService
        with monkeypatch.context() as child:
            child.chdir(self.local)
            from studies import mot_3d_campaign
            child.setattr(mot_3d_campaign, '__file__', str(self.local / 'studies/mot_3d_campaign.py'))
            service = Mot3DDiscoveryBootstrapService(self.local, acceptance_profile_id='ui_acceptance_v1')
            bootstrap_status = service.status({})
            sources = bootstrap_status['sources']
            assert len(sources) == 1
            request = {'source_id': sources[0]['source_id'], 'campaign_name': 'TESTONLY_3D_PROTOCOL'}
            preview = service.preview(request, session_id='protocol3d')
            competing_preview = service.preview(request, session_id='protocol3d')
            result = service.confirm({'preview_token': preview['preview_token']}, session_id='protocol3d')
            self.dto.extend([
                {'client':'mot3d', 'parser':'parseMot3DBootstrapStatus', 'label':'bootstrap/status',
                 'value':bootstrap_status, 'args':[]},
                {'client':'mot3d', 'parser':'parseMot3DBootstrapPreview', 'label':'bootstrap/preview',
                 'value':preview, 'args':[{'sourceId':request['source_id'], 'campaignName':request['campaign_name']}]},
                {'client':'mot3d', 'parser':'parseMot3DBootstrapResult', 'label':'bootstrap/confirm',
                 'value':result, 'args':[request['campaign_name']]},
            ])
            assert service.confirm({'preview_token': preview['preview_token']}, session_id='protocol3d') == result
            reviewed = self.local / 'data/optimization/mot_3d/ui_acceptance/TESTONLY_3D_PROTOCOL'
            assert reviewed.is_dir()
            assert not (self.local / 'data/optimization/mot_3d/TESTONLY_3D_PROTOCOL').exists()
            before = {p.relative_to(reviewed): p.read_bytes() for p in reviewed.rglob('*') if p.is_file()}
            with pytest.raises(FileExistsError):
                service.confirm({'preview_token': competing_preview['preview_token']}, session_id='protocol3d')
            assert {p.relative_to(reviewed): p.read_bytes() for p in reviewed.rglob('*') if p.is_file()} == before
        self.relative = 'data/optimization/mot_3d/ui_acceptance/TESTONLY_3D_PROTOCOL'
        self.campaign = self.remote / self.relative
        from studies import mot_3d_campaign
        self.mp.setattr(mot_3d_campaign, '__file__', str(self.local / 'studies/mot_3d_campaign.py'))
        from workflow_api.discovery import build_registry
        self.campaign_id = next(key for key, value in build_registry(self.local).items()
                                if value.manifest.parent == self.local / self.relative)
        self.request = {'campaign_id': self.campaign_id, 'username': 'tal.noa', 'project_directory': self.logical}
        # Initial bootstrap preparation uses the same guarded streaming transfer
        # as the UI; no fixture copy publishes the 3D campaign on the remote side.
        from workflow_api.zeus_transfer import ZeusPreparationCoordinator
        preparation = ZeusPreparationCoordinator(self.local, self.ssh, self.git)
        before_jobs = len(upstream.qsub_calls)
        transfer_preview = preparation.preview(self.request, session_id='protocol3d')
        assert transfer_preview['campaign']['family'] == 'mot_3d'
        assert transfer_preview['artifacts']['ensemble_count'] == 20
        assert transfer_preview['artifacts']['total_count'] == 52
        transfer_result = preparation.confirm({'preview_token': transfer_preview['preview_token']}, session_id='protocol3d')
        assert preparation.confirm({'preview_token': transfer_preview['preview_token']}, session_id='protocol3d') == transfer_result
        assert len(upstream.qsub_calls) == before_jobs
        self.dto.extend([
            {'client':'domain', 'parser':'parseTransferPreview', 'label':'transfer/preview', 'value':transfer_preview, 'args':[]},
            {'client':'domain', 'parser':'parseTransferResult', 'label':'transfer/confirm', 'value':transfer_result, 'args':[]},
        ])
        self._physics()

    def _realm(self, child, root):
        # In production these are separate interpreters importing the exact
        # checkout files. Keep path authorization active in each fixture realm.
        from studies import mot_3d_campaign
        from workflow_api import mot_3d_workload
        for module, relative in ((mot_3d_campaign, 'studies/mot_3d_campaign.py'),
                                 (mot_3d_workload, 'workflow_api/mot_3d_workload.py')):
            assert two_d._sha(root / relative) == two_d._sha(two_d.CODE / relative)
            child.setattr(module, '__file__', str(root / relative))

    def _transport(self):
        from workflow_api import pinned_ssh
        previous = pinned_ssh.PinnedSshRunner.run
        def call(runner, operation, profile, payload):
            if not runner._policy.receiver.value.startswith('mot_3d_'):
                return previous(runner, operation, profile, payload)
            definition = pinned_ssh._RECEIVERS[runner._policy.receiver]
            module = importlib.import_module('workflow_api.' + definition.filename.removesuffix('.py'))
            output = io.StringIO()
            with self.mp.context() as child:
                child.chdir(self.remote)
                self._realm(child, self.remote)
                child.setattr(sys, 'argv', ['receiver', operation.value, profile.username, self.logical,
                    base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()])
                with redirect_stdout(output):
                    try:
                        if 'trusted_root_override' in inspect.signature(module.main).parameters:
                            module.main(trusted_root_override=self.remote)
                        else:
                            original_path = Path
                            def mapped(value='.'):
                                text = str(value)
                                prefix = '/home/tal.noa/'
                                if text.startswith(prefix) and '/' not in text[len(prefix):]:
                                    return original_path(self.remote.parent / text[len(prefix):])
                                return original_path(value)
                            child.setattr(module, 'Path', mapped)
                            module.main()
                    except SystemExit as error:
                        import traceback
                        failure_trace = traceback.format_exc()
                        code = error.code or 0
                    else:
                        code = 0
            assert code == 0, f'{runner._policy.receiver.value}/{operation.value}: {output.getvalue()}\n{failure_trace}'
            try:
                json.loads(output.getvalue())
            except ValueError as error:
                raise AssertionError(f'Actual receiver machine channel is not JSON: {output.getvalue()[:3000]!r}') from error
            return subprocess.CompletedProcess([], 0, output.getvalue().encode(), b'')
        self.mp.setattr(pinned_ssh.PinnedSshRunner, 'run', call)
        def transfer(runner, operation, profile, paths, expected_commit, payload):
            from workflow_api.zeus_transfer import _REMOTE_TRANSFER_SCRIPT
            source = _REMOTE_TRANSFER_SCRIPT.replace("home = pathlib.Path('/home') / username", f"home = pathlib.Path({str(self.remote.parent)!r})")
            output = io.StringIO()
            with self.mp.context() as child:
                child.chdir(self.remote)
                self._realm(child, self.remote)
                child.setattr(sys, 'argv', ['receiver', operation.value, profile.username, str(self.remote),
                    base64.urlsafe_b64encode(json.dumps(paths).encode()).decode(), expected_commit])
                child.setattr(sys, 'stdin', io.TextIOWrapper(io.BytesIO(payload)))
                with redirect_stdout(output):
                    try:
                        exec(compile(source, '<actual-bootstrap-transfer>', 'exec'), {'__name__':'__main__'})
                    except SystemExit as error:
                        code = error.code or 0
                    else:
                        code = 0
            assert code == 0, f'Actual bootstrap transfer {operation.value}: {output.getvalue()}'
            return code, output.getvalue().encode(), b''
        self.mp.setattr(pinned_ssh.PinnedSshRunner, 'transfer', transfer)

    def _physics(self):
        from config import Geometry
        from simulations import mot_3d, zeeman
        self.mp.setattr(zeeman, 'zeeman_simulation', lambda **kw: ([], np.zeros((kw['N_particles'], 6)), None))
        def force_boundary(states, **kw):
            grid = np.linspace(0, kw['t_max'], int(np.ceil(kw['t_max'] / kw['dt'])) + 1)
            values = np.zeros((6, len(grid)))
            # Deterministic force-boundary fixture favors non-seeded interior
            # profiles. It avoids the canonical selector's explicit rejection
            # of outward perturbations clipped onto a boundary nominal.
            config = kw['_3d_mot_config']
            captured = config['magnetic_gradient_G_cm'] != 2.5
            if 'blue_crossing_z_offset_m' in config:
                captured = captured and -0.05 < config['blue_crossing_z_offset_m'] < 0.05
            position = np.asarray(Geometry.MOT_3D_CENTER_M) + (0 if captured else np.array([1., 0., 0.]))
            values[:3] = position[:, None]
            return [SimpleNamespace(t=grid, y=values.copy()) for _ in states], None
        self.mp.setattr(mot_3d, 'mot_3d_simulation', force_boundary)

    def coordinator(self, module, name):
        service = getattr(importlib.import_module('workflow_api.' + module), name)(self.local, self.ssh, self.git)
        names = {
            'zeus_discovery_submission': ('mot3dDiscovery', 'Mot3DDiscovery'),
            'mot_3d_discovery_transition': ('mot3dDiscoveryTransition', 'Mot3DDiscoveryTransition'),
            'mot_3d_preliminary_submission': ('mot3dPreliminaryCheck', 'PreliminaryCheck'),
            **{f'mot_3d_{stage}_{kind}': ('mot3d' + title + kind.title(), 'Mot3D' + title + kind.title())
               for stage, title in [('preliminary', 'Preliminary'), ('refinement', 'Refinement'),
                                    ('closure', 'Closure'), ('finalist', 'Finalist'),
                                    ('final_validation', 'FinalValidation')]
               for kind in ('submission', 'transition')
               if (stage, kind) != ('preliminary', 'submission')},
            'mot_3d_final_input_submission': ('mot3dFinalInputSubmission', 'Mot3DFinalInput'),
            'mot_3d_final_validation_completion': ('mot3dFinalValidationCompletion', 'Mot3DFinalValidationCompletion'),
        }
        client, prefix = names[module]
        for method, suffix in [('status', 'Status'), ('preview', 'Preview'), ('confirm', 'Result')]:
            if not hasattr(service, method):
                continue
            original = getattr(service, method)
            def wrapped(*args, _original=original, _method=method, _suffix=suffix, **kwargs):
                result = _original(*args, **kwargs)
                parser_args = []
                if _method == 'preview':
                    if module in {'mot_3d_final_input_submission', 'mot_3d_final_validation_transition', 'mot_3d_final_validation_completion'}:
                        parser_args = [{'campaignId': self.campaign_id, 'commit': self.upstream.commit}]
                    elif module == 'mot_3d_discovery_transition':
                        parser_args = [{'campaignId': self.campaign_id}]
                    elif module.endswith('_transition'):
                        parser_args = [self.campaign_id]
                    else:
                        parser_args = [{'campaignId': self.campaign_id, 'profile': {'host':'zeus.technion.ac.il', 'username':'tal.noa', 'project_directory':self.logical}}]
                elif _method == 'confirm':
                    parser_args = [self.campaign_id]
                row = {'client':client, 'parser':'parse'+prefix+_suffix, 'label':module+'/'+_method,
                       'value':result, 'args':parser_args}
                if module == 'mot_3d_final_validation_completion' and _method == 'confirm':
                    row.update(parser='completionClient', preview=self.completion_preview,
                               args=[self.campaign_id, {'host':'zeus.technion.ac.il', 'username':'tal.noa', 'project_directory':self.logical}, self.upstream.commit])
                if module == 'mot_3d_final_validation_completion' and _method == 'preview':
                    self.completion_preview = result
                self.dto.append(row)
                directory = os.environ.get('UI_3D_PROTOCOL_DTO_DIRECTORY')
                if directory:
                    target = Path(directory); target.mkdir(parents=True, exist_ok=True)
                    (target/'acceptance.json').write_text(json.dumps(self.dto, indent=2)+'\n')
                return result
            setattr(service, method, wrapped)
        return service

    def confirm(self, service):
        if hasattr(service, 'status'):
            service.status(self.request)
        preview = service.preview(self.request, session_id='protocol3d')
        token = {'preview_token': preview['preview_token']}
        result = service.confirm(token, session_id='protocol3d')
        assert service.confirm(token, session_id='protocol3d') == result
        return result


    def work_submitted_jobs(self):
        """Execute the exact rendered Python argv for each submitted PBS task."""
        for job, row in self.upstream.jobs.items():
            if row.get('executed_3d') or self.relative.encode() not in row['data']:
                continue
            text = row['data'].decode()
            match = re.search(r'#PBS -J 0-(\d+)', text)
            spec = row.get('array_spec', '')
            count = int(match[1]) + 1 if match else (int(spec.split(':')[0].split('-')[-1]) + 1 if spec else 1)
            for index in range(count):
                variables = {'PBS_ARRAY_INDEX': str(index), 'worker': str(index), 'seed': str(3035 + index),
                             'zseed': str(3035 + index), 'mseed': str(43035 + index)}
                for name, values in re.findall(r'^(\w+)=\(([^)]*)\)', text, re.M):
                    variables[name] = shlex.split(values)[index]
                variables['seed'] = variables.get('seeds', variables['seed'])
                variables['target'] = variables.get('targets', '')
                variables['sampler'] = variables.get('samplers', '')
                commands = [line for line in text.replace('\\\n', ' ').splitlines() if line.startswith('python ')]
                assert commands, text
                for command in commands:
                    command = re.sub(r'\$\{(\w+)\}|\$(\w+)',
                        lambda match: variables[match[1] or match[2]], command)
                    argv = shlex.split(command)
                    assert '-m' in argv, command
                    offset = argv.index('-m')
                    module, arguments = argv[offset + 1], argv[offset + 2:]
                    with self.mp.context() as child:
                        child.chdir(self.remote)
                        self._realm(child, self.remote)
                        child.setenv('PBS_ARRAY_INDEX', str(index))
                        child.setattr(sys, 'argv', [module, *arguments])
                        # Model the worker process's Zeus mount identity while
                        # every filesystem operation stays in the temporary clone.
                        import pathlib
                        from protocol_path_namespace import worker_path_type
                        worker_path = worker_path_type(self.remote, self.logical)
                        child.setattr(pathlib, 'Path', worker_path)
                        for imported_name, imported in tuple(sys.modules.items()):
                            if imported_name.startswith(('studies.', 'simulations.', 'utils.')) and getattr(imported, 'Path', None) is Path:
                                child.setattr(imported, 'Path', worker_path)
                        original_load = np.load
                        def native_load(file, *args, **kwargs):
                            if isinstance(file, str) and (file == self.logical or file.startswith(self.logical + '/')):
                                file = worker_path(file)
                            return original_load(file, *args, **kwargs)
                        child.setattr(np, 'load', native_load)
                        try:
                            runpy.run_module(module, run_name='__main__')
                        finally:
                            from protocol_path_namespace import restore_worker_path_bindings
                            restore_worker_path_bindings(worker_path)
            row['executed_3d'] = True


@pytest.mark.skipif(os.name == "nt", reason="POSIX receiver and shell scheduler fixture executes on Zeus; native client contracts remain separate")
def test_full_testonly_3d_receiver_protocol_chain(tmp_path, monkeypatch):
    upstream = _completed_upstream(tmp_path, monkeypatch)
    chain = _ThreeD(upstream, monkeypatch)
    discovery = chain.coordinator('zeus_discovery_submission', 'ZeusMot3DDiscoverySubmissionCoordinator')
    chain.confirm(discovery)
    chain.work_submitted_jobs()
    transition = chain.coordinator('mot_3d_discovery_transition', 'Mot3DDiscoveryTransitionCoordinator')
    assert not (chain.campaign / 'discovery_submission.json').exists()
    qsub_count = len(upstream.qsub_calls)
    chain.confirm(transition)
    assert len(upstream.qsub_calls) == qsub_count
    for prefix, submission_name, transition_name in (
        ('preliminary', 'Mot3DPreliminarySubmissionCoordinator', 'Mot3DPreliminaryTransitionCoordinator'),
        ('refinement', 'Mot3DRefinementSubmissionCoordinator', 'Mot3DRefinementTransitionCoordinator'),
        ('closure', 'Mot3DClosureSubmissionCoordinator', 'Mot3DClosureTransitionCoordinator'),
        ('finalist', 'Mot3DFinalistSubmissionCoordinator', 'Mot3DFinalistTransitionCoordinator'),
    ):
        submission = chain.coordinator(f'mot_3d_{prefix}_submission', submission_name)
        if prefix == 'preliminary':
            from copy import deepcopy
            from workflow_api.mot_3d_preliminary_submission import Mot3DPreliminarySubmissionError
            receipt_path = chain.local / chain.relative / '.mot_ui/sync/discovery_to_preliminary.json'
            original_receipt = receipt_path.read_bytes()
            original_jobs = len(upstream.qsub_calls)
            for attack in ('missing', 'extra', 'wrong_hash'):
                changed = deepcopy(json.loads(original_receipt))
                key = next(name for name in changed['files'] if '/trials/' in name)
                if attack == 'missing': changed['files'].pop(key)
                elif attack == 'extra': changed['files']['discovery/unreviewed.json'] = '0' * 64
                else: changed['files'][key] = '0' * 64
                receipt_path.write_text(json.dumps(changed))
                try:
                    with pytest.raises(Mot3DPreliminarySubmissionError, match='preliminary_preparation_invalid'):
                        submission.preview(chain.request, session_id='protocol3d')
                finally:
                    receipt_path.write_bytes(original_receipt)
                assert len(upstream.qsub_calls) == original_jobs
        chain.confirm(submission)
        chain.work_submitted_jobs()
        transition = chain.coordinator(f'mot_3d_{prefix}_transition', transition_name)
        if prefix == 'refinement':
            from workflow_api.mot_3d_refinement_transition_remote import DESCRIPTOR
            receipt = chain.campaign / '.mot_ui/transitions' / (DESCRIPTOR.prior_transition_name + '.json')
            original = receipt.read_bytes()
            before_jobs = len(upstream.qsub_calls)
            discovery_receipt = (receipt.parent / 'preliminary_check.json').read_bytes()
            for attack in ('missing', 'extra', 'wrong_manifest', 'cross_stage', 'duplicate_key', 'registry'):
                changed = json.loads(original)
                if attack == 'missing': changed.pop('identity_sha256')
                elif attack == 'extra': changed['unreviewed'] = True
                elif attack == 'wrong_manifest': changed['new_campaign_sha256'] = '0' * 64
                elif attack == 'registry':
                    name = next(name for name in changed['files'] if name != 'campaign.json')
                    changed['files']['unreviewed/replacement.json'] = changed['files'].pop(name)
                raw = (json.dumps(changed, sort_keys=True, separators=(',', ':')).encode() + b'\n')
                if attack == 'cross_stage': raw = discovery_receipt
                elif attack == 'duplicate_key': raw = raw.replace(b'{', b'{"version":0,', 1)
                receipt.write_bytes(raw)
                try:
                    with pytest.raises(AssertionError, match='refinement_transition_conflict'):
                        transition.status(chain.request)
                finally:
                    receipt.write_bytes(original)
                assert len(upstream.qsub_calls) == before_jobs
        chain.confirm(transition)
    fresh = chain.coordinator('mot_3d_final_input_submission', 'Mot3DFinalInputSubmissionCoordinator')
    chain.confirm(fresh)
    chain.work_submitted_jobs()
    validation = chain.coordinator('mot_3d_final_validation_transition', 'Mot3DFinalValidationTransitionCoordinator')
    chain.confirm(validation)
    final = chain.coordinator('mot_3d_final_validation_submission', 'Mot3DFinalValidationSubmissionCoordinator')
    chain.confirm(final)
    chain.work_submitted_jobs()
    completion = chain.coordinator('mot_3d_final_validation_completion', 'Mot3DFinalValidationCompletionCoordinator')
    chain.confirm(completion)
    # A new coordinator models a reopened client: terminal evidence is recovered
    # solely from the authenticated on-disk protocol, without another mutation.
    before_jobs = len(upstream.qsub_calls)
    before_files = {str(p.relative_to(chain.campaign)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in chain.campaign.rglob('*') if p.is_file()}
    reopened = chain.coordinator('mot_3d_final_validation_completion', 'Mot3DFinalValidationCompletionCoordinator')
    recovered = reopened.status(chain.request)
    assert recovered['completion']['status'] in {'complete', 'final_validation_extension_required'}
    assert recovered['local_sync']['status'] == 'synchronized'
    assert recovered['completion']['detail'] is not None
    assert reopened.status(chain.request) == recovered
    assert len(upstream.qsub_calls) == before_jobs
    assert {str(p.relative_to(chain.campaign)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in chain.campaign.rglob('*') if p.is_file()} == before_files
    from ui_3d_protocol_contract_bridge import assert_3d_contracts
    assert_3d_contracts(chain.dto)
