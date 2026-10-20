"""Real planners/workers/publisher/readers; only physical engines are replaced."""
import json

import numpy as np
import pytest

import test_zeeman_local_execution as zeeman
import test_mot_2d_local_execution as mot2d
import test_mot_3d_local_execution as mot3d
from workflow_api.run_execution import IndividualRunExecutionCoordinator, issue_execution_authority
from workflow_api.run_records import RunRecordError, RunRecordStore
from workflow_api.run_results import inspect_run_package
from workflow_api.run_discovery import inspect_run, discover_runs
from workflow_api.mot_2d_individual_sources import list_individual_mot_2d_sources, resolve_individual_mot_2d_source
from workflow_api.mot_3d_individual_sources import list_individual_mot_3d_sources, resolve_individual_mot_3d_source


def _publish(root, monkeypatch, family, retained, zero=False):
    root.mkdir()
    if family == 'zeeman':
        plan = zeeman.plan(retained=retained)
        engine = zeeman.Engine(survivors=np.empty((0, 6)), indices=np.empty(0, dtype=np.int64)) if zero else zeeman.Engine()
        worker = zeeman.ZeemanLocalWorker(engine=engine, monotonic=iter((1., 2.)).__next__, clock=lambda: zeeman.NOW)
    elif family == 'mot_2d':
        plan = mot2d._plan(root, retained=retained)
        engine = mot2d.Engine(0 if zero else 2)
        worker = mot2d.Mot2DLocalWorker(root, engine=engine, monotonic=iter((1., 2.)).__next__, clock=lambda: mot2d.NOW)
    else:
        original = mot3d._plan(root, monkeypatch, retained=retained)
        # Build the immutable plan with seed 1, rather than rewriting its records.
        request = {key: getattr(original.request, key) for key in (
            'source_id', 'geometry_family', 'particle_count', 'selection_seed',
            'parameters', 'npools', 'retain_particle_states', 'execution_mode')}
        request['parameters'] = dict(request['parameters'])
        request['simulation_seed'] = 1
        plan = mot3d.build_mot_3d_run_plan(request, repository_root=root, run_id='mot3d-local-1', git_revision='b'*40, created_utc=mot3d.NOW)
        class Engine(mot3d.Engine):
            def __call__(self, states, **kwargs):
                trajectories, captured = super().__call__(states, **kwargs)
                return trajectories, np.empty((0, 6)) if zero else captured
        engine = Engine()
        def analysis(trajectories, time_points, **kwargs):
            result = mot3d._analysis(trajectories, time_points, **kwargs)
            if zero:
                for value in result.values(): value[:] = False
            return result
        worker = mot3d.Mot3DLocalWorker(root, engine=engine, analyzer=analysis, monotonic=iter((1., 2.)).__next__, clock=lambda: mot3d.NOW)
    records = plan.storage_records()
    store = RunRecordStore(root)
    try: store.create(*(records[key] for key in ('run', 'configuration', 'inputs', 'status')))
    finally: store.close()
    run_id = records['run']['run_id']
    coordinator = IndividualRunExecutionCoordinator(root, worker, issue_execution_authority(), clock=lambda: records['run']['created_utc'])
    assert coordinator.execute(family, run_id)['state'] == 'succeeded'
    assert len(engine.calls) == 1
    return run_id, root / 'data/runs' / family / run_id / 'results/summary.json', engine


def _attacks(family, original):
    count = 'n_initial' if family == 'zeeman' else 'n_input'
    survivor = 'residence_qualified_captured_count' if family == 'mot_3d' else 'n_survivors'
    fraction = {'zeeman': 'survival_fraction', 'mot_2d': 'conditional_efficiency', 'mot_3d': 'residence_qualified_captured_fraction'}[family]
    def changed(**values): return dict(original, **values)
    yield 'immutable-count', changed(**{count: original[count]+1})
    coordinated = changed(**{count: original[count]+1, fraction: original[survivor]/(original[count]+1)})
    if family == 'mot_3d': coordinated['usable_at_end_fraction'] = original['usable_at_end_count'] / (original[count]+1)
    yield 'coordinated-count-fraction', coordinated
    yield 'bool-count', changed(**{survivor: True})
    yield 'out-of-range', changed(**{survivor: original[count]+1})
    yield 'fraction', changed(**{fraction: .123456})
    yield 'bool-fraction', changed(**{fraction: False})
    yield 'bool-elapsed', changed(elapsed_s=True)
    yield 'negative-elapsed', changed(elapsed_s=-1)
    yield 'nonfinite-elapsed', changed(elapsed_s=float('inf'))
    yield 'extra', changed(unreviewed=True)
    missing = dict(original); del missing[survivor]
    yield 'missing', missing
    if family == 'zeeman':
        yield 'bool-captured', changed(captured=bool(original['captured']))
    else:
        yield 'selection', changed(selection_sha256='0'*64)
        for key, value in [('configuration_sha256', '0'*64), ('source_fingerprint', '0'*64)]:
            provenance = dict(original['provenance'], **{key: value})
            yield 'provenance-'+key, changed(provenance=provenance)
        if family == 'mot_3d':
            assert original['provenance']['simulation_seed'] == 1
            for value in (True, 1.0):
                yield 'typed-seed-'+type(value).__name__, changed(provenance=dict(original['provenance'], simulation_seed=value))


@pytest.mark.parametrize('family', ['zeeman', 'mot_2d', 'mot_3d'])
@pytest.mark.parametrize('retained', [True, False])
@pytest.mark.parametrize('zero', [False, True])
def test_actual_worker_results_reject_metric_corruption_on_every_read(tmp_path, monkeypatch, family, retained, zero):
    root = tmp_path / 'repo'
    run_id, summary, engine = _publish(root, monkeypatch, family, retained, zero)
    original_bytes = summary.read_bytes()
    original = json.loads(original_bytes)
    assert inspect_run_package(root, family, run_id).results is not None
    for label, metrics in _attacks(family, original['metrics']):
        corrupted = dict(original, metrics=metrics)
        summary.write_text(json.dumps(corrupted), encoding='utf-8')
        try:
            with pytest.raises(RunRecordError): inspect_run_package(root, family, run_id)
            with pytest.raises(RunRecordError): inspect_run(root, family, run_id)
        finally: summary.write_bytes(original_bytes)
        assert inspect_run_package(root, family, run_id).results is not None, label
    assert len(engine.calls) == 1


@pytest.mark.parametrize('family', ['zeeman', 'mot_2d'])
def test_corrupted_actual_retained_result_cannot_be_readmitted_as_source(tmp_path, monkeypatch, family):
    root = tmp_path / 'repo'
    run_id, summary, _ = _publish(root, monkeypatch, family, True)
    catalog, resolve = ((list_individual_mot_2d_sources, resolve_individual_mot_2d_source) if family == 'zeeman' else
                        (list_individual_mot_3d_sources, resolve_individual_mot_3d_source))
    offered = catalog(root)['sources']
    assert len(offered) == 1
    source_id = offered[0]['id']
    resolve(root, source_id)
    original = summary.read_bytes(); payload = json.loads(original)
    payload['metrics']['n_initial' if family == 'zeeman' else 'n_input'] += 1
    summary.write_text(json.dumps(payload), encoding='utf-8')
    try:
        assert catalog(root)['sources'] == []
        with pytest.raises(ValueError): resolve(root, source_id)
    finally: summary.write_bytes(original)
    assert catalog(root)['sources'][0]['id'] == source_id


@pytest.mark.parametrize('family', ['zeeman', 'mot_2d', 'mot_3d'])
def test_coherent_capture_rewrite_still_must_match_retained_state_array(tmp_path, monkeypatch, family):
    root = tmp_path / 'repo'
    run_id, summary, _ = _publish(root, monkeypatch, family, True)
    original = summary.read_bytes(); payload = json.loads(original)
    metrics = payload['metrics']
    if family == 'zeeman':
        metrics.update(n_survivors=0, captured=0, survival_fraction=0.0)
    elif family == 'mot_2d':
        metrics.update(n_survivors=0, conditional_efficiency=0.0)
    else:
        metrics.update(residence_qualified_captured_count=0, residence_qualified_captured_fraction=0.0)
    summary.write_text(json.dumps(payload), encoding='utf-8')
    try:
        with pytest.raises(RunRecordError): inspect_run_package(root, family, run_id)
        rows = discover_runs(root)
        assert len(rows) == 1 and rows[0].integrity == 'invalid'
    finally: summary.write_bytes(original)
    assert inspect_run(root, family, run_id).integrity == 'complete_verified'


@pytest.mark.parametrize('retained', [True, False])
def test_zeeman_coordinated_run_and_result_count_cannot_override_hashed_configuration(tmp_path, monkeypatch, retained):
    root = tmp_path / 'repo'
    run_id, summary, _ = _publish(root, monkeypatch, 'zeeman', retained)
    run_path = summary.parent.parent / 'run.json'
    original_run, original_summary = run_path.read_bytes(), summary.read_bytes()
    run, results = json.loads(original_run), json.loads(original_summary)
    configuration_path = run_path.with_name('configuration.json')
    original_configuration = configuration_path.read_bytes()
    run['particle_count'] += 1
    results['metrics']['n_initial'] = run['particle_count']
    results['metrics']['survival_fraction'] = results['metrics']['n_survivors'] / run['particle_count']
    run_path.write_text(json.dumps(run), encoding='utf-8')
    summary.write_text(json.dumps(results), encoding='utf-8')
    try:
        with pytest.raises(RunRecordError, match='scientifically inconsistent'):
            inspect_run_package(root, 'zeeman', run_id)
        assert configuration_path.read_bytes() == original_configuration
    finally:
        run_path.write_bytes(original_run); summary.write_bytes(original_summary)
    assert inspect_run(root, 'zeeman', run_id).integrity == 'complete_verified'
