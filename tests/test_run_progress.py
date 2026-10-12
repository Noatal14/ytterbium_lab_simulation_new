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
