"""Pinned receiver for the canonical four-job 3D refinement-check chain."""

from __future__ import annotations

from lab_setup.mot_3d_timestep_policy import MOT_3D_TIMESTEP_POLICY

import base64, hashlib, json, os, re, stat, subprocess, sys, tempfile, time

try:
    import fcntl
except ImportError:
    from workflow_api.platform_io import locking as fcntl
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping

FAMILIES = ("angled_donut", "single_pass")


@dataclass(frozen=True)
class ReceiverDescriptor:
    stage: str
    input_role: str | tuple[str, ...] | None
    transition_receipt: str
    jobs: Mapping[str, Mapping[str, str]]
    files: frozenset[str]
    science: Mapping[str, object]
    code_names: frozenset[str]
    transition_status: str
    outcome_error: str
    preparation_error: str
    non_job_files: frozenset[str] | None = None
    science_keys: frozenset[str] | None = None
    dt_design_key: str = "screening_dt_s"

    def __post_init__(self):
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.stage) is None:
            raise ValueError("invalid receiver stage")
        if self.input_role is None:
            pass
        elif isinstance(self.input_role, str):
            if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.input_role) is None:
                raise ValueError("invalid receiver input role")
        elif (
            type(self.input_role) is not tuple
            or not self.input_role
            or any(
                not isinstance(role, str)
                or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", role) is None
                for role in self.input_role
            )
        ):
            raise ValueError("invalid receiver input roles")
        expected_transition_receipts = {
            "preliminary_check": "preliminary_check.json",
            "refinement": "refinement.json",
            "closure": "refinement_to_closure.json",
            "finalist_selection": "closure_to_finalist_selection.json",
            "final_validation": "final_validation_inputs_to_final_validation.json",
        }
        if self.transition_receipt != expected_transition_receipts.get(self.stage):
            raise ValueError("invalid receiver transition receipt")
        if set(self.jobs) != set(FAMILIES):
            raise ValueError("invalid receiver jobs")
        jobs = {}
        for family in FAMILIES:
            row = self.jobs[family]
            if not isinstance(row, Mapping) or set(row) != {"array", "merge"}:
                raise ValueError("invalid receiver jobs")
            expected = {
                "array": f"jobs/{self.stage}/{family}_array.pbs",
                "merge": f"jobs/{self.stage}/{family}_merge.pbs",
            }
            if dict(row) != expected:
                raise ValueError("invalid receiver jobs")
            jobs[family] = MappingProxyType(expected)
        non_job_files = self.non_job_files
        if non_job_files is None:
            non_job_files = frozenset(
                {
                    "campaign.json",
                    *(
                        f"selection/{'discovery' if self.stage == 'preliminary_check' else 'finalists' if self.stage == 'finalist_selection' else self.stage}/{family}.json"
                        for family in FAMILIES
                    ),
                }
            )
        if type(non_job_files) is not frozenset:
            raise ValueError("invalid receiver non-job files")
        expected_files = non_job_files | frozenset(
            path for family in FAMILIES for path in jobs[family].values()
        )
        if type(self.files) is not frozenset or self.files != expected_files:
            raise ValueError("invalid receiver files")
        standard_science_keys = {
            "classification",
            "candidates_per_family",
            "input_ensembles",
            "particles_per_ensemble",
            "total_particles",
            "recoil_seeds",
            "dt_s",
            "t_max_s",
            "solver",
            "selection_seed",
            "bootstrap_replicates",
            "bootstrap_seed",
        }
        finalist_science_keys = {
            "classification",
            "candidates_per_family",
            "input_ensembles",
            "recoil_seeds",
            "dt_s",
            "t_max_s",
            "solver",
            "npools",
            "bootstrap_replicates",
            "bootstrap_seed",
        }
        expected_science_keys = self.science_keys or (
            finalist_science_keys
            if self.stage == "finalist_selection"
            else standard_science_keys
        )
        if (
            not isinstance(self.science, Mapping)
            or set(self.science) != expected_science_keys
        ):
            raise ValueError("invalid receiver science")
        science = dict(self.science)
        if science["dt_s"] is not None or science["solver"] is not None:
            raise ValueError("runtime science must be manifest-derived")
        if self.stage in {"finalist_selection", "final_validation"}:
            numeric_names = (
                "candidates_per_family",
                "input_ensembles",
                "npools",
                "bootstrap_replicates",
                "bootstrap_seed",
            )
            expected_classification = {
                "finalist_selection": "final_candidate_selection_not_unbiased_validation",
                "final_validation": "sealed_unbiased_final_validation",
            }[self.stage]
        else:
            numeric_names = (
                "candidates_per_family",
                "input_ensembles",
                "particles_per_ensemble",
                "total_particles",
                "selection_seed",
                "bootstrap_replicates",
                "bootstrap_seed",
            )
            expected_classification = "candidate_selection_not_final_validation"
        if (
            science["classification"] != expected_classification
            or any(
                type(science[name]) is not int or science[name] <= 0
                for name in numeric_names
            )
            or type(science["t_max_s"]) not in {int, float}
            or science["t_max_s"] != MOT_3D_TIMESTEP_POLICY["t_max_s"]
            or not isinstance(science["recoil_seeds"], (list, tuple))
            or any(
                type(seed) is not int or seed < 0 for seed in science["recoil_seeds"]
            )
        ):
            raise ValueError("invalid receiver science")
        expected_dt_key = (
            "production_dt_s"
            if science["classification"] == "sealed_unbiased_final_validation"
            else "screening_dt_s"
        )
        if self.dt_design_key != expected_dt_key:
            raise ValueError("invalid receiver timestep authority")
        if science["classification"] == "sealed_unbiased_final_validation" and (
            science["candidates_per_family"] != 1
            or science["input_ensembles"] != 20
            or tuple(science["recoil_seeds"]) != (44001, 44002, 44003)
            or science["npools"] != 200
            or science["bootstrap_replicates"] != 20_000
            or science["bootstrap_seed"] != 92_001
        ):
            raise ValueError("invalid final-validation science")
        science["recoil_seeds"] = tuple(science["recoil_seeds"])
        if type(self.code_names) is not frozenset or not self.code_names:
            raise ValueError("invalid receiver code ledger")
        if any(
            type(value) is not str
            or PurePosixPath(value).is_absolute()
            or any(part in {"", ".", ".."} for part in PurePosixPath(value).parts)
            for value in self.code_names
        ):
            raise ValueError("invalid receiver code ledger")
        if self.transition_status != f"{self.stage}_prepared":
            raise ValueError("invalid transition status")
        if (
            self.outcome_error
            != f"{self.stage.removesuffix('_check')}_submission_outcome_unknown"
        ):
            raise ValueError("invalid outcome error")
        if (
            self.preparation_error
            != f"{self.stage.removesuffix('_check')}_preparation_invalid"
        ):
            raise ValueError("invalid preparation error")
        object.__setattr__(self, "jobs", MappingProxyType(jobs))
        object.__setattr__(self, "science", MappingProxyType(science))


_CURRENT: ContextVar[ReceiverDescriptor] = ContextVar("selection_submission_receiver")


def _config() -> ReceiverDescriptor:
    return _CURRENT.get()


def _outcome_error() -> str:
    try:
        return _config().outcome_error
    except LookupError:
        # Neutral low-level descriptor helpers are also consumed by the
        # preliminary-transition receiver outside a submission session.
        return "preliminary_submission_outcome_unknown"


@contextmanager
def descriptor_scope(descriptor: ReceiverDescriptor):
    if type(descriptor) is not ReceiverDescriptor:
        raise TypeError("invalid receiver descriptor")
    token = _CURRENT.set(descriptor)
    try:
        yield
    finally:
        _CURRENT.reset(token)


HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ARRAY = re.compile(r"^\d+\[\]\.zeus-master$")
SCALAR = re.compile(r"^\d+\.zeus-master$")
DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


def fail(code, status=20):
    print(json.dumps({"error": code}))
    raise SystemExit(status)


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def stamp(value):
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 253402300799
    )


def exact_match(pattern, value):
    return type(value) is str and pattern.fullmatch(value) is not None


def open_dir_at(parent, name, create=False):
    if not isinstance(name, str) or name in {"", ".", ".."} or "/" in name:
        fail(_outcome_error())
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
        except OSError:
            fail(_outcome_error())
    try:
        fd = os.open(name, DIR_FLAGS, dir_fd=parent)
        row = os.fstat(fd)
    except OSError:
        fail(_outcome_error())
    if not stat.S_ISDIR(row.st_mode) or row.st_nlink < 1:
        os.close(fd)
        fail(_outcome_error())
    return fd


def _authenticated_predecessor_names(campaign_fd, submissions_fd, names, transition, commit):
    """Recognize only the completed, attested linear predecessor ledger."""
    if _config().stage != "final_validation":
        return set()
    stage = "final_validation_input_generation"
    known = {stage + ".json", stage + ".lock", *(stage + "_" + step + ".json" for step in ("zeeman", "mot_2d", "freeze"))}
    present = set(names) & known
    if not present:
        return set()
    required = known - {stage + ".lock"}
    if not required <= present or not exact_match(HEX64, transition.get("submission_key")):
        fail(_outcome_error())
    compat_name = "final_validation_input_generation_submission.json"
    if (not isinstance(transition.get("files"), dict)
            or hashlib.sha256(read_relative_at(campaign_fd, compat_name)).hexdigest()
            != transition["files"].get(compat_name)):
        fail(_outcome_error())
    for name in present:
        if not regular_exists_at(submissions_fd, name):
            fail(_outcome_error())
    # Pending/unknown similarly prefixed files remain outside this exact set and
    # are rejected by the caller's ordinary orphan-ledger guard.
    from workflow_api import mot_3d_preliminary_transition_remote as proof
    from workflow_api.mot_3d_final_validation_transition_remote import DESCRIPTOR
    from contextlib import redirect_stdout
    import io
    lock_fd = -1
    try:
        if stage + ".lock" in present:
            lock_fd = os.open(stage + ".lock", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=submissions_fd)
            row = os.fstat(lock_fd)
            if not stat.S_ISREG(row.st_mode) or row.st_nlink != 1:
                raise ValueError("Unsafe predecessor lock")
            fcntl.flock(lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        # The proof checks exact global+three step schemas, nonce/key/commit,
        # PBS hashes, dependencies, causal timestamps and compatibility ledger.
        with proof.descriptor_scope(DESCRIPTOR), redirect_stdout(io.StringIO()):
            proof._exact_linear_submission(campaign_fd, transition["submission_key"], commit)
    except (OSError, ValueError, SystemExit):
        fail(_outcome_error())
    finally:
        if lock_fd >= 0:
            os.close(lock_fd)
    return present


def regular_exists_at(parent, name):
    try:
        row = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError:
        fail(_outcome_error())
    if not stat.S_ISREG(row.st_mode) or row.st_nlink != 1:
        fail(_outcome_error())
    return True


def bounded_at(parent, name, limit=8 * 1024 * 1024):
    try:
        fd = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent,
        )
        before = os.fstat(fd)
    except OSError:
        fail(_outcome_error())
    try:
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= limit
        ):
            fail(_outcome_error())
        data = bytearray()
        while len(data) <= limit:
            row = os.read(fd, min(1024 * 1024, limit + 1 - len(data)))
            if not row:
                break
            data.extend(row)
        after = os.fstat(fd)
        stable = lambda x: (
            x.st_dev,
            x.st_ino,
            x.st_mode,
            x.st_nlink,
            x.st_uid,
            x.st_gid,
            x.st_size,
            x.st_mtime_ns,
            x.st_ctime_ns,
        )
        if len(data) != before.st_size or stable(before) != stable(after):
            fail(_outcome_error())
        return bytes(data)
    finally:
        os.close(fd)


def strict_json_at(parent, name, keys=None, limit=8 * 1024 * 1024):
    try:

        def pairs(rows):
            out = {}
            for key, value in rows:
                if key in out:
                    raise ValueError
                out[key] = value
            return out

        value = json.loads(
            bounded_at(parent, name, limit).decode("utf-8", "strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except SystemExit:
        raise
    except Exception:
        fail(_outcome_error())
    if not isinstance(value, dict) or keys is not None and set(value) != set(keys):
        fail(_outcome_error())
    return value


def read_relative_at(parent, relative, limit=8 * 1024 * 1024):
    parts = PurePosixPath(relative).parts
    if (
        not parts
        or PurePosixPath(relative).is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
    ):
        fail(_outcome_error())
    descriptor = parent
    opened = []
    try:
        for part in parts[:-1]:
            descriptor = open_dir_at(descriptor, part)
            opened.append(descriptor)
        return bounded_at(descriptor, parts[-1], limit)
    finally:
        for fd in reversed(opened):
            os.close(fd)


def json_bytes(raw, keys=None, error=None):
    if error is None:
        error = _config().preparation_error
    try:

        def pairs(rows):
            out = {}
            for key, value in rows:
                if key in out:
                    raise ValueError
                out[key] = value
            return out

        value = json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except Exception:
        fail(error)
    if not isinstance(value, dict) or keys is not None and set(value) != set(keys):
        fail(error)
    return value


def _publish_at_impl(parent, name, value):
    raw = canonical(value) + b"\n"
    temp = f".{name}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
    fd = -1
    try:
        fd = os.open(
            temp,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent,
        )
        with os.fdopen(fd, "wb", closefd=True) as stream:
            fd = -1
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        os.fsync(parent)
    except FileExistsError:
        fail(_outcome_error())
    except OSError:
        fail(_outcome_error())
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temp, dir_fd=parent)
        except FileNotFoundError:
            pass


def _replace_at_impl(parent, name, value, expected):
    raw = canonical(value) + b"\n"
    temp = f".{name}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
    fd = -1
    try:
        fd = os.open(
            temp,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent,
        )
        with os.fdopen(fd, "wb", closefd=True) as stream:
            fd = -1
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if bounded_at(parent, name) != canonical(expected) + b"\n":
            fail(_outcome_error())
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            fail(_outcome_error())
        # Re-attest the directory entry immediately before replacement.  The
        # application lock serializes cooperating writers; this identity check
        # additionally turns an external swap into an unknown outcome instead
        # of silently overwriting evidence we did not review.
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (current.st_dev, current.st_ino, current.st_ctime_ns) != (
            before.st_dev,
            before.st_ino,
            before.st_ctime_ns,
        ):
            fail(_outcome_error())
        os.replace(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    except OSError:
        fail(_outcome_error())
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temp, dir_fd=parent)
        except FileNotFoundError:
            pass


def _unlink_at_impl(parent, name):
    """Remove a reconciled receipt and durably record the directory update."""

    try:
        row = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(row.st_mode) or row.st_nlink != 1:
            fail(_outcome_error())
        os.unlink(name, dir_fd=parent)
        os.fsync(parent)
    except FileNotFoundError:
        return
    except OSError:
        fail(_outcome_error())


def _run_impl(argv, input_data=None, limit=1024 * 1024):
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        result = subprocess.run(
            argv, input=input_data, stdout=out, stderr=err, timeout=30, check=False
        )
        out.seek(0, 2)
        a = out.tell()
        err.seek(0, 2)
        b = err.tell()
        if a > limit or b > limit:
            fail(_outcome_error())
        out.seek(0)
        err.seek(0)
        return result.returncode, out.read(), err.read()


_RUNNER = ContextVar("selection_submission_run", default=_run_impl)
_PUBLISHER = ContextVar("selection_submission_publish", default=_publish_at_impl)
_REPLACER = ContextVar("selection_submission_replace", default=_replace_at_impl)
_UNLINKER = ContextVar("selection_submission_unlink", default=_unlink_at_impl)
_IDENTITY = ContextVar("selection_submission_identity", default=None)


def run(argv, input_data=None, limit=1024 * 1024):
    return _RUNNER.get()(argv, input_data=input_data, limit=limit)


def publish_at(parent, name, value):
    return _PUBLISHER.get()(parent, name, value)


def replace_at(parent, name, value, expected):
    return _REPLACER.get()(parent, name, value, expected)


def unlink_at(parent, name):
    return _UNLINKER.get()(parent, name)


def empty_jobs():
    return {f: {"array": None, "merge": None} for f in FAMILIES}


def compatibility(jobs, status, submission_key, nonce, commit, created, submitted=None):
    if _config().stage == "final_validation" and status == "submitted":
        identity = _IDENTITY.get()
        if not isinstance(identity, Mapping):
            fail(_config().preparation_error)
        files = identity["files"]
        return {
            "kind": "mot_3d_selection_stage_submission",
            "stage": "final_validation",
            "status": "submitted",
            "dependency": "afterok",
            "families": {
                family: {
                    "array_job_id": jobs[family]["array"],
                    "merge_job_id": jobs[family]["merge"],
                }
                for family in FAMILIES
            },
            "campaign_manifest_sha256": files["campaign.json"],
            "worker_job_sha256": {
                family: files[_config().jobs[family]["array"]] for family in FAMILIES
            },
            "merge_job_sha256": {
                family: files[_config().jobs[family]["merge"]] for family in FAMILIES
            },
        }
    return {
        "kind": "mot_3d_selection_stage_submission",
        "stage": _config().stage,
        "status": status,
        "dependency": "afterok",
        "submission_key": submission_key,
        "nonce": nonce,
        "commit": commit,
        "created_unix_s": created,
        "submitted_unix_s": submitted,
        "families": {
            f: {"array_job_id": jobs[f]["array"], "merge_job_id": jobs[f]["merge"]}
            for f in FAMILIES
        },
    }


def exact_compat(
    record, jobs, status, submission_key, nonce, commit, created, submitted=None
):
    return record == compatibility(
        jobs, status, submission_key, nonce, commit, created, submitted
    )


def response(lifecycle, branch, jobs, nonce=None, submitted=None, arrays=0, merges=0):
    print(
        json.dumps(
            {
                "lifecycle": lifecycle,
                "branch": branch,
                "jobs": jobs,
                "submission_nonce": nonce,
                "submitted_unix_s": submitted,
                "completed_array_tasks": arrays,
                "completed_merge_jobs": merges,
            }
        )
    )


def qstat_fields(raw):
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeError:
        return None
    chunks = re.split(r"(?m)^Job Id:\s*", text)
    if chunks[0].strip():
        return None
    result = {}
    for chunk in chunks[1:]:
        lines = chunk.splitlines()
        identifier = lines[0].strip() if lines else ""
        if not identifier or identifier in result:
            return None
        fields = {}
        previous = None
        for line in lines[1:]:
            match = re.fullmatch(r"\s*([A-Za-z_]+)\s*=\s*(.*?)\s*", line)
            if match:
                if match.group(1) in fields:
                    return None
                previous = match.group(1)
                fields[previous] = match.group(2)
            elif line.startswith(("\t", "        ")) and previous is not None:
                continuation = line.strip()
                if not continuation:
                    return None
                fields[previous] += " " + continuation
            else:
                return None
        result[identifier] = fields
    return result


def one_state(fields):
    state = fields.get("job_state")
    if state in {"Q", "W"}:
        return "queued"
    if state in {"R", "E"}:
        return "running"
    if state in {"H", "S"}:
        return "held"
    if state in {"F", "X"} and fields.get("Exit_status") == "0":
        return "completed_success"
    if state in {"F", "X"} and "Exit_status" in fields:
        return "completed_failed"
    return "status_unknown"


def scheduler(job, kind):
    try:
        code, out, err = run(
            ["/opt/pbs/bin/qstat", "-x", "-t", "-f", job], limit=4 * 1024 * 1024
        )
    except Exception:
        return "status_unknown", 0
    fields = qstat_fields(out)
    if code or err or fields is None:
        return "status_unknown", 0
    if kind == "merge":
        if set(fields) != {job}:
            return "status_unknown", 0
        state = one_state(fields[job])
        return state, int(state == "completed_success")
    prefix = job.split("[]", 1)[0]
    expected = {f"{prefix}[{i}].zeus-master" for i in range(3)}
    if not expected.issubset(fields) or set(fields) - expected not in (set(), {job}):
        return "status_unknown", 0
    states = [one_state(fields[x]) for x in expected]
    complete = states.count("completed_success")
    if job in fields:
        parent = one_state(fields[job])
        if parent in {"completed_failed", "held", "status_unknown"}:
            return parent, complete
        if parent in {"queued", "running"} and complete == 3:
            return "status_unknown", complete
    for candidate in (
        "completed_failed",
        "held",
        "status_unknown",
        "running",
        "queued",
    ):
        if candidate in states:
            return candidate, complete
    return "completed_success", complete


def main(*, trusted_root_override=None):
    """Serve one pinned operation.

    ``trusted_root_override`` is deliberately keyword-only and unreachable from
    the receiver CLI.  It lets tests exercise the real descriptor/receipt
    state machine in an isolated repository without creating a fake /home
    hierarchy.
    """
    if len(sys.argv) != 5 or sys.argv[1] not in {"inspect", "submit", "status"}:
        fail("invalid_request")
    operation, username, project, encoded = sys.argv[1:]
    if re.fullmatch(
        r"[A-Za-z][A-Za-z0-9._-]{0,31}", username
    ) is None or project not in {
        f"/home/{username}/ytterbium_lab_simulation_new",
        f"/home/{username}/ytterbium_lab_simulation_ui_acceptance",
    }:
        fail("invalid_request")
    try:
        if encoded == "-":
            raw = sys.stdin.buffer.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                fail("invalid_request")
            payload = json.loads(raw.decode("utf-8", "strict"))
        else:
            payload = json.loads(base64.urlsafe_b64decode(encoded))
        requested = Path(project)
        root = (
            Path(trusted_root_override).resolve(strict=True)
            if trusted_root_override is not None
            else requested.resolve(strict=True)
        )
        relative = PurePosixPath(payload["campaign"])
    except Exception:
        fail("invalid_request")
    expected = {"campaign", "commit", "identity", "submission_key"} | (
        {"nonce"} if operation == "submit" else set()
    )
    if (
        not isinstance(payload, dict)
        or set(payload) != expected
        or (trusted_root_override is None and root != requested)
        or relative.is_absolute()
        or not (
            len(relative.parts) == 4
            or (len(relative.parts) == 5 and relative.parts[3] == "ui_acceptance")
        )
        or relative.parts[:3] != ("data", "optimization", "mot_3d")
        or any(x in {"", ".", ".."} for x in relative.parts)
        or not exact_match(HEX40, payload.get("commit"))
        or not exact_match(HEX64, payload.get("submission_key"))
    ):
        fail("invalid_request")
    identity = payload.get("identity")
    identity_keys = {
        "campaign_sha256",
        "local_transition_receipt_sha256",
        "transition_key",
        "remote_transition_receipt_sha256",
        "bundle_sha256",
        "files",
        "science",
        "physical_model_sha256",
        "upstream_campaign_sha256",
        "upstream_final_report_sha256",
        "timestep_policy_sha256",
        "code_files",
    }
    code_names = _config().code_names
    if (
        not isinstance(identity, dict)
        or set(identity) != identity_keys
        or any(
            not exact_match(HEX64, identity.get(x))
            for x in identity_keys - {"files", "science", "code_files"}
        )
        or not isinstance(identity.get("files"), dict)
        or set(identity["files"]) != _config().files
        or any(not exact_match(HEX64, x) for x in identity["files"].values())
        or not isinstance(identity.get("code_files"), dict)
        or set(identity["code_files"]) != code_names
        or any(not exact_match(HEX64, x) for x in identity["code_files"].values())
    ):
        fail("invalid_request")
    _IDENTITY.set(identity)
    campaign = root.joinpath(*relative.parts)
    root_fd = os.open(root, DIR_FLAGS)
    campaign_fd = root_fd
    opened = []
    for part in relative.parts:
        campaign_fd = open_dir_at(campaign_fd, part)
        opened.append(campaign_fd)
    code, out, err = run(
        ["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD"], limit=4096
    )
    revision = out.decode("ascii", "strict").strip() if not code and not err else ""
    code2, out2, err2 = run(
        ["/usr/bin/git", "-C", str(root), "branch", "--show-current"], limit=4096
    )
    branch = out2.decode("utf-8", "strict").strip() if not code2 and not err2 else ""
    code3, out3, err3 = run(
        [
            "/usr/bin/git",
            "-C",
            str(root),
            "status",
            "--porcelain",
            "--untracked-files=no",
        ],
        limit=1024 * 1024,
    )
    if (
        revision != payload["commit"]
        or not branch
        or len(branch) > 256
        or not branch.isprintable()
        or code3
        or err3
        or out3
    ):
        fail("remote_checkout_mismatch")
    manifest_raw = read_relative_at(campaign_fd, "campaign.json")
    manifest = json_bytes(manifest_raw)
    from workflow_api.acceptance_remote import assert_campaign_target

    try:
        from workflow_api.mot_3d_workload import assert_receiver_target

        assert_receiver_target(
            manifest,
            username,
            project,
            relative,
            trusted_root_override=trusted_root_override,
        )
    except ValueError:
        fail(_config().preparation_error)
    from workflow_api import mot_3d_workload as workload

    try:
        workload.validate_location(manifest, relative)
    except ValueError:
        fail(_config().preparation_error)
    evidence = manifest.get("design", {}).get("timestep_evidence", {})
    upstream = manifest.get("upstream_2d_campaign", {})
    if (
        manifest.get("stage") != _config().stage
        or manifest.get("name") != relative.name
        or manifest.get("provenance", {}).get("git_commit") != payload["commit"]
        or manifest.get("provenance", {}).get("physical_model_sha256")
        != identity["physical_model_sha256"]
        or upstream.get("campaign_sha256") != identity["upstream_campaign_sha256"]
        or upstream.get("final_report_sha256")
        != identity["upstream_final_report_sha256"]
        or evidence.get("policy_sha256") != identity["timestep_policy_sha256"]
    ):
        fail(_config().preparation_error)
    design = manifest.get("design", {})
    stage = manifest.get("stages", {}).get(_config().stage, {})
    expected_science = dict(_config().science)
    expected_science["recoil_seeds"] = list(expected_science["recoil_seeds"])
    expected_science["dt_s"] = design.get(_config().dt_design_key)
    expected_science["solver"] = design.get("solver")
    expected_science = workload.submission_science(
        manifest, _config().stage, expected_science
    )
    if (
        identity["science"] != expected_science
        or stage.get("classification") != expected_science["classification"]
        or (
            _config().input_role is not None
            and (
                stage.get("input_role") != _config().input_role
                if isinstance(_config().input_role, str)
                else stage.get("input_roles") != list(_config().input_role)
            )
        )
    ):
        fail(_config().preparation_error)
    transition = json_bytes(
        read_relative_at(
            campaign_fd,
            f".mot_ui/transitions/{_config().transition_receipt}",
        )
    )
    if (
        digest(transition) != identity["remote_transition_receipt_sha256"]
        or transition.get("status") != _config().transition_status
        or transition.get("transition_key") != identity["transition_key"]
        or transition.get("bundle", {}).get("bundle_sha256")
        != identity["bundle_sha256"]
    ):
        fail(_config().preparation_error)
    frozen = {}
    for name, expected_hash in identity["files"].items():
        raw = read_relative_at(campaign_fd, name)
        if hashlib.sha256(raw).hexdigest() != expected_hash:
            fail(_config().preparation_error)
        frozen[name] = raw
    for name, expected_hash in identity["code_files"].items():
        code_path = root.joinpath(*PurePosixPath(name).parts)
        if (
            hashlib.sha256(
                bounded_at(root_fd, name)
                if "/" not in name
                else read_relative_at(root_fd, name)
            ).hexdigest()
            != expected_hash
        ):
            fail(_config().preparation_error)

    predecessor_names = set()

    def reattest():
        if _config().stage == "final_validation" and submissions_fd >= 0:
            current_names = set(os.listdir(submissions_fd))
            if (_authenticated_predecessor_names(campaign_fd, submissions_fd, current_names, transition, payload["commit"]) != predecessor_names
                    or any(name.startswith("final_validation_input_generation") and name not in predecessor_names for name in current_names)):
                fail(_outcome_error())
        if read_relative_at(campaign_fd, "campaign.json") != manifest_raw:
            fail(_outcome_error())
        for name, raw in frozen.items():
            if read_relative_at(campaign_fd, name) != raw:
                fail(_outcome_error())
        for name, expected_hash in identity["code_files"].items():
            if (
                hashlib.sha256(read_relative_at(root_fd, name)).hexdigest()
                != expected_hash
            ):
                fail(_outcome_error())
        a, b, c = run(
            ["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD"], limit=4096
        )
        d, e, f = run(
            [
                "/usr/bin/git",
                "-C",
                str(root),
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
            limit=1024 * 1024,
        )
        if (
            a
            or c
            or b.decode("ascii", "strict").strip() != payload["commit"]
            or d
            or f
            or e
        ):
            fail(_outcome_error())

    if (
        digest(
            {"campaign": relative.as_posix(), "commit": payload["commit"], **identity}
        )
        != payload["submission_key"]
    ):
        fail(_config().preparation_error)
    mot_ui_fd = open_dir_at(campaign_fd, ".mot_ui")
    opened.append(mot_ui_fd)
    submissions_fd = -1
    if operation == "submit":
        submissions_fd = open_dir_at(mot_ui_fd, "submissions", create=True)
        opened.append(submissions_fd)
    else:
        try:
            submissions_fd = os.open("submissions", DIR_FLAGS, dir_fd=mot_ui_fd)
            row = os.fstat(submissions_fd)
            if not stat.S_ISDIR(row.st_mode):
                raise OSError
            opened.append(submissions_fd)
        except FileNotFoundError:
            submissions_fd = -1
        except OSError:
            fail(_outcome_error())
    final = f"{_config().stage}.json"
    pending = f"{_config().stage}.pending.json"
    compat = f"{_config().stage}_submission.json"
    lock = -1
    if submissions_fd >= 0:
        if operation == "submit" or regular_exists_at(
            submissions_fd, f"{_config().stage}.lock"
        ):
            try:
                lock = os.open(
                    f"{_config().stage}.lock",
                    os.O_RDWR
                    | (os.O_CREAT if operation == "submit" else 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=submissions_fd,
                )
                row = os.fstat(lock)
                if not stat.S_ISREG(row.st_mode) or row.st_nlink != 1:
                    fail(_outcome_error())
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                fail(_outcome_error())
    jobs = empty_jobs()
    nonce = submitted = None
    try:
        if submissions_fd >= 0 and regular_exists_at(submissions_fd, final):
            record = strict_json_at(
                submissions_fd,
                final,
                keys={
                    "version",
                    "status",
                    "submission_key",
                    "nonce",
                    "commit",
                    "jobs",
                    "created_unix_s",
                    "submitted_unix_s",
                },
            )
            jobs = record["jobs"]
            nonce = record["nonce"]
            submitted = record["submitted_unix_s"]
            created = record["created_unix_s"]
            if (
                record["version"] != 1
                or record["status"] != "submitted"
                or record["submission_key"] != payload["submission_key"]
                or record["commit"] != payload["commit"]
                or not exact_match(HEX32, nonce)
                or not stamp(created)
                or not stamp(submitted)
                or submitted < created
                or not isinstance(jobs, dict)
                or set(jobs) != set(FAMILIES)
            ):
                fail(_outcome_error())
            seen = set()
            done_steps = {}
            for family in FAMILIES:
                if (
                    not isinstance(jobs.get(family), dict)
                    or set(jobs[family]) != {"array", "merge"}
                    or not exact_match(ARRAY, jobs[family]["array"])
                    or not exact_match(SCALAR, jobs[family]["merge"])
                ):
                    fail(_outcome_error())
                numeric = {
                    jobs[family]["array"].split("[", 1)[0],
                    jobs[family]["merge"].split(".", 1)[0],
                }
                if seen & numeric:
                    fail(_outcome_error())
                seen |= numeric
                for kind in ("array", "merge"):
                    step_name = f"{_config().stage}_{family}_{kind}.json"
                    step = strict_json_at(
                        submissions_fd,
                        step_name,
                        keys={
                            "status",
                            "submission_key",
                            "nonce",
                            "commit",
                            "family",
                            "kind",
                            "pbs_sha256",
                            "depends_on",
                            "job_id",
                            "created_unix_s",
                            "completed_unix_s",
                        },
                    )
                    dependency = jobs[family]["array"] if kind == "merge" else None
                    if (
                        step["status"] != "submitted"
                        or step["submission_key"] != payload["submission_key"]
                        or step["nonce"] != nonce
                        or step["commit"] != payload["commit"]
                        or step["family"] != family
                        or step["kind"] != kind
                        or step["pbs_sha256"]
                        != identity["files"][_config().jobs[family][kind]]
                        or step["depends_on"] != dependency
                        or step["job_id"] != jobs[family][kind]
                        or not stamp(step["created_unix_s"])
                        or not stamp(step["completed_unix_s"])
                        or step["completed_unix_s"] < step["created_unix_s"]
                    ):
                        fail(_outcome_error())
                    done_steps[(family, kind)] = step
            allowed_names = {f"{_config().stage}.lock", final, pending}
            allowed_names |= {
                f"{_config().stage}_{family}_{kind}.{suffix}.json"
                for family in FAMILIES
                for kind in ("array", "merge")
                for suffix in ("pending",)
            }
            allowed_names |= {
                f"{_config().stage}_{family}_{kind}.json"
                for family in FAMILIES
                for kind in ("array", "merge")
            }
            try:
                names = set(os.listdir(submissions_fd))
            except OSError:
                fail(_outcome_error())
            predecessor_names = _authenticated_predecessor_names(
                campaign_fd, submissions_fd, names, transition, payload["commit"]
            )
            allowed_names |= predecessor_names
            if any(
                name.startswith(_config().stage) and name not in allowed_names
                for name in names
            ):
                fail(_outcome_error())
            if regular_exists_at(submissions_fd, pending):
                global_row = strict_json_at(
                    submissions_fd,
                    pending,
                    keys={
                        "status",
                        "submission_key",
                        "nonce",
                        "commit",
                        "created_unix_s",
                    },
                )
                if global_row != {
                    "status": "pending",
                    "submission_key": payload["submission_key"],
                    "nonce": nonce,
                    "commit": payload["commit"],
                    "created_unix_s": created,
                }:
                    fail(_outcome_error())
            for family in FAMILIES:
                for kind in ("array", "merge"):
                    pending_name = f"{_config().stage}_{family}_{kind}.pending.json"
                    if regular_exists_at(submissions_fd, pending_name):
                        pending_row = strict_json_at(
                            submissions_fd,
                            pending_name,
                            keys={
                                "status",
                                "submission_key",
                                "nonce",
                                "commit",
                                "family",
                                "kind",
                                "pbs_sha256",
                                "depends_on",
                                "created_unix_s",
                            },
                        )
                        expected = {
                            key: value
                            for key, value in done_steps[(family, kind)].items()
                            if key not in {"job_id", "completed_unix_s"}
                        }
                        expected["status"] = "pending"
                        if pending_row != expected:
                            fail(_outcome_error())
            expected_compat = compatibility(
                jobs,
                "submitted",
                payload["submission_key"],
                nonce,
                payload["commit"],
                created,
                submitted,
            )
            if regular_exists_at(campaign_fd, compat):
                current_compat = strict_json_at(campaign_fd, compat)
                if current_compat != expected_compat:
                    if not exact_compat(
                        current_compat,
                        jobs,
                        "submitting",
                        payload["submission_key"],
                        nonce,
                        payload["commit"],
                        created,
                    ):
                        fail(_outcome_error())
                    if operation == "inspect":
                        response("submitted", branch, jobs, nonce, submitted)
                        return
                    replace_at(campaign_fd, compat, expected_compat, current_compat)
            else:
                if operation == "inspect":
                    response("submitted", branch, jobs, nonce, submitted)
                    return
                if lock < 0:
                    fail(_outcome_error())
                publish_at(campaign_fd, compat, expected_compat)
            if operation != "inspect":
                for family in FAMILIES:
                    for kind in ("array", "merge"):
                        name = f"{_config().stage}_{family}_{kind}.pending.json"
                        if regular_exists_at(submissions_fd, name):
                            unlink_at(submissions_fd, name)
                if regular_exists_at(submissions_fd, pending):
                    unlink_at(submissions_fd, pending)
            if operation == "status":
                states = []
                array_count = merge_count = 0
                for family in FAMILIES:
                    a, c = scheduler(jobs[family]["array"], "array")
                    m, d = scheduler(jobs[family]["merge"], "merge")
                    states.extend((a, m))
                    array_count += c
                    merge_count += d
                lifecycle = "completed_success"
                for candidate in (
                    "completed_failed",
                    "held",
                    "status_unknown",
                    "running",
                    "queued",
                ):
                    if candidate in states:
                        lifecycle = candidate
                        break
                response(
                    lifecycle, branch, jobs, nonce, submitted, array_count, merge_count
                )
                return
            response("submitted", branch, jobs, nonce, submitted)
            return

        global_pending = None
        if submissions_fd >= 0 and regular_exists_at(submissions_fd, pending):
            global_pending = strict_json_at(
                submissions_fd,
                pending,
                keys={"status", "submission_key", "nonce", "commit", "created_unix_s"},
            )
            if (
                global_pending["status"] != "pending"
                or global_pending["submission_key"] != payload["submission_key"]
                or global_pending["commit"] != payload["commit"]
                or not exact_match(HEX32, global_pending["nonce"])
                or not stamp(global_pending["created_unix_s"])
            ):
                fail(_outcome_error())
        if submissions_fd >= 0:
            allowed_names = {
                f"{_config().stage}.lock",
                final,
                pending,
                *(
                    f"{_config().stage}_{family}_{kind}.{suffix}.json"
                    for family in FAMILIES
                    for kind in ("array", "merge")
                    for suffix in ("pending",)
                ),
                *(
                    f"{_config().stage}_{family}_{kind}.json"
                    for family in FAMILIES
                    for kind in ("array", "merge")
                ),
            }
            try:
                names = set(os.listdir(submissions_fd))
            except OSError:
                fail(_outcome_error())
            predecessor_names = _authenticated_predecessor_names(
                campaign_fd, submissions_fd, names, transition, payload["commit"]
            )
            allowed_names |= predecessor_names
            if any(
                name.startswith(_config().stage) and name not in allowed_names
                for name in names
            ):
                fail(_outcome_error())
        step_jobs = empty_jobs()
        step_rows = []
        prefix_open = True
        for family in FAMILIES:
            for kind in ("array", "merge"):
                name = f"{_config().stage}_{family}_{kind}.json"
                if submissions_fd < 0 or not regular_exists_at(submissions_fd, name):
                    prefix_open = False
                    continue
                if not prefix_open:
                    fail(_outcome_error())
                row = strict_json_at(
                    submissions_fd,
                    name,
                    keys={
                        "status",
                        "submission_key",
                        "nonce",
                        "commit",
                        "family",
                        "kind",
                        "pbs_sha256",
                        "depends_on",
                        "job_id",
                        "created_unix_s",
                        "completed_unix_s",
                    },
                )
                job_file = _config().jobs[family][kind]
                expected_dependency = (
                    step_jobs[family]["array"] if kind == "merge" else None
                )
                value = row["job_id"]
                if (
                    row["status"] != "submitted"
                    or row["submission_key"] != payload["submission_key"]
                    or row["commit"] != payload["commit"]
                    or row["family"] != family
                    or row["kind"] != kind
                    or row["pbs_sha256"] != identity["files"][job_file]
                    or row["depends_on"] != expected_dependency
                    or not exact_match(HEX32, row["nonce"])
                    or not stamp(row["created_unix_s"])
                    or not stamp(row["completed_unix_s"])
                    or row["completed_unix_s"] < row["created_unix_s"]
                    or not exact_match(ARRAY if kind == "array" else SCALAR, value)
                ):
                    fail(_outcome_error())
                step_jobs[family][kind] = value
                step_rows.append(row)
        count = len(step_rows)
        pending_steps = []
        stale_pending = []
        sequence = [
            (family, kind) for family in FAMILIES for kind in ("array", "merge")
        ]
        for index, (family, kind) in enumerate(sequence):
            pending_name = f"{_config().stage}_{family}_{kind}.pending.json"
            if submissions_fd >= 0 and regular_exists_at(submissions_fd, pending_name):
                row = strict_json_at(
                    submissions_fd,
                    pending_name,
                    keys={
                        "status",
                        "submission_key",
                        "nonce",
                        "commit",
                        "family",
                        "kind",
                        "pbs_sha256",
                        "depends_on",
                        "created_unix_s",
                    },
                )
                expected_dependency = (
                    step_jobs[family]["array"] if kind == "merge" else None
                )
                valid = (
                    global_pending is not None
                    and row["status"] == "pending"
                    and row["submission_key"] == payload["submission_key"]
                    and row["nonce"] == global_pending["nonce"]
                    and row["commit"] == payload["commit"]
                    and row["family"] == family
                    and row["kind"] == kind
                    and row["pbs_sha256"]
                    == identity["files"][_config().jobs[family][kind]]
                    and row["depends_on"] == expected_dependency
                    and stamp(row["created_unix_s"])
                )
                if not valid:
                    fail(_outcome_error())
                if (
                    index == count - 1
                    and count
                    and step_rows[index]["created_unix_s"] == row["created_unix_s"]
                ):
                    stale_pending.append(pending_name)
                elif index == count:
                    pending_steps.append(row)
                else:
                    fail(_outcome_error())
        if len(pending_steps) > 1:
            fail(_outcome_error())
        if pending_steps:
            response("outcome_unknown", branch, step_jobs, global_pending["nonce"])
            return
        if operation != "inspect":
            for name in stale_pending:
                unlink_at(submissions_fd, name)
        if count:
            nonces = {row["nonce"] for row in step_rows}
            if global_pending is None or nonces != {global_pending["nonce"]}:
                fail(_outcome_error())
            numeric = [
                row["job_id"].split("[", 1)[0].split(".", 1)[0] for row in step_rows
            ]
            if len(numeric) != len(set(numeric)):
                fail(_outcome_error())
            if count < 4:
                if not regular_exists_at(campaign_fd, compat):
                    fail(_outcome_error())
                current_compat = strict_json_at(campaign_fd, compat)
                expected_arguments = (
                    "submitting",
                    payload["submission_key"],
                    global_pending["nonce"],
                    payload["commit"],
                    global_pending["created_unix_s"],
                )
                if not exact_compat(current_compat, step_jobs, *expected_arguments):
                    previous_jobs = {
                        family: dict(values) for family, values in step_jobs.items()
                    }
                    previous_family, previous_kind = sequence[count - 1]
                    previous_jobs[previous_family][previous_kind] = None
                    if not exact_compat(
                        current_compat, previous_jobs, *expected_arguments
                    ):
                        fail(_outcome_error())
                    if operation != "inspect":
                        if lock < 0:
                            fail(_outcome_error())
                        replace_at(
                            campaign_fd,
                            compat,
                            compatibility(step_jobs, *expected_arguments),
                            current_compat,
                        )
                response("partial", branch, step_jobs, global_pending["nonce"])
                return
            submitted = max(row["completed_unix_s"] for row in step_rows)
            nonce = global_pending["nonce"]
            created = global_pending["created_unix_s"]
            record = {
                "version": 1,
                "status": "submitted",
                "submission_key": payload["submission_key"],
                "nonce": nonce,
                "commit": payload["commit"],
                "jobs": step_jobs,
                "created_unix_s": created,
                "submitted_unix_s": submitted,
            }
            if operation == "inspect":
                response("submitted", branch, step_jobs, nonce, submitted)
                return
            publish_at(submissions_fd, final, record)
            expected_compat = compatibility(
                step_jobs,
                "submitted",
                payload["submission_key"],
                nonce,
                payload["commit"],
                created,
                submitted,
            )
            if regular_exists_at(campaign_fd, compat):
                prior_compat = strict_json_at(campaign_fd, compat)
                previous_jobs = {key: dict(value) for key, value in step_jobs.items()}
                previous_jobs["single_pass"]["merge"] = None
                if not (
                    exact_compat(
                        prior_compat,
                        step_jobs,
                        "submitting",
                        payload["submission_key"],
                        nonce,
                        payload["commit"],
                        created,
                    )
                    or exact_compat(
                        prior_compat,
                        previous_jobs,
                        "submitting",
                        payload["submission_key"],
                        nonce,
                        payload["commit"],
                        created,
                    )
                ):
                    fail(_outcome_error())
                replace_at(campaign_fd, compat, expected_compat, prior_compat)
            else:
                publish_at(campaign_fd, compat, expected_compat)
            response("submitted", branch, step_jobs, nonce, submitted)
            return
        if global_pending is not None:
            response("outcome_unknown", branch, jobs, global_pending["nonce"])
            return
        if regular_exists_at(campaign_fd, compat):
            fail(_outcome_error())
        if operation in {"inspect", "status"}:
            response("eligible", branch, jobs)
            return

        nonce = payload.get("nonce")
        if not isinstance(nonce, str) or HEX32.fullmatch(nonce) is None:
            fail("invalid_request")
        created = int(time.time())
        global_pending = {
            "status": "pending",
            "submission_key": payload["submission_key"],
            "nonce": nonce,
            "commit": payload["commit"],
            "created_unix_s": created,
        }
        publish_at(submissions_fd, pending, global_pending)
        publish_at(
            campaign_fd,
            compat,
            compatibility(
                jobs,
                "submitting",
                payload["submission_key"],
                nonce,
                payload["commit"],
                created,
            ),
        )
        for family in FAMILIES:
            for kind in ("array", "merge"):
                previous = jobs[family]["array"] if kind == "merge" else None
                job_file = _config().jobs[family][kind]
                step_created = int(time.time())
                step_pending = f"{_config().stage}_{family}_{kind}.pending.json"
                step_done = f"{_config().stage}_{family}_{kind}.json"
                pending_row = {
                    "status": "pending",
                    "submission_key": payload["submission_key"],
                    "nonce": nonce,
                    "commit": payload["commit"],
                    "family": family,
                    "kind": kind,
                    "pbs_sha256": identity["files"][job_file],
                    "depends_on": previous,
                    "created_unix_s": step_created,
                }
                publish_at(submissions_fd, step_pending, pending_row)
                reattest()
                argv = ["/usr/local/bin/qsub"] + (
                    ["-J", workload.array_range(manifest, _config().stage)]
                    if kind == "array"
                    else ["-W", f"depend=afterok:{previous}"]
                )
                try:
                    code, out, err = run(argv, input_data=frozen[job_file])
                except Exception:
                    response("outcome_unknown", branch, jobs, nonce)
                    return
                try:
                    job_id = out.decode("ascii", "strict").strip()
                except UnicodeError:
                    response("outcome_unknown", branch, jobs, nonce)
                    return
                matcher = ARRAY if kind == "array" else SCALAR
                if code or err or matcher.fullmatch(job_id) is None:
                    response("outcome_unknown", branch, jobs, nonce)
                    return
                numeric = job_id.split("[", 1)[0].split(".", 1)[0]
                if numeric in {
                    x.split("[", 1)[0].split(".", 1)[0]
                    for row in jobs.values()
                    for x in row.values()
                    if x
                }:
                    fail(_outcome_error())
                done = {
                    **pending_row,
                    "status": "submitted",
                    "job_id": job_id,
                    "completed_unix_s": int(time.time()),
                }
                before_jobs = {key: dict(value) for key, value in jobs.items()}
                publish_at(submissions_fd, step_done, done)
                unlink_at(submissions_fd, step_pending)
                jobs[family][kind] = job_id
                previous_compat = strict_json_at(campaign_fd, compat)
                if not exact_compat(
                    previous_compat,
                    before_jobs,
                    "submitting",
                    payload["submission_key"],
                    nonce,
                    payload["commit"],
                    created,
                ):
                    fail(_outcome_error())
                replace_at(
                    campaign_fd,
                    compat,
                    compatibility(
                        jobs,
                        "submitting",
                        payload["submission_key"],
                        nonce,
                        payload["commit"],
                        created,
                    ),
                    previous_compat,
                )
        reattest()
        submitted = int(time.time())
        record = {
            "version": 1,
            "status": "submitted",
            "submission_key": payload["submission_key"],
            "nonce": nonce,
            "commit": payload["commit"],
            "jobs": jobs,
            "created_unix_s": created,
            "submitted_unix_s": submitted,
        }
        publish_at(submissions_fd, final, record)
        replace_at(
            campaign_fd,
            compat,
            compatibility(
                jobs,
                "submitted",
                payload["submission_key"],
                nonce,
                payload["commit"],
                created,
                submitted,
            ),
            strict_json_at(campaign_fd, compat),
        )
        unlink_at(submissions_fd, pending)
        response("submitted", branch, jobs, nonce, submitted)
    finally:
        if lock >= 0:
            fcntl.flock(lock, fcntl.LOCK_UN)
            os.close(lock)
        for fd in reversed(opened):
            try:
                os.close(fd)
            except OSError:
                pass
        os.close(root_fd)


def serve(
    descriptor: ReceiverDescriptor,
    *,
    trusted_root_override=None,
    run_override=None,
    publish_override=None,
    replace_override=None,
    unlink_override=None,
):
    with descriptor_scope(descriptor):
        tokens = []
        for variable, value in (
            (_RUNNER, run_override),
            (_PUBLISHER, publish_override),
            (_REPLACER, replace_override),
            (_UNLINKER, unlink_override),
        ):
            if value is not None:
                tokens.append((variable, variable.set(value)))
        try:
            return main(trusted_root_override=trusted_root_override)
        finally:
            for variable, token in reversed(tokens):
                variable.reset(token)
