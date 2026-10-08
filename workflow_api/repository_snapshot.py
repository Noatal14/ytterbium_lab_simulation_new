"""Narrow, read-only Git provenance provider for confirmed local creation."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from workflow_api.mot_2d_spec import RELEVANT_FILES

HEAD_RE = re.compile(r"^[0-9a-f]{40}$")
PATHS = (*RELEVANT_FILES, "lab_setup")


@dataclass(frozen=True)
class RepositorySnapshot:
    commit: str
    provider: str = "pinned-git-read-only-v1"


class RepositorySnapshotProvider:
    def __init__(self, repository_root: Path, git_executable: Path):
        self.root = repository_root.resolve(); self.git = git_executable.resolve()
        if not self.git.is_file() or not os.access(self.git, os.X_OK):
            raise ValueError("The trusted Git executable is unavailable.")
        if self.root in self.git.parents:
            raise ValueError("The Git executable cannot come from the repository.")
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
            "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *PATHS,
        ))
        if status:
            raise RuntimeError("Scientific campaign files contain uncommitted changes.")
        return RepositorySnapshot(head)
