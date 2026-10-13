from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import json
import os

import pytest

from workflow_api.mot_3d_selection_submission import (
    next_action,
    public_lifecycle,
    validate_selection_submission_state,
)
from workflow_api.mot_3d_stage_topology import (
    PRELIMINARY_CHECK_TOPOLOGY,
    REFINEMENT_TOPOLOGY,
    public_chain,
)
from workflow_api import mot_3d_selection_submission_remote as remote_core
from workflow_api import mot_3d_preliminary_submission_remote as preliminary_remote
from workflow_api import mot_3d_refinement_submission_remote as refinement_remote


class ClosedError(RuntimeError):
    pass


@dataclass(frozen=True)
class State:
    lifecycle: str
    branch: str
    jobs: dict
    nonce: str | None
    submitted_unix_s: int | None
    completed_array_tasks: int
    completed_merge_jobs: int


EMPTY = {
    "angled_donut": {"array": None, "merge": None},
    "single_pass": {"array": None, "merge": None},
}
FULL = {
    "angled_donut": {
        "array": "11[].zeus-master",
        "merge": "12.zeus-master",
    },
    "single_pass": {
        "array": "13[].zeus-master",
        "merge": "14.zeus-master",
    },
}


@pytest.mark.parametrize("topology", [PRELIMINARY_CHECK_TOPOLOGY, REFINEMENT_TOPOLOGY])
@pytest.mark.parametrize(
    "state",
    [
        State("eligible", "main", EMPTY, None, None, 0, 0),
        State("submitted", "main", FULL, "a" * 32, 1, 0, 0),
        State("running", "main", FULL, "a" * 32, 1, 2, 0),
        State("completed_success", "main", FULL, "a" * 32, 1, 6, 2),
        State(
            "outcome_unknown",
            "main",
            {
                "angled_donut": {
                    "array": "11[].zeus-master",
                    "merge": None,
                },
                "single_pass": {"array": None, "merge": None},
            },
            "a" * 32,
            None,
            0,
            0,
        ),
    ],
)
def test_both_selection_stages_share_the_exact_lifecycle_matrix(topology, state):
    validate_selection_submission_state(
        state,
        "inspect" if state.lifecycle in {"eligible", "outcome_unknown"} else "status",
        error=ClosedError,
    )
    assert (
        public_chain(state.jobs, topology=topology)["dependency"] == topology.dependency
    )


@pytest.mark.parametrize(
    "state",
    [
        State("partial", "main", EMPTY, "a" * 32, None, 0, 0),
        State("outcome_unknown", "main", FULL, "a" * 32, None, 0, 0),
        State("submitted", "main", FULL, "a" * 32, 1, 1, 0),
        State("completed_success", "main", FULL, "a" * 32, 1, 5, 2),
        State("running", "main", FULL, "a" * 32, 1, 6, 2),
        State("submitted", "main", FULL, "a" * 32, True, 0, 0),
    ],
)
def test_impossible_cross_stage_states_are_rejected(state):
    with pytest.raises(ClosedError, match="remote_response_invalid"):
        validate_selection_submission_state(state, "status", error=ClosedError)


def test_public_lifecycle_and_actions_distinguish_scheduler_success_from_science():
    assert public_lifecycle("completed_success") == "completed_success_unvalidated"
    assert next_action("completed_success") == "await_result_synchronization"
    assert next_action("outcome_unknown") == "inspect_zeus"
    assert next_action("eligible") == "review_submission"


def test_remote_descriptors_are_deeply_immutable_and_exact():
    with pytest.raises(TypeError):
        refinement_remote.DESCRIPTOR.jobs["angled_donut"]["array"] = "changed"
    with pytest.raises(TypeError):
        refinement_remote.DESCRIPTOR.science["selection_seed"] = 1
    with pytest.raises(ValueError):
        remote_core.ReceiverDescriptor(
            stage="refinement",
            input_role="refinement",
            transition_receipt="refinement.json",
            jobs=refinement_remote.JOBS,
            files=refinement_remote.FILES,
            science={**refinement_remote.SCIENCE, "selection_seed": True},
            code_names=refinement_remote.CODE_NAMES,
            transition_status="refinement_prepared",
            outcome_error="refinement_submission_outcome_unknown",
            preparation_error="refinement_preparation_invalid",
        )


def test_concurrent_stage_bindings_do_not_leak_receipt_namespace():
    def render(descriptor):
        with remote_core.descriptor_scope(descriptor):
            return remote_core.compatibility(
                EMPTY, "submitting", "a" * 64, "b" * 32, "c" * 40, 1
            )["stage"]

    descriptors = [
        preliminary_remote.DESCRIPTOR,
        refinement_remote.DESCRIPTOR,
    ] * 50
    with ThreadPoolExecutor(max_workers=8) as pool:
        observed = list(pool.map(render, descriptors))
    assert observed == [descriptor.stage for descriptor in descriptors]


def test_stage_hook_contexts_are_isolated_and_default_publisher_is_real(tmp_path):
    directory = tmp_path / "receipts"
    directory.mkdir()
    descriptor = preliminary_remote.DESCRIPTOR
    fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        with remote_core.descriptor_scope(descriptor):
            remote_core.publish_at(fd, "real.json", {"stage": descriptor.stage})
        assert json.loads((directory / "real.json").read_text()) == {
            "stage": "preliminary_check"
        }
    finally:
        os.close(fd)

    def invoke(descriptor):
        observed = []

        def hook(parent, name, value):
            observed.append((descriptor.stage, name, value))

        with remote_core.descriptor_scope(descriptor):
            token = remote_core._PUBLISHER.set(hook)
            try:
                remote_core.publish_at(-1, f"{descriptor.stage}.json", {"ok": True})
            finally:
                remote_core._PUBLISHER.reset(token)
        return observed

    descriptors = [preliminary_remote.DESCRIPTOR, refinement_remote.DESCRIPTOR] * 40
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(invoke, descriptors))
    assert [row[0][0] for row in rows] == [
        descriptor.stage for descriptor in descriptors
    ]


def test_thin_receiver_wrappers_keep_descriptors_and_hooks_isolated(monkeypatch):
    barrier = __import__("threading").Barrier(2)

    def preliminary_run(*args, **kwargs):
        return "preliminary-run"

    def refinement_run(*args, **kwargs):
        return "refinement-run"

    def preliminary_publish(*args, **kwargs):
        return "preliminary-publish"

    def refinement_publish(*args, **kwargs):
        return "refinement-publish"

    monkeypatch.setattr(preliminary_remote, "run", preliminary_run)
    monkeypatch.setattr(refinement_remote, "run", refinement_run)
    monkeypatch.setattr(preliminary_remote, "publish_at", preliminary_publish)
    monkeypatch.setattr(refinement_remote, "publish_at", refinement_publish)

    def inspect_bound_context(*, trusted_root_override=None):
        barrier.wait(timeout=2)
        descriptor = remote_core._config()
        return (
            descriptor.stage,
            descriptor.transition_status,
            descriptor.outcome_error,
            frozenset(descriptor.files),
            remote_core._RUNNER.get()(),
            remote_core._PUBLISHER.get()(),
        )

    monkeypatch.setattr(remote_core, "main", inspect_bound_context)
    with ThreadPoolExecutor(max_workers=2) as pool:
        preliminary_future = pool.submit(preliminary_remote.main)
        refinement_future = pool.submit(refinement_remote.main)
        preliminary = preliminary_future.result(timeout=3)
        refinement = refinement_future.result(timeout=3)

    assert preliminary == (
        "preliminary_check",
        "preliminary_check_prepared",
        "preliminary_submission_outcome_unknown",
        frozenset(preliminary_remote.FILES),
        "preliminary-run",
        "preliminary-publish",
    )
    assert refinement == (
        "refinement",
        "refinement_prepared",
        "refinement_submission_outcome_unknown",
        frozenset(refinement_remote.FILES),
        "refinement-run",
        "refinement-publish",
    )

    # Contexts are reset after each wrapper returns; neither stage leaks into callers.
    with pytest.raises(LookupError):
        remote_core._config()
    assert remote_core._RUNNER.get() is remote_core._run_impl
    assert remote_core._PUBLISHER.get() is remote_core._publish_at_impl
