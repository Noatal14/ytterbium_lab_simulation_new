import pytest

from workflow_api.run_progress import IndividualRunProgressRegistry


def test_progress_registry_reports_particles_fraction_and_runtime():
    ticks = iter([10.0, 12.5])
    registry = IndividualRunProgressRegistry(monotonic=lambda: next(ticks))
    registry.start("mot_2d", "run-one", 20)
    registry.update("mot_2d", "run-one", 7, 20)

    assert registry.snapshot("mot_2d", "run-one") == {
        "completed_particles": 7,
        "total_particles": 20,
        "fraction": 0.35,
        "runtime_s": 2.5,
    }


def test_progress_registry_rejects_regression_or_changed_total():
    registry = IndividualRunProgressRegistry(monotonic=lambda: 1.0)
    registry.start("zeeman", "run-one", 10)
    registry.update("zeeman", "run-one", 4, 10)
    with pytest.raises(ValueError):
        registry.update("zeeman", "run-one", 3, 10)
    with pytest.raises(ValueError):
        registry.update("zeeman", "run-one", 4, 11)


def test_failed_background_progress_is_not_stale_live_activity_and_diagnostics_are_bounded():
    registry = IndividualRunProgressRegistry()
    registry._failure_limit = 2
    registry.start("mot_2d", "first", 20)
    registry.update("mot_2d", "first", 20, 20)
    registry.fail("mot_2d", "first", "background_execution_failed")
    assert registry.snapshot("mot_2d", "first") is None
    assert registry.failure("mot_2d", "first") == "background_execution_failed"
    registry.fail("mot_2d", "second", "background_execution_failed")
    registry.fail("mot_2d", "third", "background_execution_failed")
    assert len(registry._failures) == 2
    assert registry.failure("mot_2d", "first") is None
    registry.start("mot_2d", "third", 20)
    assert registry.failure("mot_2d", "third") is None


def test_queue_observation_is_independent_of_progress_and_cleared_explicitly():
    registry=IndividualRunProgressRegistry()
    assert not registry.is_scheduled('zeeman','queued')
    registry.schedule('zeeman','queued')
    assert registry.snapshot('zeeman','queued') is None
    registry.start('zeeman','queued',10)
    assert registry.is_scheduled('zeeman','queued')
    with pytest.raises(ValueError): registry.schedule('zeeman','queued')
    registry.finish('zeeman','queued')
    registry.finish('zeeman','queued')
    assert not registry.is_scheduled('zeeman','queued')


def test_failed_observation_clears_process_queue_ownership():
    registry=IndividualRunProgressRegistry();registry.schedule('zeeman','failed')
    registry.fail('zeeman','failed','background_execution_failed')
    assert not registry.is_scheduled('zeeman','failed')
    assert registry.failure('zeeman','failed')=='background_execution_failed'
