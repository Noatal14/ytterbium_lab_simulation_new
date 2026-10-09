"""Safe, review-before-write preparation of a portable 2D campaign on Zeus.

The service is deliberately independent of SSH.  A narrow transport adapter must
provide inspection and conditional, no-overwrite writes.  This keeps preview
strictly read-only and makes the mutation boundary straightforward to test.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat as stat_module
import struct
import subprocess
import tempfile
import threading
import time
from types import MappingProxyType
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from workflow_api.mot_2d_validation import modern_contract
from workflow_api.discovery import build_registry
from workflow_api.preview_registry import PreviewRegistry
from workflow_api.pinned_ssh import (
    PinnedSshPolicy,
    PinnedSshRunner,
    TransferOperation,
)
from workflow_api.repository_paths import canonical_repo_relative, resolve_repo_relative
from workflow_api.zeus_snapshot import ZEUS_HOST, ZeusProfile


COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CAMPAIGN_ROOT = "data/optimization/mot_2d"
INPUT_ROOT = "data/particle_states/after_zeeman"
TOKEN_LIFETIME_SECONDS = 5 * 60
MAX_PENDING_PREVIEWS = 64
MAX_TRANSFER_BYTES = 128 * 1024 * 1024
MAX_REMOTE_OUTPUT = 2 * 1024 * 1024


class ZeusPreparationError(RuntimeError):
    """A stable error code safe to expose through an API."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RemoteSnapshot:
    git_commit: str
    clean: bool
    # Missing paths are omitted. Values are lowercase SHA-256 digests.
    artifacts: Mapping[str, str]


class ZeusPreparationTransport(Protocol):
    """Pinned Zeus transport; implementations must make writes conditional."""

    def inspect(self, paths: tuple[str, ...]) -> RemoteSnapshot:
        """Read commit, cleanliness and hashes. This operation must not write."""

    def upload_missing_inputs(self, files: Mapping[str, tuple[Path, str, int]], expected_commit: str) -> None:
        """Upload only absent inputs, atomically; fail if any target now exists."""

    def publish_campaign_atomic(self, files: Mapping[str, tuple[Path, str, int]], expected_commit: str) -> None:
        """Publish the complete campaign directory last; never replace a target."""


_REMOTE_TRANSFER_SCRIPT = r'''import hashlib,json,os,pathlib,secrets,stat,struct,subprocess,sys
op, username, project_text, encoded_paths, expected_commit = sys.argv[1:6]
project = pathlib.Path(project_text)
home = pathlib.Path('/home') / username
try: project = project.resolve(strict=True)
except (OSError,RuntimeError): print(json.dumps({'error':'remote_project_missing'})); raise SystemExit(20)
if not project.is_dir() or (project != home and home not in project.parents):
    print(json.dumps({'error':'remote_project_missing'})); raise SystemExit(20)
NOFOLLOW=getattr(os,'O_NOFOLLOW',0); DIRECTORY=getattr(os,'O_DIRECTORY',0)
try:
    root_fd=os.open(project,os.O_RDONLY|DIRECTORY|NOFOLLOW)
    os.fchdir(root_fd)
except OSError: print(json.dumps({'error':'remote_project_missing'})); raise SystemExit(20)
try: paths = json.loads(__import__('base64').urlsafe_b64decode(encoded_paths).decode('utf-8'))
except Exception: print(json.dumps({'error':'invalid_request'})); raise SystemExit(21)
if not isinstance(paths,list) or len(paths)>72 or len(paths)!=len(set(paths)):
    print(json.dumps({'error':'invalid_request'})); raise SystemExit(21)
def relative(text):
    if not isinstance(text,str) or not text or len(text.encode())>512 or '\\' in text or not text.isprintable(): raise ValueError()
    pure=pathlib.PurePosixPath(text)
    if pure.is_absolute() or pure.as_posix()!=text or any(x in ('','.','..') for x in pure.parts): raise ValueError()
    allowed=(('data','particle_states','after_zeeman'),('data','optimization','mot_2d'))
    if not any(pure.parts[:len(prefix)]==prefix for prefix in allowed): raise ValueError()
    target=project.joinpath(*pure.parts)
    current=project
    for part in pure.parts:
        current=current/part
        if current.is_symlink(): raise ValueError()
    return pure,target
try: resolved=[relative(path) for path in paths]
except (ValueError,OSError): print(json.dumps({'error':'invalid_request'})); raise SystemExit(21)
def run(argv):
    result=subprocess.run(argv,cwd='.',stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
      env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':str(home),'LC_ALL':'C'},timeout=15,check=False)
    return result.returncode,result.stdout.decode('utf-8','strict')
def checkout_matches():
    try:
        hc,head=run(['git','rev-parse','--verify','HEAD^{commit}']); sc,status=run(['git','status','--porcelain=v1','--untracked-files=no'])
        return not hc and not sc and head.strip()==expected_commit and not status
    except Exception: return False
if op=='inspect':
    try:
        hc,head=run(['git','rev-parse','--verify','HEAD^{commit}']); sc,status=run(['git','status','--porcelain=v1','--untracked-files=no'])
        if hc or sc: raise RuntimeError()
        artifacts={}
        for pure,target in resolved:
            parent=os.dup(root_fd)
            try:
                try:
                    for part in pure.parts[:-1]:
                        following=os.open(part,os.O_RDONLY|DIRECTORY|NOFOLLOW,dir_fd=parent); os.close(parent); parent=following
                    fd=os.open(pure.parts[-1],os.O_RDONLY|os.O_NONBLOCK|NOFOLLOW,dir_fd=parent)
                except FileNotFoundError: continue
                try:
                    if not stat.S_ISREG(os.fstat(fd).st_mode): raise RuntimeError()
                    digest=hashlib.sha256()
                    while True:
                        chunk=os.read(fd,1048576)
                        if not chunk: break
                        digest.update(chunk)
                    artifacts[pure.as_posix()]=digest.hexdigest()
                finally: os.close(fd)
            finally: os.close(parent)
        print(json.dumps({'git_commit':head.strip(),'clean':not bool(status),'artifacts':artifacts},sort_keys=True))
    except Exception: print(json.dumps({'error':'remote_check_failed'})); raise SystemExit(22)
    raise SystemExit()
if op not in ('inputs','campaign'): print(json.dumps({'error':'invalid_request'})); raise SystemExit(21)
if not checkout_matches(): print(json.dumps({'error':'remote_checkout_mismatch'})); raise SystemExit(25)
class CheckoutMismatch(Exception): pass
def directory_fd(parts,create=False,start_fd=None):
    current=os.dup(root_fd if start_fd is None else start_fd)
    try:
        for part in parts:
            if create:
                try: os.mkdir(part,0o700,dir_fd=current)
                except FileExistsError: pass
            following=os.open(part,os.O_RDONLY|DIRECTORY|NOFOLLOW,dir_fd=current)
            os.close(current); current=following
        return current
    except Exception:
        os.close(current); raise
def temporary_fd(parent_fd):
    for _ in range(128):
        name='.zeus-transfer-'+secrets.token_hex(16)
        try: return os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|NOFOLLOW,0o600,dir_fd=parent_fd),name
        except FileExistsError: continue
    raise RuntimeError()
def remove_tree(parent_fd,name):
    try: child_fd=os.open(name,os.O_RDONLY|DIRECTORY|NOFOLLOW,dir_fd=parent_fd)
    except FileNotFoundError: return
    try:
        for entry in os.listdir(child_fd):
            metadata=os.stat(entry,dir_fd=child_fd,follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode): remove_tree(child_fd,entry)
            else: os.unlink(entry,dir_fd=child_fd)
    finally: os.close(child_fd)
    os.rmdir(name,dir_fd=parent_fd)
def receive(expected, staging_fd=None, campaign_prefix=None):
    result={}
    for pure,target in expected:
        header=sys.stdin.buffer.read(8)
        expected_digest=sys.stdin.buffer.read(64)
        if len(header)!=8 or len(expected_digest)!=64: raise ValueError()
        size=struct.unpack('!Q',header)[0]
        if size>134217728: raise ValueError()
        digest=hashlib.sha256()
        relative_parts=pure.parts if staging_fd is None else pure.parts[len(campaign_prefix):]
        parent_fd=directory_fd(relative_parts[:-1],create=True,start_fd=staging_fd)
        try: os.stat(relative_parts[-1],dir_fd=parent_fd,follow_symlinks=False); raise FileExistsError()
        except FileNotFoundError: pass
        fd,name=temporary_fd(parent_fd)
        try:
            with os.fdopen(fd,'wb') as output:
                remaining=size
                while remaining:
                    chunk=sys.stdin.buffer.read(min(1048576,remaining))
                    if not chunk: raise ValueError()
                    output.write(chunk); digest.update(chunk); remaining-=len(chunk)
                output.flush(); os.fsync(output.fileno())
            observed=digest.hexdigest()
            if observed.encode('ascii')!=expected_digest: raise ValueError()
            result[pure]=(parent_fd,name,relative_parts[-1],observed)
        except Exception:
            try: os.unlink(name,dir_fd=parent_fd)
            except OSError: pass
            os.close(parent_fd); raise
    if sys.stdin.buffer.read(1): raise ValueError()
    return result
try:
    if op=='inputs':
        received=receive(resolved)
        try:
            for pure,(parent_fd,temporary,target_name,digest) in received.items():
                if not checkout_matches(): raise CheckoutMismatch()
                os.link(temporary,target_name,src_dir_fd=parent_fd,dst_dir_fd=parent_fd,follow_symlinks=False)
                os.unlink(temporary,dir_fd=parent_fd); os.close(parent_fd)
        except Exception:
            for parent_fd,temporary,_,_ in received.values():
                try: os.unlink(temporary,dir_fd=parent_fd)
                except OSError: pass
                try: os.close(parent_fd)
                except OSError: pass
            raise
    else:
        pure_paths=[pure for pure,_ in resolved]
        campaign_parts=pure_paths[0].parts[:4]
        if len(campaign_parts)!=4 or campaign_parts[:3]!=('data','optimization','mot_2d') or any(p.parts[:4]!=campaign_parts for p in pure_paths): raise ValueError()
        parent_fd=directory_fd(campaign_parts[:-1],create=True)
        final_name=campaign_parts[-1]
        try: os.stat(final_name,dir_fd=parent_fd,follow_symlinks=False); raise FileExistsError()
        except FileNotFoundError: pass
        stage_name='.zeus-campaign-'+secrets.token_hex(16); os.mkdir(stage_name,0o700,dir_fd=parent_fd)
        stage_fd=os.open(stage_name,os.O_RDONLY|DIRECTORY|NOFOLLOW,dir_fd=parent_fd)
        try:
            received=receive(resolved,stage_fd,campaign_parts)
            for pure,(file_parent_fd,temporary,target_name,digest) in received.items():
                os.rename(temporary,target_name,src_dir_fd=file_parent_fd,dst_dir_fd=file_parent_fd); os.close(file_parent_fd)
            if not checkout_matches(): raise CheckoutMismatch()
            import ctypes,errno
            libc=ctypes.CDLL(None,use_errno=True)
            renameat2=getattr(libc,'renameat2',None)
            if renameat2 is None: raise RuntimeError('atomic no-replace rename unavailable')
            renameat2.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
            renameat2.restype=ctypes.c_int
            if renameat2(parent_fd,os.fsencode(stage_name),parent_fd,os.fsencode(final_name),1)!=0:
                failure=ctypes.get_errno()
                if failure==errno.EEXIST: raise FileExistsError()
                raise OSError(failure,'renameat2 failed')
        except Exception:
            try: remove_tree(parent_fd,stage_name)
            except OSError: pass
            raise
        finally:
            os.close(stage_fd); os.close(parent_fd)
    print(json.dumps({'ok':True}))
except FileExistsError: print(json.dumps({'error':'target_exists'})); raise SystemExit(23)
except CheckoutMismatch: print(json.dumps({'error':'remote_checkout_mismatch'})); raise SystemExit(25)
except Exception: print(json.dumps({'error':'remote_write_failed'})); raise SystemExit(24)
'''


class PinnedSshZeusPreparationTransport:
    """SSH adapter with a fixed host, fixed options and a fixed remote receiver."""

    def __init__(self, repository_root: Path, ssh_executable: Path, profile: ZeusProfile, expected_commit: str, *, timeout: float = 120):
        self.root = repository_root.resolve(strict=True)
        self.ssh = ssh_executable.resolve(strict=True)
        self.profile = profile
        if not COMMIT_RE.fullmatch(expected_commit):
            raise ValueError("The expected commit is invalid.")
        self.expected_commit = expected_commit
        self.timeout = timeout
        if not self.ssh.is_file() or not os.access(self.ssh, os.X_OK) or self.root in self.ssh.parents:
            raise ValueError("The trusted SSH executable is unavailable.")
        self.runner = PinnedSshRunner(
            PinnedSshPolicy.transfer(self.root, self.ssh, timeout=self.timeout)
        )

    def _run(self, operation: str, paths: tuple[str, ...], payload: bytes = b"") -> dict[str, object]:
        if len(payload) > MAX_TRANSFER_BYTES:
            raise ZeusPreparationError("transfer_too_large")
        pinned_operation = {
            "inspect": TransferOperation.INSPECT,
            "inputs": TransferOperation.INPUTS,
            "campaign": TransferOperation.CAMPAIGN,
        }.get(operation)
        if pinned_operation is None:
            raise ZeusPreparationError("remote_response_invalid")
        returncode, stdout, stderr_bytes = self.runner.transfer(
            pinned_operation,
            self.profile,
            paths,
            self.expected_commit,
            payload,
        )
        stderr = stderr_bytes.decode("utf-8", "replace").lower()
        if returncode and not stdout.strip():
            if "host key verification failed" in stderr or "remote host identification has changed" in stderr:
                raise ZeusPreparationError("zeus_host_key_untrusted")
            if "permission denied" in stderr or "authentication" in stderr:
                raise ZeusPreparationError("zeus_authentication_required")
            if "timed out" in stderr:
                raise ZeusPreparationError("zeus_timeout")
            if any(marker in stderr for marker in ("could not resolve hostname", "connection refused", "no route to host")):
                raise ZeusPreparationError("zeus_unreachable")
        try:
            response = json.loads(stdout.decode("utf-8", "strict"))
        except (UnicodeError, json.JSONDecodeError):
            raise ZeusPreparationError("remote_response_invalid") from None
        if not isinstance(response, dict):
            raise ZeusPreparationError("remote_response_invalid")
        if returncode or response.get("error"):
            code = response.get("error")
            if code not in {"remote_project_missing", "invalid_request", "remote_check_failed", "target_exists", "remote_write_failed"}:
                code = "zeus_transfer_failed"
            raise ZeusPreparationError(str(code))
        return response

    def inspect(self, paths: tuple[str, ...]) -> RemoteSnapshot:
        response = self._run("inspect", paths)
        artifacts = response.get("artifacts")
        if set(response) != {"git_commit", "clean", "artifacts"} or not isinstance(artifacts, dict):
            raise ZeusPreparationError("remote_response_invalid")
        return RemoteSnapshot(str(response["git_commit"]), response["clean"] is True, artifacts)

    @staticmethod
    def _payload(files: Mapping[str, tuple[Path, str, int]]) -> bytes:
        payload = bytearray()
        for path, expected_digest, expected_size in files.values():
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
            try:
                metadata = os.fstat(fd)
                if not stat_module.S_ISREG(metadata.st_mode):
                    raise ZeusPreparationError("local_files_changed")
                contents = bytearray()
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk: break
                    contents.extend(chunk)
                    if len(contents) > MAX_TRANSFER_BYTES: raise ZeusPreparationError("transfer_too_large")
            finally:
                os.close(fd)
            size = len(contents)
            observed = hashlib.sha256(contents).hexdigest()
            if size != expected_size or metadata.st_size != expected_size or observed != expected_digest:
                raise ZeusPreparationError("local_files_changed")
            if size > MAX_TRANSFER_BYTES or len(payload) + 72 + size > MAX_TRANSFER_BYTES:
                raise ZeusPreparationError("transfer_too_large")
            payload.extend(struct.pack("!Q", size)); payload.extend(expected_digest.encode("ascii")); payload.extend(contents)
        return bytes(payload)

    def upload_missing_inputs(self, files: Mapping[str, tuple[Path, str, int]], expected_commit: str) -> None:
        if expected_commit != self.expected_commit: raise ZeusPreparationError("remote_checkout_mismatch")
        paths = tuple(files)
        self._run("inputs", paths, self._payload(files))

    def publish_campaign_atomic(self, files: Mapping[str, tuple[Path, str, int]], expected_commit: str) -> None:
        if expected_commit != self.expected_commit: raise ZeusPreparationError("remote_checkout_mismatch")
        paths = tuple(files)
        self._run("campaign", paths, self._payload(files))


class ZeusPreparationCoordinator:
    """Resolve opaque campaign ids and expose the stable HTTP-facing schema."""

    def __init__(
        self,
        repository_root: Path,
        ssh_executable: Path,
        git_executable: Path,
        *,
        clock=time.time,
        token_factory=None,
    ):
        self.root = repository_root.resolve(strict=True)
        self.ssh = ssh_executable.resolve(strict=True)
        self.git = git_executable.resolve(strict=True)
        self.clock = clock
        self.token_factory = token_factory
        self._services = PreviewRegistry[
            tuple[ZeusPreparationService, PreparationPreview, str, dict[str, object]]
        ](clock=clock)
        if not self.git.is_file() or not os.access(self.git, os.X_OK) or self.root in self.git.parents:
            raise ValueError("The trusted Git executable is unavailable.")

    def _local_revision(self) -> tuple[str, bool]:
        environment = {
            "PATH": str(self.git.parent), "HOME": str(Path.home()), "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat",
        }
        def run(arguments: list[str]) -> bytes:
            try:
                result = subprocess.run(
                    [str(self.git), *arguments], cwd=self.root, env=environment,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    shell=False, close_fds=True, timeout=10, check=False,
                )
            except subprocess.TimeoutExpired:
                raise ZeusPreparationError("local_repository_unavailable") from None
            if result.returncode or len(result.stdout) > 1024 * 1024 or len(result.stderr) > 65536:
                raise ZeusPreparationError("local_repository_unavailable")
            return result.stdout
        try:
            commit = run(["rev-parse", "--verify", "HEAD^{commit}"]).decode("ascii").strip()
            status = run(["status", "--porcelain=v1", "--untracked-files=no"])
        except UnicodeError:
            raise ZeusPreparationError("local_repository_unavailable") from None
        if not COMMIT_RE.fullmatch(commit):
            raise ZeusPreparationError("local_repository_unavailable")
        return commit, not bool(status)

    def preview(self, request: Mapping[str, object], *, session_id: str) -> dict[str, object]:
        if set(request) != {"campaign_id", "username", "project_directory"}:
            raise ZeusPreparationError("request_invalid")
        campaign_id = request.get("campaign_id")
        if not isinstance(campaign_id, str):
            raise ZeusPreparationError("request_invalid")
        try:
            profile = ZeusProfile.parse({
                "username": request.get("username"),
                "project_directory": request.get("project_directory"),
            })
        except ValueError as error:
            raise ZeusPreparationError("profile_invalid") from error
        entry = build_registry(self.root).get(campaign_id)
        if entry is None or entry.family != "mot_2d":
            raise ZeusPreparationError("campaign_not_found")
        manifest = _load_manifest(entry.manifest)
        provenance = manifest.get("provenance")
        expected_commit = provenance.get("git_commit") if isinstance(provenance, dict) else None
        local_commit, clean = self._local_revision()
        if not clean or local_commit != expected_commit:
            raise ZeusPreparationError("local_checkout_mismatch")
        transport = PinnedSshZeusPreparationTransport(self.root, self.ssh, profile, expected_commit)
        service = ZeusPreparationService(
            self.root,
            transport,
            clock=self.clock,
            token_factory=self.token_factory,
        )
        preview = service.preview(entry.manifest.parent, session_id=session_id)
        manifest_name = manifest.get("name")
        if not isinstance(manifest_name, str):
            raise ZeusPreparationError("campaign_manifest_invalid")
        destination = {
            "host": ZEUS_HOST,
            "project_directory": profile.project_directory,
            "campaign_directory": f"{profile.project_directory}/{preview.campaign}",
        }
        response = {
            "preview_token": preview.token,
            "expires_in_seconds": TOKEN_LIFETIME_SECONDS,
            "campaign": {"id": campaign_id, "name": manifest_name, "path": preview.campaign, "git_commit": preview.git_commit},
            "destination": destination,
            "artifacts": {
                "ensemble_count": 35, "total_count": len(preview.files),
                "missing_count": sum(item.action == "upload" for item in preview.files),
                "identical_count": sum(item.action == "reuse" for item in preview.files),
                "total_bytes": sum(item.size for item in preview.files),
                "missing_bytes": sum(item.size for item in preview.files if item.action == "upload"),
            },
            "effects": {"copy_missing_only": True, "overwrite_existing": False, "submit_jobs": False, "run_simulation": False},
        }
        try:
            self._services.put(
                preview.token,
                (service, preview, campaign_id, destination),
                expires_at=preview.expires_at,
                capacity=MAX_PENDING_PREVIEWS,
            )
        except OverflowError as error:
            raise ZeusPreparationError("too_many_pending_previews") from error
        return response

    def confirm(self, request: Mapping[str, object], *, session_id: str) -> dict[str, object]:
        if set(request) != {"preview_token"} or not isinstance(request.get("preview_token"), str):
            raise ZeusPreparationError("request_invalid")
        token = request["preview_token"]
        record = self._services.get(token)
        if record is None:
            raise ZeusPreparationError("confirmation_invalid")
        stored = record.value
        service, preview, campaign_id, destination = stored
        local_commit, clean = self._local_revision()
        if not clean or local_commit != preview.git_commit:
            raise ZeusPreparationError("local_checkout_mismatch")
        result = service.confirm(token, session_id=session_id)
        return {
            "status": "prepared", "campaign_id": campaign_id,
            "destination": destination["campaign_directory"],
            "transferred_count": result.uploaded_count,
            "reused_identical_count": result.reused_count,
            "bytes_transferred": result.bytes_transferred,
            "submitted_to_zeus": False, "simulation_started": False,
        }


@dataclass(frozen=True)
class FilePlan:
    path: str
    sha256: str
    size: int
    action: str

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size, "action": self.action}


@dataclass(frozen=True)
class PreparationPreview:
    token: str
    campaign: str
    git_commit: str
    files: tuple[FilePlan, ...]
    already_prepared: bool
    expires_at: float

    def to_dict(self) -> dict[str, object]:
        return {
            "token": self.token,
            "campaign": self.campaign,
            "git_commit": self.git_commit,
            "files": [item.to_dict() for item in self.files],
            "already_prepared": self.already_prepared,
            "upload_count": sum(item.action == "upload" for item in self.files),
            "reuse_count": sum(item.action == "reuse" for item in self.files),
            "upload_bytes": sum(item.size for item in self.files if item.action == "upload"),
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class PreparationResult:
    campaign: str
    status: str
    uploaded_count: int
    reused_count: int
    bytes_transferred: int

    def to_dict(self) -> dict[str, object]:
        return {
            "campaign": self.campaign, "status": self.status,
            "uploaded_count": self.uploaded_count, "reused_count": self.reused_count,
            "bytes_transferred": self.bytes_transferred,
            "job_submitted": False,
        }


@dataclass
class _Pending:
    session_id: str
    campaign_root: Path
    expected: dict[str, tuple[Path, str, int, str]]
    preview: PreparationPreview
    result: PreparationResult | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, object]:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ZeusPreparationError("campaign_manifest_invalid") from error
    if not isinstance(value, dict):
        raise ZeusPreparationError("campaign_manifest_invalid")
    return value


@dataclass(frozen=True)
class CampaignArtifactPlan:
    """Canonical local artifacts and revision bound to one portable campaign."""

    campaign_root: Path
    commit: str
    files: Mapping[str, tuple[Path, str, int, str]]


class CampaignArtifactPlanner:
    """Validate and enumerate the exact files safe to transfer to Zeus."""

    def __init__(self, repository_root: Path):
        self.root = repository_root.resolve(strict=True)

    def plan(self, campaign: Path) -> CampaignArtifactPlan:
        try:
            campaign_identity = canonical_repo_relative(
                self.root, campaign, allowed_root=CAMPAIGN_ROOT, require="dir",
            )
        except ValueError as error:
            raise ZeusPreparationError("campaign_path_untrusted") from error
        manifest_path = campaign / "campaign.json"
        smoke_path = campaign / "jobs" / "01_smoke.pbs"
        manifest = _load_manifest(manifest_path)
        trusted, _ = modern_contract(manifest, self.root)
        if not trusted or manifest.get("kind") != "mot_2d_s0_campaign" or manifest.get("stage") != "smoke":
            raise ZeusPreparationError("campaign_not_portable_smoke")
        provenance = manifest.get("provenance")
        commit = provenance.get("git_commit") if isinstance(provenance, dict) else None
        if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
            raise ZeusPreparationError("campaign_commit_invalid")
        try:
            smoke_path = resolve_repo_relative(
                self.root, f"{campaign_identity}/jobs/01_smoke.pbs",
                allowed_root=CAMPAIGN_ROOT, require="file",
            )
        except ValueError as error:
            raise ZeusPreparationError("campaign_smoke_job_invalid") from error
        selected: dict[str, tuple[Path, str, int, str]] = {}
        input_records = manifest.get("input_ensembles")
        if not isinstance(input_records, dict):
            raise ZeusPreparationError("campaign_inputs_invalid")
        seen_seeds: set[int] = set()
        for records in input_records.values():
            if not isinstance(records, list):
                raise ZeusPreparationError("campaign_inputs_invalid")
            for record in records:
                if not isinstance(record, dict) or not isinstance(record.get("zeeman_seed"), int):
                    raise ZeusPreparationError("campaign_inputs_invalid")
                seed = record["zeeman_seed"]
                if seed in seen_seeds:
                    raise ZeusPreparationError("campaign_inputs_invalid")
                seen_seeds.add(seed)
                for key, hash_key in (("path", "sha256"), ("metadata_path", "metadata_sha256")):
                    identity, expected_hash = record.get(key), record.get(hash_key)
                    if not isinstance(identity, str) or not isinstance(expected_hash, str):
                        raise ZeusPreparationError("campaign_inputs_invalid")
                    try:
                        local = resolve_repo_relative(self.root, identity, allowed_root=INPUT_ROOT, require="file")
                    except ValueError as error:
                        raise ZeusPreparationError("campaign_inputs_invalid") from error
                    if _sha256(local) != expected_hash:
                        raise ZeusPreparationError("campaign_inputs_changed")
                    selected[identity] = (local, expected_hash, local.stat().st_size, "input")
        if len(seen_seeds) != 35 or len(selected) != 70:
            raise ZeusPreparationError("campaign_inputs_invalid")
        for local in (manifest_path, smoke_path):
            identity = canonical_repo_relative(self.root, local, allowed_root=CAMPAIGN_ROOT, require="file")
            selected[identity] = (local, _sha256(local), local.stat().st_size, "campaign")
        return CampaignArtifactPlan(campaign, commit, MappingProxyType(selected))


class ZeusPreparationService:
    """Create session-bound previews and confirm exactly their reviewed plan."""

    def __init__(
        self, repository_root: Path, transport: ZeusPreparationTransport, *,
        clock=time.time, token_lifetime: float = TOKEN_LIFETIME_SECONDS,
        token_factory=None,
    ):
        self.root = repository_root.resolve(strict=True)
        self.transport = transport
        self.clock = clock
        self.token_lifetime = token_lifetime
        self._previews = PreviewRegistry[_Pending](
            clock=clock,
            token_factory=token_factory,
        )
        self._confirm_lock = threading.Lock()

    def _campaign_files(self, campaign: Path) -> tuple[dict[str, tuple[Path, str, int, str]], str]:
        plan = CampaignArtifactPlanner(self.root).plan(campaign)
        return dict(plan.files), plan.commit

    @staticmethod
    def _validate_snapshot(snapshot: RemoteSnapshot, commit: str, expected: Mapping[str, tuple[Path, str, int, str]]) -> None:
        if snapshot.git_commit != commit or snapshot.clean is not True:
            raise ZeusPreparationError("remote_checkout_mismatch")
        if any(not isinstance(key, str) for key in snapshot.artifacts) or any(
            not isinstance(value, str) or not SHA256_RE.fullmatch(value)
            for value in snapshot.artifacts.values()
        ):
            raise ZeusPreparationError("remote_response_invalid")
        unknown = set(snapshot.artifacts) - set(expected)
        if unknown:
            raise ZeusPreparationError("remote_response_invalid")
        for path, digest in snapshot.artifacts.items():
            if digest != expected[path][1]:
                kind = expected[path][3]
                raise ZeusPreparationError(f"remote_{kind}_conflict")

    def preview(self, campaign: Path, *, session_id: str) -> PreparationPreview:
        if not session_id or len(session_id) > 256:
            raise ZeusPreparationError("session_invalid")
        expected, commit = self._campaign_files(campaign.resolve())
        snapshot = self.transport.inspect(tuple(sorted(expected)))
        self._validate_snapshot(snapshot, commit, expected)
        campaign_paths = {path for path, item in expected.items() if item[3] == "campaign"}
        present_campaign = campaign_paths & set(snapshot.artifacts)
        if present_campaign and present_campaign != campaign_paths:
            raise ZeusPreparationError("remote_campaign_conflict")
        already = present_campaign == campaign_paths
        files = tuple(
            FilePlan(path, item[1], item[2], "reuse" if path in snapshot.artifacts else "upload")
            for path, item in sorted(expected.items())
        )
        expires = self.clock() + self.token_lifetime
        preview_holder: list[PreparationPreview] = []

        def pending_for(token: str) -> _Pending:
            preview = PreparationPreview(
                token,
                canonical_repo_relative(
                    self.root,
                    campaign,
                    allowed_root=CAMPAIGN_ROOT,
                    require="dir",
                ),
                commit,
                files,
                already,
                expires,
            )
            preview_holder.append(preview)
            return _Pending(session_id, campaign.resolve(), expected, preview)

        try:
            self._previews.add_factory(
                pending_for,
                expires_at=expires,
                capacity=MAX_PENDING_PREVIEWS,
            )
        except OverflowError as error:
            raise ZeusPreparationError("too_many_pending_previews") from error
        return preview_holder[0]

    def confirm(self, token: str, *, session_id: str) -> PreparationResult:
        # Confirmation is rare and serializing it closes same-token and
        # cross-token publication races without relying on a remote lock.
        with self._confirm_lock:
            return self._confirm(token, session_id=session_id)

    def _confirm(self, token: str, *, session_id: str) -> PreparationResult:
        record = self._previews.get(token)
        pending = record.value if record is not None else None
        if pending is None or not secrets.compare_digest(pending.session_id, session_id):
            raise ZeusPreparationError("confirmation_invalid")
        if pending.result is not None:
            return pending.result
        if self.clock() > pending.preview.expires_at:
            self._previews.pop(token)
            raise ZeusPreparationError("confirmation_expired")
        # Rebuild from disk: confirmation cannot approve bytes changed after preview.
        current, commit = self._campaign_files(pending.campaign_root)
        if commit != pending.preview.git_commit or {
            path: (item[1], item[2], item[3]) for path, item in current.items()
        } != {path: (item[1], item[2], item[3]) for path, item in pending.expected.items()}:
            raise ZeusPreparationError("local_files_changed")
        snapshot = self.transport.inspect(tuple(sorted(current)))
        self._validate_snapshot(snapshot, commit, current)
        campaign = {p: (item[0], item[1], item[2]) for p, item in current.items() if item[3] == "campaign"}
        inputs = {p: (item[0], item[1], item[2]) for p, item in current.items() if item[3] == "input" and p not in snapshot.artifacts}
        campaign_present = set(campaign).issubset(snapshot.artifacts)
        if set(campaign) & set(snapshot.artifacts) and not campaign_present:
            raise ZeusPreparationError("remote_campaign_conflict")
        if inputs:
            self.transport.upload_missing_inputs(inputs, commit)
            after_inputs = self.transport.inspect(tuple(sorted(current)))
            self._validate_snapshot(after_inputs, commit, current)
            required_inputs = {path for path, item in current.items() if item[3] == "input"}
            if not required_inputs.issubset(after_inputs.artifacts):
                raise ZeusPreparationError("remote_inputs_incomplete")
        if not campaign_present:
            self.transport.publish_campaign_atomic(campaign, commit)
            completed = self.transport.inspect(tuple(sorted(current)))
            self._validate_snapshot(completed, commit, current)
            if set(completed.artifacts) != set(current):
                raise ZeusPreparationError("remote_campaign_incomplete")
        result = PreparationResult(
            pending.preview.campaign, "already_prepared" if campaign_present and not inputs else "prepared",
            len(inputs) + (0 if campaign_present else len(campaign)),
            len(current) - len(inputs) - (0 if campaign_present else len(campaign)),
            sum(current[path][2] for path in inputs) + (0 if campaign_present else sum(current[path][2] for path in campaign)),
        )
        # A server calls confirm serially per token; retain the result to make
        # transport retries from the same session idempotent.
        pending.result = result
        return result
