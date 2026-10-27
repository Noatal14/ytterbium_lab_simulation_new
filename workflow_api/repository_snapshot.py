"""Narrow, read-only Git provenance provider for confirmed local creation."""

from __future__ import annotations

from workflow_api.platform_io import os
import re
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from workflow_api.mot_2d_spec import RELEVANT_FILES

HEAD_RE = re.compile(r"^[0-9a-f]{40}$")
PATHS = (*RELEVANT_FILES, "lab_setup")

# Exact clean-worktree ledger for individual Zeeman-run admission and future
# execution.  Keep this explicit: a new runtime or provenance consumer must be
# reviewed and added here rather than silently inheriting an entire directory.
ZEEMAN_RELEVANT_FILES = (
    "config.py",
    "pyproject.toml",
    "requirements.txt",
    "simulations/zeeman.py",
    "simulations/thermal_beam.py",
    "lab_setup/_3d_mot_mag_field.py",
    "lab_setup/atom_species.py",
    "lab_setup/config_builder.py",
    "lab_setup/gravity.py",
    "lab_setup/laser_setup_2d_mot.py",
    "lab_setup/laser_setup_3d.py",
    "lab_setup/mag_field_2d_mot.py",
    "lab_setup/mag_field_Zeeman.py",
    "lab_setup/numerical_policy.py",
    "lab_setup/mot_2d_operating_specification.py",
    "lab_setup/physical_specification.py",
    "lab_setup/specifications/laboratory_physical_v1.json",
    "lab_setup/specifications/laboratory_physical_v2.json",
    "lab_setup/specifications/zeeman_model_conventions_v1.json",
    "lab_setup/zeeman_operating_specification.py",
    "lab_setup/specifications/zeeman_operating_v1.json",
    "lab_setup/specifications/mot_2d_operating_v1.json",
    "lab_setup/specifications/numerical_policy_v2.json",
    "lab_setup/strict_specification.py",
    "lab_setup/zeeman_laser_setup.py",
    "lab_setup/zones.py",
    "utils/RK4StCustom.py",
    "utils/ScipyIVP_3DCustom.py",
    "utils/data_paths.py",
    "utils/file_helpers.py",
    "utils/simulation_helpers.py",
    "workflow_api/preview_registry.py",
    "workflow_api/pinned_ssh.py",
    "workflow_api/repository_snapshot.py",
    "workflow_api/repository_paths.py",
    "workflow_api/run_discovery.py",
    "workflow_api/platform_io.py",
    "workflow_api/run_records.py",
    "workflow_api/individual_limits.py",
    "workflow_api/run_results.py",
    "workflow_api/run_metrics.py",
    "workflow_api/run_execution.py",
    "workflow_api/run_specification.py",
    "workflow_api/specifications/individual_run_v1.json",
    "workflow_api/specifications/zeeman_individual_v1.json",
    "workflow_api/zeeman_run_creation.py",
    "workflow_api/zeeman_local_execution.py",
    "workflow_api/zeeman_zeus_execution.py",
    "workflow_api/zeeman_zeus_remote.py",
    "workflow_api/zeeman_zeus_worker.py",
    "workflow_api/zeus_snapshot.py",
    "workflow_api/zeeman_run_plan.py",
    "workflow_api/zeeman_run_specification.py",
)

# Exact clean-worktree ledger for individual 2D-MOT admission.  Input particle
# files are not Git inputs: the source catalog independently re-attests every
# constituent artifact at preview and confirmation time.
MOT_2D_INDIVIDUAL_RELEVANT_FILES = (
    "config.py",
    "pyproject.toml",
    "requirements.txt",
    "simulations/mot_2d.py",
    "lab_setup/_3d_mot_mag_field.py",
    "lab_setup/atom_species.py",
    "lab_setup/config_builder.py",
    "lab_setup/gravity.py",
    "lab_setup/laser_setup_2d_mot.py",
    "lab_setup/laser_setup_3d.py",
    "lab_setup/mag_field_2d_mot.py",
    "lab_setup/mag_field_Zeeman.py",
    "lab_setup/numerical_policy.py",
    "lab_setup/mot_2d_operating_specification.py",
    "lab_setup/physical_specification.py",
    "lab_setup/specifications/laboratory_physical_v1.json",
    "lab_setup/specifications/laboratory_physical_v2.json",
    "lab_setup/specifications/zeeman_model_conventions_v1.json",
    "lab_setup/zeeman_operating_specification.py",
    "lab_setup/specifications/zeeman_operating_v1.json",
    "lab_setup/specifications/mot_2d_operating_v1.json",
    "lab_setup/specifications/numerical_policy_v2.json",
    "lab_setup/strict_specification.py",
    "lab_setup/zeeman_laser_setup.py",
    "lab_setup/zones.py",
    "utils/RK4StHybridCustom.py",
    "utils/RK4StCustom.py",
    "utils/ScipyIVP_3DCustom.py",
    "utils/data_paths.py",
    "utils/file_helpers.py",
    "utils/simulation_helpers.py",
    "workflow_api/mot_2d_individual_sources.py",
    "workflow_api/mot_2d_run_creation.py",
    "workflow_api/mot_2d_local_execution.py",
    "workflow_api/mot_2d_zeus_execution.py",
    "workflow_api/mot_2d_zeus_remote.py",
    "workflow_api/mot_2d_zeus_worker.py",
    "workflow_api/mot_2d_run_plan.py",
    "workflow_api/mot_2d_run_specification.py",
    "workflow_api/mot_2d_sources.py",
    "workflow_api/preview_registry.py",
    "workflow_api/pinned_ssh.py",
    "workflow_api/repository_snapshot.py",
    "workflow_api/repository_paths.py",
    "workflow_api/run_discovery.py",
    "workflow_api/run_execution.py",
    "workflow_api/platform_io.py",
    "workflow_api/run_records.py",
    "workflow_api/individual_limits.py",
    "workflow_api/run_results.py",
    "workflow_api/run_metrics.py",
    "workflow_api/run_specification.py",
    "workflow_api/specifications/individual_run_v1.json",
    "workflow_api/specifications/mot_2d_individual_v1.json",
    "workflow_api/zeeman_local_execution.py",
)

# Exact clean-worktree ledger for individual 3D-MOT admission.  Particle-state
# inputs are independently re-attested by the source catalog.
MOT_3D_INDIVIDUAL_RELEVANT_FILES = (
    "config.py",
    "pyproject.toml",
    "requirements.txt",
    "simulations/mot_3d.py",
    "studies/mot_3d_campaign.py",
    "studies/mot_3d/discovery/optimize.py",
    "utils/optuna_replay.py",
    "studies/mot_3d/analysis/retention.py",
    "lab_setup/_3d_mot_mag_field.py",
    "lab_setup/atom_species.py",
    "lab_setup/config_builder.py",
    "lab_setup/gravity.py",
    "lab_setup/laser_setup_3d.py",
    "lab_setup/mot_3d_timestep_policy.py",
    "lab_setup/numerical_policy.py",
    "lab_setup/physical_specification.py",
    "lab_setup/specifications/laboratory_physical_v1.json",
    "lab_setup/specifications/laboratory_physical_v2.json",
    "lab_setup/specifications/mot_3d_timestep_policy_v2.json",
    "lab_setup/specifications/numerical_policy_v2.json",
    "lab_setup/strict_specification.py",
    "utils/RK4StHybridCustom.py",
    "utils/data_paths.py",
    "utils/file_helpers.py",
    "utils/simulation_helpers.py",
    "workflow_api/mot_3d_individual_sources.py",
    "workflow_api/mot_2d_individual_sources.py",
    "workflow_api/mot_2d_local_execution.py",
    "workflow_api/mot_3d_local_execution.py",
    "workflow_api/mot_3d_zeus_execution.py",
    "workflow_api/mot_3d_zeus_remote.py",
    "workflow_api/mot_3d_zeus_worker.py",
    "workflow_api/mot_3d_run_creation.py",
    "workflow_api/mot_3d_run_plan.py",
    "workflow_api/mot_3d_run_specification.py",
    "workflow_api/preview_registry.py",
    "workflow_api/pinned_ssh.py",
    "workflow_api/repository_snapshot.py",
    "workflow_api/run_discovery.py",
    "workflow_api/run_execution.py",
    "workflow_api/platform_io.py",
    "workflow_api/run_records.py",
    "workflow_api/individual_limits.py",
    "workflow_api/run_results.py",
    "workflow_api/run_metrics.py",
    "workflow_api/run_specification.py",
    "workflow_api/specifications/individual_run_v1.json",
    "workflow_api/specifications/mot_3d_individual_v1.json",
    "workflow_api/zeeman_local_execution.py",
)


@dataclass(frozen=True)
class RepositorySnapshot:
    commit: str
    provider: str = "pinned-git-read-only-v1"


class RepositoryFilesChangedError(RuntimeError):
    """Raised when reviewed runtime inputs are not represented by HEAD."""


class RepositorySnapshotProvider:
    def __init__(
        self,
        repository_root: Path,
        git_executable: Path,
        *,
        audited_paths: tuple[str, ...] = PATHS,
    ):
        self.root = repository_root.resolve(); self.git = git_executable.resolve()
        if not self.git.is_file() or not os.access(self.git, os.X_OK):
            raise ValueError("The trusted Git executable is unavailable.")
        if self.root in self.git.parents:
            raise ValueError("The Git executable cannot come from the repository.")
        if (
            not isinstance(audited_paths, tuple)
            or not audited_paths
            or len(audited_paths) != len(set(audited_paths))
            or any(
                not isinstance(path, str)
                or not path
                or path.startswith("/")
                or "\\" in path
                or any(part in {"", ".", ".."} for part in Path(path).parts)
                for path in audited_paths
            )
        ):
            raise ValueError("Repository audit paths are invalid.")
        self.paths = audited_paths
        self._reject_unsafe_repository_configuration()

    def _reject_unsafe_repository_configuration(self) -> None:
        """Reject repository-local settings that can execute helper programs."""
        marker = self.root / ".git"
        if marker.is_symlink():
            raise ValueError("A regular local Git directory is required.")
        if marker.is_dir():
            git_directory = marker.resolve()
            common_directory = git_directory
        elif marker.is_file() and marker.stat().st_size <= 4096:
            line = marker.read_text(encoding="utf-8").strip()
            if not line.startswith("gitdir: "):
                raise ValueError("A regular local Git directory is required.")
            git_directory = Path(line[8:]).resolve()
            if not git_directory.is_dir() or git_directory.parent.name != "worktrees":
                raise ValueError("The Git worktree metadata is invalid.")
            common_directory = git_directory.parent.parent
        else:
            raise ValueError("A regular local Git directory is required.")
        candidates = [
            common_directory / "config", git_directory / "config.worktree",
            common_directory / "info/attributes", self.root / ".gitattributes",
        ]
        nested_attributes = []
        for base in (self.root / "lab_setup", self.root / "studies", self.root / "simulations", self.root / "utils"):
            if base.is_dir():
                nested_attributes.extend(list(base.glob("**/.gitattributes"))[:64])
        if len(nested_attributes) >= 64:
            raise ValueError("Repository attributes could not be bounded safely.")
        candidates.extend(nested_attributes)
        unsafe = (
            "[include", "[filter ", "fsmonitor", "hookspath", "external",
            "textconv", "filter=", "diff=", "working-tree-encoding=",
        )
        for path in candidates:
            if not path.exists():
                continue
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
                raise ValueError("Repository configuration could not be verified safely.")
            content = path.read_text(encoding="utf-8", errors="strict").lower()
            if any(marker in content for marker in unsafe):
                raise ValueError("Repository configuration enables unsupported helpers.")

    def _run(self, arguments: tuple[str, ...]) -> bytes:
        with tempfile.TemporaryDirectory(prefix="mot-ui-git-") as safe_home:
            env = {
                "PATH": str(self.git.parent), "HOME": safe_home,
                "XDG_CONFIG_HOME": safe_home, "LC_ALL": "C",
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat", "PAGER": "cat",
                "GIT_CONFIG_COUNT": "4",
                "GIT_CONFIG_KEY_0": "core.fsmonitor", "GIT_CONFIG_VALUE_0": "false",
                "GIT_CONFIG_KEY_1": "core.untrackedCache", "GIT_CONFIG_VALUE_1": "false",
                "GIT_CONFIG_KEY_2": "core.preloadIndex", "GIT_CONFIG_VALUE_2": "false",
                "GIT_CONFIG_KEY_3": "core.hooksPath", "GIT_CONFIG_VALUE_3": safe_home,
            }
            process = subprocess.Popen(
                [str(self.git), *arguments], cwd=self.root, env=env, shell=False,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                close_fds=True,
            )
            output = bytearray(); errors = bytearray(); exceeded = threading.Event()
            def drain(stream: object, limit: int, destination: bytearray) -> None:
                while True:
                    chunk = stream.read(64 * 1024)  # type: ignore[attr-defined]
                    if not chunk: return
                    if len(destination) + len(chunk) > limit:
                        exceeded.set()
                        try: process.kill()
                        except OSError: pass
                        return
                    destination.extend(chunk)
            readers = [
                threading.Thread(target=drain, args=(process.stdout, 1024 * 1024, output), daemon=True),
                threading.Thread(target=drain, args=(process.stderr, 64 * 1024, errors), daemon=True),
            ]
            for reader in readers: reader.start()
            try:
                returncode = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(); exceeded.set(); returncode = process.returncode
            for reader in readers: reader.join(timeout=1)
            if any(reader.is_alive() for reader in readers):
                process.kill(); exceeded.set()
            if exceeded.is_set() or returncode != 0:
                raise RuntimeError("Repository provenance could not be verified safely.")
            return bytes(output)

    def capture(self) -> RepositorySnapshot:
        head = self._run(("rev-parse", "--verify", "HEAD^{commit}" )).decode("ascii").strip()
        if not HEAD_RE.fullmatch(head):
            raise RuntimeError("Repository revision is invalid.")
        status = self._run((
            "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *self.paths,
        ))
        if status:
            raise RepositoryFilesChangedError(
                "Reviewed simulation files contain uncommitted changes."
            )
        return RepositorySnapshot(head)


class ZeemanRepositorySnapshotProvider(RepositorySnapshotProvider):
    """Pinned Git provider scoped to the reviewed Zeeman runtime ledger."""

    def __init__(self, repository_root: Path, git_executable: Path):
        super().__init__(
            repository_root,
            git_executable,
            audited_paths=ZEEMAN_RELEVANT_FILES,
        )


class Mot2DIndividualRepositorySnapshotProvider(RepositorySnapshotProvider):
    """Pinned Git provider scoped to individual 2D-MOT admission/runtime."""

    def __init__(self, repository_root: Path, git_executable: Path):
        super().__init__(
            repository_root,
            git_executable,
            audited_paths=MOT_2D_INDIVIDUAL_RELEVANT_FILES,
        )


class Mot3DIndividualRepositorySnapshotProvider(RepositorySnapshotProvider):
    """Pinned Git provider scoped to individual 3D-MOT admission/runtime."""

    def __init__(self, repository_root: Path, git_executable: Path):
        super().__init__(
            repository_root,
            git_executable,
            audited_paths=MOT_3D_INDIVIDUAL_RELEVANT_FILES,
        )
