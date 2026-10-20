"""Long-worker lease renewal and background errors, without physical simulation."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_run_execution as fixture
from workflow_api.run_execution import ExecutorLifecycleStore, IndividualRunExecutionCoordinator, issue_execution_authority
from workflow_api.run_records import RunRecordStore, RunRecordError
from workflow_api.zeeman_run_plan import build_zeeman_run_plan
from workflow_api.zeeman_local_execution import BoundedLocalExecutionPool
from workflow_api.run_discovery import inspect_run
from workflow_api.run_progress import IndividualRunProgressRegistry


@pytest.mark.parametrize('retained', [True, False])
def test_canonical_sibling_creation_during_paused_worker_does_not_orphan_publication(tmp_path, retained):
    root = fixture.make_run(tmp_path, retained=retained)
    entered, release = threading.Event(), threading.Event()
    class Worker(fixture.FakeWorker):
        def run(self, request):
            entered.set()
            assert release.wait(timeout=5)
            return super().run(request)
    worker = Worker(fixture.retained_product() if retained else fixture.discarded_product())
    coordinator = IndividualRunExecutionCoordinator(root, worker, issue_execution_authority(), clock=lambda: fixture.NOW)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(coordinator.execute, 'zeeman', 'zeeman-run-001')
        try:
            assert entered.wait(timeout=5)
            records = build_zeeman_run_plan(fixture.REQUEST, run_id='new-sibling', git_revision='a'*40, created_utc=fixture.NOW).storage_records()
            store = RunRecordStore(root)
            try: store.create(*(records[key] for key in ('run', 'configuration', 'inputs', 'status')))
            finally: store.close()
        finally: release.set()
        assert future.result(timeout=5)['state'] == 'succeeded'
    assert worker.calls == 1
    assert inspect_run(root, 'zeeman', 'zeeman-run-001').integrity == 'complete_verified'
    assert inspect_run(root, 'zeeman', 'new-sibling').state == 'configured'


def test_publication_error_marks_original_revision_unknown_without_replaying_worker(tmp_path, monkeypatch):
    root = fixture.make_run(tmp_path)
    def fail(*args, **kwargs): raise OSError('injected storage failure')
    monkeypatch.setattr(ExecutorLifecycleStore, 'publish_worker_artifacts', fail)
    worker = fixture.FakeWorker(fixture.discarded_product())
    coordinator = IndividualRunExecutionCoordinator(root, worker, issue_execution_authority(), clock=lambda: fixture.NOW)
    assert coordinator.execute('zeeman', 'zeeman-run-001')['state'] == 'outcome_unknown'
    inspected = inspect_run(root, 'zeeman', 'zeeman-run-001')
    assert inspected.status['error']['code'] == 'publication_outcome_unknown'
    assert inspected.results is None
    assert coordinator.execute('zeeman', 'zeeman-run-001') == {'state':'outcome_unknown','recovered':True,'worker_started':False}
    assert worker.calls == 1


def test_unexpected_background_error_remains_observable_and_cannot_be_silently_resubmitted(tmp_path):
    root = fixture.make_run(tmp_path)
    class Coordinator:
        def __init__(self, *args, **kwargs): pass
        def execute(self, *args): raise RunRecordError('untrusted namespace')
    registry = IndividualRunProgressRegistry()
    registry.start('zeeman', 'zeeman-run-001', 100)
    pool = BoundedLocalExecutionPool(root, issue_execution_authority(), coordinator_factory=Coordinator, max_pending=2, progress_registry=registry)
    try:
        handle = pool.submit('zeeman', 'zeeman-run-001')
        with pytest.raises(RunRecordError): handle.future.result(timeout=5)
        completed = threading.Event()
        handle.future.add_done_callback(lambda _: completed.set())
        assert completed.wait(timeout=5)
        assert registry.snapshot('zeeman', 'zeeman-run-001') is None
        assert registry.failure('zeeman', 'zeeman-run-001') == 'background_execution_failed'
        assert pool.failure('zeeman','zeeman-run-001') == 'RunRecordError'
        with pytest.raises(RuntimeError, match='recovery'): pool.submit('zeeman','zeeman-run-001')
        assert len(pool._failures) <= pool._failure_limit
    finally: pool.close()


@pytest.mark.parametrize('outcome,expected', [('failed','failed'), ('exception','outcome_unknown'), ('invalid','failed')])
def test_sibling_creation_during_worker_also_renews_failure_classification(tmp_path, outcome, expected):
    root = fixture.make_run(tmp_path)
    class Worker:
        def run(self, request):
            (root / 'data/runs/zeeman/new-sibling').mkdir()
            if outcome == 'failed': raise fixture.WorkerFailed()
            if outcome == 'exception': raise RuntimeError('physical worker error')
            return object()
    coordinator = IndividualRunExecutionCoordinator(root, Worker(), issue_execution_authority(), clock=lambda: fixture.NOW)
    assert coordinator.execute('zeeman', 'zeeman-run-001')['state'] == expected
    assert inspect_run(root, 'zeeman', 'zeeman-run-001').results is None


def test_real_mot2d_materialized_inputs_survive_restored_ancestor_namespace_without_foreign_writes(tmp_path):
    import shutil
    import numpy as np
    import test_mot_2d_local_execution as mot2d
    root = tmp_path / 'repo'; root.mkdir()
    plan = mot2d._plan(root, retained=True)
    records = plan.storage_records()
    store = RunRecordStore(root)
    try: store.create(*(records[key] for key in ('run', 'configuration', 'inputs', 'status')))
    finally: store.close()
    sampling = records['configuration']['resolved']['sampling']
    source = records['configuration']['resolved']['input_source']['records']
    expected = np.stack([np.load(root / source[index]['path'], allow_pickle=False)[row]
                         for index, row in sampling['selected_identities']])
    foreign = tmp_path / 'foreign-copy'
    class Engine(mot2d.Engine):
        def __call__(self, states, **kwargs):
            assert not isinstance(states, np.memmap)
            assert states.flags.owndata
            np.testing.assert_array_equal(states, expected)
            shutil.copytree(root, foreign)
            fixture.aba_restore(root)
            # The materialized selection is independent of foreign pathname data.
            foreign_source = foreign / source[0]['path']
            foreign_values = np.load(foreign_source, allow_pickle=False)
            foreign_values[:] = -999
            np.save(foreign_source, foreign_values, allow_pickle=False)
            np.testing.assert_array_equal(states, expected)
            return super().__call__(states, **kwargs)
    engine = Engine(2)
    worker = mot2d.Mot2DLocalWorker(root, engine=engine, monotonic=iter((1., 2.)).__next__, clock=lambda: mot2d.NOW)
    coordinator = IndividualRunExecutionCoordinator(root, worker, issue_execution_authority(), clock=lambda: mot2d.NOW)
    assert coordinator.execute('mot_2d', 'mot2d-local-1')['state'] == 'succeeded'
    assert len(engine.calls) == 1
    np.testing.assert_array_equal(np.load(root / 'data/runs/mot_2d/mot2d-local-1/results/states.npy'), expected[:2])
    assert inspect_run(root, 'mot_2d', 'mot2d-local-1').integrity == 'complete_verified'
    foreign_run = inspect_run(foreign, 'mot_2d', 'mot2d-local-1')
    assert foreign_run.state == 'running' and foreign_run.results is None
