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
        assert not registry.is_scheduled('zeeman','zeeman-run-001')
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


@pytest.mark.parametrize('cancel_second', [False, True])
def test_queued_local_observation_survives_registry_reload_without_durable_queue_state(tmp_path, cancel_second):
    import test_zeeman_local_execution as zeeman
    from workflow_api.individual_run_discovery import CanonicalIndividualRunRegistry
    root = fixture.make_run(tmp_path)
    entered, release = threading.Event(), threading.Event()
    progress = IndividualRunProgressRegistry()
    class Worker(zeeman.ZeemanLocalWorker):
        def run(self, request):
            if request.run['run_id'] == 'zeeman-run-001':
                entered.set()
                assert release.wait(timeout=5)
            return super().run(request)
    pool = BoundedLocalExecutionPool(root, issue_execution_authority(), max_concurrent=1, max_pending=2,
        worker_factory=lambda: Worker(engine=zeeman.Engine(), monotonic=iter((1.,2.)).__next__, clock=lambda:fixture.NOW),
        coordinator_factory=lambda *args, **kwargs: IndividualRunExecutionCoordinator(*args, clock=lambda:fixture.NOW, **kwargs),
        progress_registry=progress)
    try:
        first = pool.submit('zeeman', 'zeeman-run-001')
        assert entered.wait(timeout=5)
        records = build_zeeman_run_plan(fixture.REQUEST, run_id='second-queued', git_revision='a'*40, created_utc=fixture.NOW).storage_records()
        store = RunRecordStore(root)
        try: directory = store.create(*(records[key] for key in ('run','configuration','inputs','status')))
        finally: store.close()
        before = (directory / 'status.json').read_bytes()
        second = pool.submit('zeeman', 'second-queued')
        for registry in (CanonicalIndividualRunRegistry(root, progress_registry=progress),
                         CanonicalIndividualRunRegistry(root, progress_registry=progress)):
            row = next(row for row in registry.list_runs()['runs'] if row['display_name']=='second-queued')
            assert row['record_state'] == row['lifecycle'] == 'configured'
            assert row['execution']['locally_scheduled'] is True
            assert row['next_action'] == 'wait'
            assert registry.get_run(row['id'])['execution']['locally_scheduled'] is True
        assert (directory / 'status.json').read_bytes() == before
        restarted = CanonicalIndividualRunRegistry(root, progress_registry=IndividualRunProgressRegistry())
        row = next(row for row in restarted.list_runs()['runs'] if row['display_name']=='second-queued')
        assert row['execution']['locally_scheduled'] is False and row['next_action']=='none'
        with pytest.raises(RuntimeError, match='scheduled'): pool.submit('zeeman','second-queued')
        if cancel_second:
            assert pool.cancel_queued('zeeman','second-queued',updated_utc=fixture.NOW)
            assert not progress.is_scheduled('zeeman','second-queued')
            assert second.future.cancelled()
        release.set()
        assert first.future.result(timeout=5)['state']=='succeeded'
        if not cancel_second:
            assert second.future.result(timeout=5)['state']=='succeeded'
        pool.close()
        assert not progress.is_scheduled('zeeman','zeeman-run-001')
        assert not progress.is_scheduled('zeeman','second-queued')
    finally:
        release.set(); pool.close()


def test_local_enqueue_failure_rolls_back_observation_and_capacity(tmp_path, monkeypatch):
    root = fixture.make_run(tmp_path); progress=IndividualRunProgressRegistry()
    pool=BoundedLocalExecutionPool(root,issue_execution_authority(),progress_registry=progress)
    def reject(*args, **kwargs):
        assert progress.is_scheduled('zeeman','zeeman-run-001')
        raise RuntimeError('executor rejected enqueue')
    monkeypatch.setattr(pool._executor,'submit',reject)
    try:
        with pytest.raises(RuntimeError,match='rejected'): pool.submit('zeeman','zeeman-run-001')
        assert not progress.is_scheduled('zeeman','zeeman-run-001')
        assert inspect_run(root,'zeeman','zeeman-run-001').state=='configured'
        assert pool._slots.acquire(blocking=False)
        pool._slots.release()
    finally: pool.close()


def test_immediately_completed_future_clears_queue_mark_after_handle_registration(tmp_path, monkeypatch):
    from concurrent.futures import Future
    root=fixture.make_run(tmp_path);progress=IndividualRunProgressRegistry()
    pool=BoundedLocalExecutionPool(root,issue_execution_authority(),progress_registry=progress)
    def immediate(*args, **kwargs):
        assert progress.is_scheduled('zeeman','zeeman-run-001')
        future=Future();future.set_result({'state':'succeeded'})
        return future
    monkeypatch.setattr(pool._executor,'submit',immediate)
    try:
        handle=pool.submit('zeeman','zeeman-run-001')
        assert handle.future.done()
        assert not progress.is_scheduled('zeeman','zeeman-run-001')
        assert ('zeeman','zeeman-run-001') not in pool._handles
    finally:pool.close()


def test_stale_completed_callback_cannot_clear_new_future_observation_or_release_its_slot(tmp_path, monkeypatch):
    from concurrent.futures import Future
    root=fixture.make_run(tmp_path);progress=IndividualRunProgressRegistry()
    pool=BoundedLocalExecutionPool(root,issue_execution_authority(),max_pending=1,progress_registry=progress)
    futures=[]
    def pending(*args, **kwargs):
        future=Future();futures.append(future);return future
    monkeypatch.setattr(pool._executor,'submit',pending)
    try:
        first=pool.submit('zeeman','zeeman-run-001')
        first.future.set_result({'state':'succeeded'})
        second=pool.submit('zeeman','zeeman-run-001')
        pool._release(('zeeman','zeeman-run-001'),first.future)
        assert progress.is_scheduled('zeeman','zeeman-run-001')
        assert pool._handles[('zeeman','zeeman-run-001')].future is second.future
        assert not pool._slots.acquire(blocking=False)
        second.future.set_result({'state':'succeeded'})
        assert not progress.is_scheduled('zeeman','zeeman-run-001')
    finally:pool.close()


def test_done_future_with_delayed_callback_cannot_be_overwritten_without_observer(tmp_path, monkeypatch):
    from concurrent.futures import Future
    root=fixture.make_run(tmp_path)
    class DelayedFuture(Future):
        def __init__(self): super().__init__();self.callbacks=[]
        def add_done_callback(self, callback): self.callbacks.append(callback)
        def deliver(self):
            for callback in self.callbacks: callback(self)
    pool=BoundedLocalExecutionPool(root,issue_execution_authority(),max_pending=1)
    futures=[]
    def enqueue(*args, **kwargs):
        future=DelayedFuture();futures.append(future);return future
    monkeypatch.setattr(pool._executor,'submit',enqueue)
    try:
        first=pool.submit('zeeman','zeeman-run-001');first.future.set_result({'state':'succeeded'})
        with pytest.raises(RuntimeError,match='scheduled'):pool.submit('zeeman','zeeman-run-001')
        assert len(futures)==1 and not pool._slots.acquire(blocking=False)
        first.future.deliver()
        second=pool.submit('zeeman','zeeman-run-001')
        first.future.deliver()
        assert not pool._slots.acquire(blocking=False)
        second.future.set_result({'state':'succeeded'});second.future.deliver()
        assert pool._slots.acquire(blocking=False);pool._slots.release()
    finally:pool.close()
