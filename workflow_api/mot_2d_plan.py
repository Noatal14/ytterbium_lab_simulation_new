"""Pure canonical plan for a fixed-s0 2D-MOT campaign."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shlex
import shutil
import tempfile
import ctypes
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from workflow_api.mot_2d_sources import inspect_source
from workflow_api.repository_snapshot import RepositorySnapshot
from workflow_api.mot_2d_spec import RELEVANT_FILES, ROLE_SEEDS, build_manifest

SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class CampaignPlan:
    name: str; slug: str; s0_values: tuple[float, ...]; source_id: str
    destination: Path; manifest: dict[str, Any]; files: dict[str, bytes]
    source_fingerprint: str; plan_digest: str; snapshot: RepositorySnapshot
    semantic_fingerprint: str


def physical_model_hash(repository_root: Path) -> tuple[str, list[str]]:
    paths = [repository_root / path for path in RELEVANT_FILES]
    paths.extend(sorted((repository_root / "lab_setup").rglob("*.py")))
    digest = hashlib.sha256(); names: list[str] = []
    for path in paths:
        relative = path.relative_to(repository_root).as_posix()
        digest.update(relative.encode()); digest.update(path.read_bytes()); names.append(relative)
    return digest.hexdigest(), names


def normalize_s0(values: list[Any]) -> tuple[float, ...]:
    if not 1 <= len(values) <= 16:
        raise ValueError("Provide between 1 and 16 fixed s0 values.")
    normalized: list[float] = []
    for raw in values:
        if isinstance(raw, bool): raise ValueError("Every s0 value must be positive and finite.")
        value = float(raw)
        if not math.isfinite(value) or value <= 0: raise ValueError("Every s0 value must be positive and finite.")
        if value not in normalized: normalized.append(value)
    return tuple(normalized)


def render_campaign_files(
    manifest: dict[str, Any], destination: Path, repository_root: Path
) -> dict[str, bytes]:
    """Render the canonical initial files without touching the filesystem."""
    values = manifest["s0_values"]
    try:
        campaign_argument = destination.relative_to(repository_root).as_posix()
    except ValueError as error:
        raise ValueError("Campaign destination must be inside the repository.") from error
    if not campaign_argument.startswith("data/optimization/mot_2d/"):
        raise ValueError("Campaign destination is outside the canonical 2D-MOT location.")
    array = "" if len(values) == 1 else f"#PBS -J 0-{len(values)-1}%1\n"
    scalar = "export PBS_ARRAY_INDEX=0\n" if len(values) == 1 else ""
    commit = manifest["provenance"]["git_commit"]
    pbs = f"""#!/bin/bash
#PBS -N mot2d_smoke
#PBS -q zeus_combined_q
{array}#PBS -l select=1:ncpus=1:mem=64gb
#PBS -l walltime=00:20:00

set -euo pipefail
PROJECT_ROOT="${{HOME}}/ytterbium_lab_simulation_new"
cd -- "${{PROJECT_ROOT}}" || exit 1
module load SPACK/apps
module load gcc/14.1.0
module load python/3.14.2
source "${{HOME}}/venvs/atomsmltr/bin/activate"
{scalar}EXPECTED_COMMIT={shlex.quote(commit)}
ACTUAL_COMMIT=$(git rev-parse HEAD)
if [ "${{ACTUAL_COMMIT}}" != "${{EXPECTED_COMMIT}}" ]; then
  echo "Commit mismatch: expected ${{EXPECTED_COMMIT}}, found ${{ACTUAL_COMMIT}}" >&2
  exit 42
fi
RUN_TMP="/tmp/${{USER}}_mot2d_smoke_${{PBS_JOBID}}_${{PBS_ARRAY_INDEX:-0}}"
mkdir -p "${{RUN_TMP}}"
export TMPDIR="${{RUN_TMP}}" TMP="${{RUN_TMP}}" TEMP="${{RUN_TMP}}"
trap 'rm -rf -- "${{RUN_TMP}}"' EXIT
python -m studies.mot_2d_s0_campaign smoke --campaign {shlex.quote(campaign_argument)} --s0-index $PBS_ARRAY_INDEX
""".encode()
    return {
        "campaign.json": (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
        "jobs/01_smoke.pbs": pbs,
    }


def render_screen_transition(
    manifest: dict[str, Any], destination: Path, repository_root: Path
) -> dict[str, bytes]:
    """Purely render the canonical smoke-to-screen transition artifacts."""
    if manifest.get("kind") != "mot_2d_s0_campaign" or manifest.get("stage") != "smoke":
        raise ValueError("Campaign is not awaiting screening preparation.")
    try:
        campaign_argument = destination.relative_to(repository_root).as_posix()
    except ValueError as error:
        raise ValueError("Campaign destination must be inside the repository.") from error
    if not campaign_argument.startswith("data/optimization/mot_2d/"):
        raise ValueError("Campaign destination is outside the canonical 2D-MOT location.")
    values = manifest.get("s0_values")
    if not isinstance(values, list) or not values:
        raise ValueError("Campaign has no fixed s0 values.")
    tasks = [{"s0": float(value), "worker": worker} for value in values for worker in range(3)]
    commit = manifest["provenance"]["git_commit"]
    task_path = f"{campaign_argument}/screen/tasks.json"
    job_path = f"{campaign_argument}/jobs/02_screen.pbs"
    pbs = f"""#!/bin/bash
#PBS -N mot2d_scree
#PBS -q zeus_combined_q
#PBS -J 0-{len(tasks)-1}%3
#PBS -l select=1:ncpus=200:mem=64gb
#PBS -l walltime=24:00:00

set -euo pipefail
PROJECT_ROOT="${{HOME}}/ytterbium_lab_simulation_new"
cd -- "${{PROJECT_ROOT}}" || exit 1
module load SPACK/apps
module load gcc/14.1.0
module load python/3.14.2
source "${{HOME}}/venvs/atomsmltr/bin/activate"
EXPECTED_COMMIT={shlex.quote(commit)}
ACTUAL_COMMIT=$(git rev-parse HEAD)
if [ "${{ACTUAL_COMMIT}}" != "${{EXPECTED_COMMIT}}" ]; then
  echo "Commit mismatch: expected ${{EXPECTED_COMMIT}}, found ${{ACTUAL_COMMIT}}" >&2
  exit 42
fi
RUN_TMP="/tmp/${{USER}}_mot2d_scree_${{PBS_JOBID}}_${{PBS_ARRAY_INDEX:-0}}"
mkdir -p "${{RUN_TMP}}"
export TMPDIR="${{RUN_TMP}}" TMP="${{RUN_TMP}}" TEMP="${{RUN_TMP}}"
trap 'rm -rf -- "${{RUN_TMP}}"' EXIT
python -m studies.mot_2d_s0_campaign screen-task --campaign {shlex.quote(campaign_argument)} --task-index $PBS_ARRAY_INDEX
""".encode()
    updated = deepcopy(manifest)
    updated["stage"] = "screen"
    updated.setdefault("stages", {})["screen"] = {"tasks": len(tasks), "job_file": job_path}
    return {
        "screen/tasks.json": (json.dumps(tasks, indent=2, sort_keys=True) + "\n").encode(),
        "jobs/02_screen.pbs": pbs,
        "campaign.json": (json.dumps(updated, indent=2, sort_keys=True) + "\n").encode(),
    }


def plan_from_frozen_manifest(
    *, repository_root: Path, destination: Path, manifest: dict[str, Any]
) -> CampaignPlan:
    """Build the same atomic write plan for the canonical CLI and local UI."""
    snapshot = RepositorySnapshot(str(manifest["provenance"]["git_commit"]))
    frozen = [
        row for role in ROLE_SEEDS
        for row in manifest["input_ensembles"][role]
    ]
    source_payload = json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()
    source_fingerprint = hashlib.sha256(source_payload).hexdigest()
    files = render_campaign_files(manifest, destination, repository_root)
    plan_digest = hashlib.sha256(b"".join(name.encode() + b"\0" + data for name, data in sorted(files.items()))).hexdigest()
    semantic = hashlib.sha256(json.dumps({
        "s0": sorted(map(float, manifest["s0_values"])),
        "source": source_fingerprint,
        "model": manifest["provenance"]["physical_model_sha256"],
        "design": manifest["fixed_design"],
    }, sort_keys=True).encode()).hexdigest()
    return CampaignPlan(
        str(manifest["name"]), destination.name, tuple(map(float, manifest["s0_values"])),
        "canonical-cli", destination, manifest, files, source_fingerprint,
        plan_digest, snapshot, semantic,
    )


def build_plan(repository_root: Path, *, name: str, slug: str, s0_values: list[Any], source: dict[str, Any], snapshot: RepositorySnapshot) -> CampaignPlan:
    repository_root = repository_root.resolve(); name = name.strip()
    if not name or len(name) > 120: raise ValueError("Campaign name is required and must be at most 120 characters.")
    if not SLUG.fullmatch(slug): raise ValueError("Campaign folder is invalid.")
    values = normalize_s0(s0_values)
    destination = repository_root / "data/optimization/mot_2d" / slug
    if destination.exists() or destination.is_symlink(): raise FileExistsError("Campaign destination already exists.")
    source_path = repository_root / source["path"]
    frozen = inspect_source(source_path, repository_root, include_records=True)
    if frozen["id"] != source["id"] or frozen["fingerprint"] != source["fingerprint"]:
        raise ValueError("Zeeman source changed after selection.")
    records = frozen.pop("records")
    by_seed = {row["zeeman_seed"]: row for row in records}
    model_hash, hashed_files = physical_model_hash(repository_root)
    manifest = build_manifest(
        name=name, s0_values=list(values), ensemble_directory=source["path"],
        zeeman_profile=frozen["profile"],
        frozen_inputs={role: [by_seed[seed] for seed in seeds] for role, seeds in ROLE_SEEDS.items()},
        git_commit=snapshot.commit, physical_model_sha256=model_hash,
        hashed_files=hashed_files,
    )
    files = render_campaign_files(manifest, destination, repository_root)
    plan_digest = hashlib.sha256(b"".join(name.encode() + b"\0" + data for name, data in sorted(files.items()))).hexdigest()
    semantic = hashlib.sha256(json.dumps({
        "s0": sorted(values), "source": source["fingerprint"],
        "model": model_hash, "design": manifest["fixed_design"],
    }, sort_keys=True).encode()).hexdigest()
    return CampaignPlan(name, slug, values, source["id"], destination, manifest, files, source["fingerprint"], plan_digest, snapshot, semantic)


def materialize(plan: CampaignPlan, precommit_validate: Any | None = None) -> None:
    parent = plan.destination.parent; parent.mkdir(parents=True, exist_ok=True)
    lock_paths = sorted({
        parent / f".{plan.semantic_fingerprint}.creation.lock",
        parent / f".{plan.slug}.destination.lock",
    }, key=lambda path: path.name)
    locks: list[tuple[Path, int]] = []
    temporary: Path | None = None
    try:
        for lock_path in lock_paths:
            descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            locks.append((lock_path, descriptor))
        temporary = Path(tempfile.mkdtemp(prefix=f".{plan.slug}.creating-", dir=parent))
        for relative, content in plan.files.items():
            path = temporary / relative; path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o755 if path.suffix == ".pbs" else 0o644)
            with os.fdopen(descriptor, "wb") as stream: stream.write(content); stream.flush(); os.fsync(stream.fileno())
        for directory in (temporary / "jobs", temporary):
            descriptor = os.open(directory, os.O_RDONLY); os.fsync(descriptor); os.close(descriptor)
        if precommit_validate is not None: precommit_validate(temporary)
        if plan.destination.exists(): raise FileExistsError("Campaign destination already exists.")
        _rename_no_replace(temporary, plan.destination)
        try:
            descriptor = os.open(parent, os.O_RDONLY); os.fsync(descriptor); os.close(descriptor)
        except OSError:
            # Publication already succeeded atomically. A retry must observe
            # the exact published plan rather than reporting a false failure.
            pass
    except Exception:
        if temporary is not None and temporary.exists(): shutil.rmtree(temporary)
        raise
    finally:
        for lock_path, descriptor in reversed(locks):
            os.close(descriptor)
            try: lock_path.unlink()
            except FileNotFoundError: pass


def _rename_no_replace(source: Path, destination: Path) -> None:
    """Atomically publish a directory without ever replacing a destination."""
    library = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source); destination_bytes = os.fsencode(destination)
    if sys.platform == "darwin":
        function = library.renamex_np
        function.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        result = function(source_bytes, destination_bytes, 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        function = library.renameat2
        function.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        result = function(-100, source_bytes, -100, destination_bytes, 1)  # RENAME_NOREPLACE
    else:
        raise RuntimeError("Atomic no-replace publication is unsupported on this platform.")
    if result != 0:
        error = ctypes.get_errno()
        if error in {17, 39, 66}:  # EEXIST / ENOTEMPTY platform variants
            raise FileExistsError("Campaign destination already exists.")
        raise OSError(error, os.strerror(error), str(destination))
