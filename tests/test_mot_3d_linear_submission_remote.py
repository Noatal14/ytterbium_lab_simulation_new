import os
import pytest
from workflow_api import mot_3d_linear_submission_remote as linear_core

from workflow_api.mot_3d_linear_submission_remote import (
    FrozenLinearPlan,
    LinearDescriptor,
    LinearStep,
    canonical_prefix,
    qsub_argv,
    scheduler_state,
    execute_chain,
    reconcile_chain,
    with_submission_lock,
    reconcile_operation,
    compatibility,
    recover_prefix,
)
from workflow_api.mot_3d_selection_submission_remote import publish_at
from workflow_api.mot_3d_selection_submission_remote import replace_at


STEPS = (
    LinearStep("zeeman", "jobs/z.pbs", "array", 20, None),
    LinearStep("mot_2d", "jobs/m.pbs", "array", 20, "zeeman"),
    LinearStep("freeze", "jobs/f.pbs", "scalar", 1, "mot_2d"),
)
DESCRIPTOR = LinearDescriptor("stage", "receipt_kind", "error_prefix", STEPS)
PLAN = FrozenLinearPlan(
    "data/optimization/mot_3d/x",
    "a" * 40,
    "b" * 64,
    "c" * 32,
    {name: name.encode() for name in ("zeeman", "mot_2d", "freeze")},
)


def test_exact_topology_and_prefix():
    jobs = {"zeeman": "10[].zeus-master", "mot_2d": "11[].zeus-master", "freeze": None}
    assert canonical_prefix(jobs) == ("10[].zeus-master", "11[].zeus-master")
    assert qsub_argv(STEPS[0], {name: None for name in jobs}) == [
        "/usr/local/bin/qsub",
        "-J",
        "0-19:1",
    ]
    assert qsub_argv(STEPS[1], jobs) == [
        "/usr/local/bin/qsub",
        "-W",
        "depend=afterok:10[].zeus-master",
        "-J",
        "0-19:1",
    ]
    assert qsub_argv(STEPS[2], jobs) == [
        "/usr/local/bin/qsub",
        "-W",
        "depend=afterok:11[].zeus-master",
    ]


@pytest.mark.parametrize(
    "jobs",
    [
        {"zeeman": None, "mot_2d": "11[].zeus-master", "freeze": None},
        {"zeeman": "10[].zeus-master", "mot_2d": "10[].zeus-master", "freeze": None},
        {"zeeman": "10.zeus-master", "mot_2d": None, "freeze": None},
    ],
)
def test_rejects_noncanonical_prefixes(jobs):
    with pytest.raises(ValueError):
        canonical_prefix(jobs)


def _qstat(job, state="F", exit_status="0", count=20):
    prefix = job.split("[]", 1)[0]
    blocks = []
    for index in range(count):
        blocks.append(
            f"Job Id: {prefix}[{index}].zeus-master\n    job_state = {state}\n    Exit_status = {exit_status}\n"
        )
    return "".join(blocks).encode()


def test_qstat_exact_20_20_scalar_and_precedence():
    jobs = {
        "zeeman": "10[].zeus-master",
        "mot_2d": "11[].zeus-master",
        "freeze": "12.zeus-master",
    }
    outputs = {
        jobs["zeeman"]: _qstat(jobs["zeeman"]),
        jobs["mot_2d"]: _qstat(jobs["mot_2d"]),
        jobs[
            "freeze"
        ]: b"Job Id: 12.zeus-master\n    job_state = F\n    Exit_status = 0\n",
    }

    def run(argv, **_):
        return 0, outputs[argv[-1]], b""

    assert scheduler_state(jobs, run=run) == ("completed_success_unvalidated", 40, 1)
    outputs[jobs["mot_2d"]] = _qstat(jobs["mot_2d"], state="H", exit_status="0")
    assert scheduler_state(jobs, run=run)[0] == "held"


def test_qstat_rejects_missing_extra_duplicate_and_junk():
    jobs = {
        "zeeman": "10[].zeus-master",
        "mot_2d": "11[].zeus-master",
        "freeze": "12.zeus-master",
    }
    bad = [
        _qstat(jobs["zeeman"], count=19),
        b"junk\n" + _qstat(jobs["zeeman"]),
        _qstat(jobs["zeeman"])
        + b"Job Id: 999.zeus-master\n    job_state = F\n    Exit_status = 0\n",
    ]
    for raw in bad:

        def run(argv, **_):
            if argv[-1] == jobs["zeeman"]:
                return 0, raw, b""
            if argv[-1] == jobs["freeze"]:
                return (
                    0,
                    b"Job Id: 12.zeus-master\n    job_state = F\n    Exit_status = 0\n",
                    b"",
                )
            return 0, _qstat(jobs["mot_2d"]), b""

        assert scheduler_state(jobs, run=run)[0] == "status_unknown"


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_real_receipts_submit_and_restart_without_resubmit(tmp_path):
    campaign = tmp_path / "campaign"
    submissions = tmp_path / "submissions"
    campaign.mkdir()
    submissions.mkdir()
    cfd, sfd = os.open(campaign, os.O_RDONLY), os.open(submissions, os.O_RDONLY)
    calls = []
    ids = iter((b"10[].zeus-master\n", b"11[].zeus-master\n", b"12.zeus-master\n"))

    def run(argv, **kwargs):
        calls.append((argv, kwargs["input_data"]))
        return 0, next(ids), b""

    try:
        assert (
            execute_chain(
                DESCRIPTOR,
                PLAN,
                submissions_fd=sfd,
                campaign_fd=cfd,
                run=run,
                reattest=lambda: None,
                now=iter(range(10, 30)).__next__,
            )[0]
            == "submitted"
        )
        assert len(calls) == 3
        state, jobs, stamp = reconcile_chain(
            DESCRIPTOR, PLAN, submissions_fd=sfd, campaign_fd=cfd
        )
        assert (
            state == "submitted"
            and len(canonical_prefix(jobs)) == 3
            and stamp is not None
        )
        assert len(calls) == 3
    finally:
        os.close(cfd)
        os.close(sfd)


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_done_before_compat_is_cas_reconciled_without_qsub(tmp_path):
    campaign = tmp_path / "campaign"
    submissions = tmp_path / "submissions"
    campaign.mkdir()
    submissions.mkdir()
    cfd = os.open(campaign, os.O_RDONLY)
    sfd = os.open(submissions, os.O_RDONLY)
    created = 10
    empty = {name: None for name in ("zeeman", "mot_2d", "freeze")}
    from workflow_api.mot_3d_linear_submission_remote import compatibility

    try:
        publish_at(
            sfd,
            "stage.pending.json",
            {
                "version": 1,
                "status": "pending",
                "submission_key": PLAN.submission_key,
                "nonce": PLAN.nonce,
                "commit": PLAN.commit,
                "created_unix_s": created,
            },
        )
        publish_at(
            cfd,
            "stage_submission.json",
            compatibility(DESCRIPTOR, empty, "submitting", PLAN, created),
        )
        publish_at(
            sfd,
            "stage_zeeman.json",
            {
                "status": "submitted",
                "submission_key": PLAN.submission_key,
                "nonce": PLAN.nonce,
                "commit": PLAN.commit,
                "step": "zeeman",
                "pbs_sha256": __import__("hashlib")
                .sha256(PLAN.pbs["zeeman"])
                .hexdigest(),
                "depends_on": None,
                "created_unix_s": 11,
                "job_id": "10[].zeus-master",
                "completed_unix_s": 12,
            },
        )
        state, jobs, _ = reconcile_chain(
            DESCRIPTOR, PLAN, submissions_fd=sfd, campaign_fd=cfd
        )
        assert state == "partial" and jobs["zeeman"] == "10[].zeus-master"
    finally:
        os.close(cfd)
        os.close(sfd)


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_closed_set_and_symlink_fail_closed(tmp_path):
    campaign = tmp_path / "campaign"
    submissions = tmp_path / "submissions"
    campaign.mkdir()
    submissions.mkdir()
    cfd = os.open(campaign, os.O_RDONLY)
    sfd = os.open(submissions, os.O_RDONLY)
    try:
        (submissions / "stage_unexpected.json").write_text("{}")
        with pytest.raises(ValueError, match="unexpected"):
            reconcile_chain(DESCRIPTOR, PLAN, submissions_fd=sfd, campaign_fd=cfd)
        (submissions / "stage_unexpected.json").unlink()
        (submissions / "stage.pending.json").symlink_to(tmp_path / "outside")
        with pytest.raises((ValueError, OSError, SystemExit)):
            reconcile_chain(DESCRIPTOR, PLAN, submissions_fd=sfd, campaign_fd=cfd)
    finally:
        os.close(cfd)
        os.close(sfd)


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_prior_stage_receipts_are_ignored_and_absent_status_is_zero_write(tmp_path):
    campaign = tmp_path / "campaign"
    submissions = tmp_path / "submissions"
    campaign.mkdir()
    submissions.mkdir()
    (submissions / "finalist_selection.json").write_text("{}")
    cfd = os.open(campaign, os.O_RDONLY)
    sfd = os.open(submissions, os.O_RDONLY)
    lock = os.open(submissions / "stage.lock", os.O_RDWR | os.O_CREAT)
    before = {p.name: p.read_bytes() for p in submissions.iterdir()}
    try:
        state = reconcile_operation(
            "status",
            DESCRIPTOR,
            PLAN,
            branch="main",
            lock_fd=lock,
            submissions_fd=sfd,
            campaign_fd=cfd,
            run=lambda *a, **k: pytest.fail("qstat"),
            reattest=lambda: None,
            now=lambda: 10,
        )
        assert state.lifecycle == "eligible"
        assert {p.name: p.read_bytes() for p in submissions.iterdir()} == before
    finally:
        os.close(lock)
        os.close(cfd)
        os.close(sfd)


@pytest.mark.parametrize("stamp", [-1, 253402300800, True])
@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_invalid_global_timestamps_fail_closed(tmp_path, stamp):
    campaign = tmp_path / "campaign"
    submissions = tmp_path / "submissions"
    campaign.mkdir()
    submissions.mkdir()
    cfd = os.open(campaign, os.O_RDONLY)
    sfd = os.open(submissions, os.O_RDONLY)
    try:
        publish_at(
            sfd,
            "stage.pending.json",
            {
                "version": 1,
                "status": "pending",
                "submission_key": PLAN.submission_key,
                "nonce": PLAN.nonce,
                "commit": PLAN.commit,
                "created_unix_s": stamp,
            },
        )
        with pytest.raises(ValueError, match="global intent"):
            reconcile_chain(DESCRIPTOR, PLAN, submissions_fd=sfd, campaign_fd=cfd)
    finally:
        os.close(cfd)
        os.close(sfd)


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_final_before_compat_status_zero_write_submit_reconciles(tmp_path):
    campaign = tmp_path / "campaign"
    submissions = tmp_path / "submissions"
    campaign.mkdir()
    submissions.mkdir()
    cfd = os.open(campaign, os.O_RDONLY)
    sfd = os.open(submissions, os.O_RDONLY)
    ids = iter((b"10[].zeus-master\n", b"11[].zeus-master\n", b"12.zeus-master\n"))
    try:
        execute_chain(
            DESCRIPTOR,
            PLAN,
            submissions_fd=sfd,
            campaign_fd=cfd,
            run=lambda *a, **k: (0, next(ids), b""),
            reattest=lambda: None,
            now=iter(range(10, 30)).__next__,
        )
        jobs = {
            "zeeman": "10[].zeus-master",
            "mot_2d": "11[].zeus-master",
            "freeze": "12.zeus-master",
        }
        replace_at(
            cfd,
            "stage_submission.json",
            compatibility(DESCRIPTOR, jobs, "submitting", PLAN, 10),
            compatibility(DESCRIPTOR, jobs, "submitted", PLAN, 10),
        )
        before = (campaign / "stage_submission.json").read_bytes()
        assert (
            reconcile_chain(
                DESCRIPTOR, PLAN, submissions_fd=sfd, campaign_fd=cfd, mutate=False
            )[0]
            == "outcome_unknown"
        )
        assert (campaign / "stage_submission.json").read_bytes() == before
        assert (
            reconcile_chain(
                DESCRIPTOR, PLAN, submissions_fd=sfd, campaign_fd=cfd, mutate=True
            )[0]
            == "submitted"
        )
    finally:
        os.close(cfd)
        os.close(sfd)


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_full_prefix_without_final_is_manual_unknown(tmp_path):
    campaign = tmp_path / "campaign"
    submissions = tmp_path / "submissions"
    campaign.mkdir()
    submissions.mkdir()
    cfd = os.open(campaign, os.O_RDONLY)
    sfd = os.open(submissions, os.O_RDONLY)
    ids = iter((b"10[].zeus-master\n", b"11[].zeus-master\n", b"12.zeus-master\n"))
    try:
        execute_chain(
            DESCRIPTOR,
            PLAN,
            submissions_fd=sfd,
            campaign_fd=cfd,
            run=lambda *a, **k: (0, next(ids), b""),
            reattest=lambda: None,
            now=iter(range(10, 30)).__next__,
        )
        (submissions / "stage.json").unlink()
        publish_at(
            sfd,
            "stage.pending.json",
            {
                "version": 1,
                "status": "pending",
                "submission_key": PLAN.submission_key,
                "nonce": PLAN.nonce,
                "commit": PLAN.commit,
                "created_unix_s": 10,
            },
        )
        jobs = {
            "zeeman": "10[].zeus-master",
            "mot_2d": "11[].zeus-master",
            "freeze": "12.zeus-master",
        }
        replace_at(
            cfd,
            "stage_submission.json",
            compatibility(DESCRIPTOR, jobs, "submitting", PLAN, 10),
            compatibility(DESCRIPTOR, jobs, "submitted", PLAN, 10),
        )
        assert (
            reconcile_chain(DESCRIPTOR, PLAN, submissions_fd=sfd, campaign_fd=cfd)[0]
            == "outcome_unknown"
        )
    finally:
        os.close(cfd)
        os.close(sfd)


@pytest.mark.parametrize("after_side_effect", [False, True])
@pytest.mark.parametrize("boundary", range(1, 7))
@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_publish_fault_boundaries_never_duplicate_qsub(
    tmp_path, monkeypatch, boundary, after_side_effect
):
    campaign = tmp_path / "campaign"
    submissions = tmp_path / "submissions"
    campaign.mkdir()
    submissions.mkdir()
    cfd = os.open(campaign, os.O_RDONLY)
    sfd = os.open(submissions, os.O_RDONLY)
    real = linear_core.publish_at
    count = 0
    calls = []
    ids = iter((b"10[].zeus-master\n", b"11[].zeus-master\n", b"12.zeus-master\n"))

    def faulty(*args, **kwargs):
        nonlocal count
        count += 1
        if count == boundary and not after_side_effect:
            raise RuntimeError("crash")
        value = real(*args, **kwargs)
        if count == boundary and after_side_effect:
            raise RuntimeError("crash")
        return value

    monkeypatch.setattr(linear_core, "publish_at", faulty)
    try:
        with pytest.raises(RuntimeError, match="crash"):
            execute_chain(
                DESCRIPTOR,
                PLAN,
                submissions_fd=sfd,
                campaign_fd=cfd,
                run=lambda *a, **k: (calls.append(a) or (0, next(ids), b"")),
                reattest=lambda: None,
                now=iter(range(10, 40)).__next__,
            )
        assert len(calls) <= 3
        before = len(calls)
        monkeypatch.setattr(linear_core, "publish_at", real)
        lock = os.open(submissions / "stage.lock", os.O_RDWR | os.O_CREAT)
        retry_ids = iter(
            (b"20[].zeus-master\n", b"21[].zeus-master\n", b"22.zeus-master\n")
        )
        try:
            state = reconcile_operation(
                "submit",
                DESCRIPTOR,
                PLAN,
                branch="main",
                lock_fd=lock,
                submissions_fd=sfd,
                campaign_fd=cfd,
                run=lambda *a, **k: (calls.append(a) or (0, next(retry_ids), b"")),
                reattest=lambda: None,
                now=iter(range(100, 140)).__next__,
            )
        except (ValueError, SystemExit):
            state = None
        finally:
            os.close(lock)
        if before:
            assert len(calls) == before
            assert state is None or state.lifecycle in {
                "partial",
                "outcome_unknown",
                "submitted",
            }
        else:
            # A crash before any qsub is the sole safely retryable case.
            assert len(calls) in {0, 3}
    finally:
        os.close(cfd)
        os.close(sfd)


@pytest.mark.parametrize("primitive,total", [("replace_at", 4), ("unlink_at", 4)])
@pytest.mark.parametrize("after_side_effect", [False, True])
@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_cas_and_cleanup_faults_restart_without_duplicate_qsub(
    tmp_path, monkeypatch, primitive, total, after_side_effect
):
    for boundary in range(1, total + 1):
        campaign = tmp_path / f"campaign-{primitive}-{after_side_effect}-{boundary}"
        submissions = (
            tmp_path / f"submissions-{primitive}-{after_side_effect}-{boundary}"
        )
        campaign.mkdir()
        submissions.mkdir()
        cfd = os.open(campaign, os.O_RDONLY)
        sfd = os.open(submissions, os.O_RDONLY)
        real = getattr(linear_core, primitive)
        count = 0
        qsubs = []
        ids = iter((b"10[].zeus-master\n", b"11[].zeus-master\n", b"12.zeus-master\n"))

        def faulty(*args, **kwargs):
            nonlocal count
            count += 1
            if count == boundary and not after_side_effect:
                raise RuntimeError("crash")
            value = real(*args, **kwargs)
            if count == boundary and after_side_effect:
                raise RuntimeError("crash")
            return value

        monkeypatch.setattr(linear_core, primitive, faulty)
        try:
            with pytest.raises(RuntimeError, match="crash"):
                execute_chain(
                    DESCRIPTOR,
                    PLAN,
                    submissions_fd=sfd,
                    campaign_fd=cfd,
                    run=lambda *a, **k: (qsubs.append(a) or (0, next(ids), b"")),
                    reattest=lambda: None,
                    now=iter(range(10, 50)).__next__,
                )
            submitted_before_restart = len(qsubs)
            monkeypatch.setattr(linear_core, primitive, real)
            lock = os.open(submissions / "stage.lock", os.O_RDWR | os.O_CREAT)
            try:
                state = reconcile_operation(
                    "submit",
                    DESCRIPTOR,
                    PLAN,
                    branch="main",
                    lock_fd=lock,
                    submissions_fd=sfd,
                    campaign_fd=cfd,
                    run=lambda *a, **k: pytest.fail("duplicate qsub"),
                    reattest=lambda: None,
                    now=lambda: 100,
                )
            except (ValueError, SystemExit):
                state = None
            finally:
                os.close(lock)
            assert len(qsubs) == submitted_before_restart <= 3
            assert state is None or state.lifecycle in {
                "partial",
                "outcome_unknown",
                "submitted",
            }
        finally:
            monkeypatch.setattr(linear_core, primitive, real)
            os.close(cfd)
            os.close(sfd)


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_lock_rejects_concurrent_operation(tmp_path):
    lock = tmp_path / "lock"
    lock.touch()
    first = os.open(lock, os.O_RDWR)
    second = os.open(lock, os.O_RDWR)
    entered = []
    try:
        fcntl = __import__("fcntl")
        fcntl.flock(first, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="busy"):
            with_submission_lock(second, lambda: entered.append(True))
        assert not entered
    finally:
        os.close(first)
        os.close(second)


@pytest.mark.parametrize("reattest_boundary", [1, 2, 3, 4])
@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX receiver integration requires directory descriptors and Unix process primitives")
def test_reattest_failure_stops_before_any_later_qsub(tmp_path, reattest_boundary):
    campaign = tmp_path / "campaign"
    submissions = tmp_path / "submissions"
    campaign.mkdir()
    submissions.mkdir()
    cfd = os.open(campaign, os.O_RDONLY)
    sfd = os.open(submissions, os.O_RDONLY)
    calls = []
    checks = 0

    def reattest():
        nonlocal checks
        checks += 1
        if checks == reattest_boundary:
            raise RuntimeError("ABA mutation")

    ids = iter((b"10[].zeus-master\n", b"11[].zeus-master\n", b"12.zeus-master\n"))
    try:
        with pytest.raises(RuntimeError, match="ABA"):
            execute_chain(
                DESCRIPTOR,
                PLAN,
                submissions_fd=sfd,
                campaign_fd=cfd,
                run=lambda *a, **k: (calls.append(a) or (0, next(ids), b"")),
                reattest=reattest,
                now=lambda: 10,
            )
        assert len(calls) == reattest_boundary - 1
        jobs, _ = recover_prefix(DESCRIPTOR, PLAN, submissions_fd=sfd)
        assert len(canonical_prefix(jobs)) == reattest_boundary - 1
    finally:
        os.close(cfd)
        os.close(sfd)
