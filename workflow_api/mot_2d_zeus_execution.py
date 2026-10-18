"""Guarded scalar Zeus execution for an individual 2D-MOT run."""

from __future__ import annotations

from workflow_api.zeeman_zeus_execution import _target_pbs

import base64
from dataclasses import dataclass
from io import BytesIO
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from workflow_api.mot_2d_local_execution import materialize_frozen_selection
from workflow_api.mot_2d_run_specification import MOT_2D_RUN_SPECIFICATION
from workflow_api.pinned_ssh import PinnedSshPolicy, PinnedSshRunner, ReceiverOperation
from workflow_api.run_execution import WorkerRequest
from workflow_api.run_records import encode_record
from workflow_api.zeeman_zeus_execution import (
    IndividualZeemanZeusCoordinator,
    PinnedSshZeemanTransport,
    RemoteSubmission,
    ZeemanZeusError,
    _OPERATIONS,
    _canonical,
)
from workflow_api.zeus_snapshot import ZeusProfile


Mot2DZeusError = ZeemanZeusError


@dataclass(frozen=True)
class FrozenMot2DZeusPackage:
    run_id: str
    commit: str
    records: Mapping[str, bytes]
    package_sha256: str
    pbs: bytes
    pbs_sha256: str
    submission_key: str
    username: str
    project_directory: str
    selected_states: bytes
    selected_states_sha256: str
    selection_sha256: str
    family: str = "mot_2d"


def _render_pbs(run: Mapping[str, Any], package_sha256: str, project_directory: str | None = None) -> bytes:
    workers = MOT_2D_RUN_SPECIFICATION["workers_by_execution_mode"]["zeus"]
    text = f"""#!/bin/bash
#PBS -N i2_{run['run_id'][:24]}
#PBS -q zeus_combined_q
#PBS -l select=1:ncpus={workers}:mem=64gb
#PBS -l walltime=08:00:00
set -euo pipefail
cd /home/${{USER}}/ytterbium_lab_simulation_new
test "$(git rev-parse HEAD)" = "{run['git_revision']}"
module load SPACK/apps
module load gcc/14.1.0
module load python/3.14.2
source "${{HOME}}/venvs/atomsmltr/bin/activate"
python -m workflow_api.mot_2d_zeus_worker --package ".workflow/individual-mot-2d/{package_sha256}/package.json" --package-sha256 "{package_sha256}"
"""
    return _target_pbs(text, project_directory)


def build_frozen_mot_2d_package(
    repository_root: Path,
    records: Mapping[str, Mapping[str, Any]],
    profile: ZeusProfile,
    *,
    require_configured: bool = True,
) -> FrozenMot2DZeusPackage:
    if set(records) != {"run", "configuration", "inputs", "status"}:
        raise Mot2DZeusError("run_evidence_invalid")
    run = records["run"]; status = records["status"]
    if (
        run["family"] != "mot_2d" or run["execution_mode"] != "zeus"
        or (require_configured and status["state"] != "configured")
        or (require_configured and status["execution"]["zeus_job_id"] is not None)
    ):
        raise Mot2DZeusError("run_not_submittable")
    selected, _ = materialize_frozen_selection(
        repository_root,
        WorkerRequest(records["run"], records["configuration"], records["inputs"]),
    )
    stream = BytesIO(); np.save(stream, selected, allow_pickle=False)
    selected_bytes = stream.getvalue()
    selected_hash = hashlib.sha256(selected_bytes).hexdigest()
    selection_hash = records["configuration"]["resolved"]["sampling"]["selected_identities_sha256"]
    initial_status = {
        "schema_version": status["schema_version"], "run_id": run["run_id"],
        "revision": 0, "state": "configured", "updated_utc": run["created_utc"],
        "execution": {"mode": "zeus", "local_pid": None, "zeus_job_id": None},
        "error": None,
    }
    encoded = {
        name: encode_record(name, dict(initial_status if name == "status" else records[name]))
        for name in ("run", "configuration", "inputs", "status")
    }
    manifest = {
        "version": 1, "family": "mot_2d", "run_id": run["run_id"],
        "commit": run["git_revision"], "username": profile.username,
        "project_directory": profile.project_directory,
        "records": {name: hashlib.sha256(value).hexdigest() for name, value in encoded.items()},
        "selected_states_sha256": selected_hash,
        "selected_states_size": len(selected_bytes),
        "selection_sha256": selection_hash,
    }
    package_hash = hashlib.sha256(_canonical(manifest)).hexdigest()
    pbs = _render_pbs(run, package_hash, profile.project_directory); pbs_hash = hashlib.sha256(pbs).hexdigest()
    key = hashlib.sha256(_canonical({
        "package_sha256": package_hash, "pbs_sha256": pbs_hash,
        "run_id": run["run_id"], "commit": run["git_revision"],
        "username": profile.username, "project_directory": profile.project_directory,
    })).hexdigest()
    return FrozenMot2DZeusPackage(
        run["run_id"], run["git_revision"], MappingProxyType(encoded),
        package_hash, pbs, pbs_hash, key, profile.username,
        profile.project_directory, selected_bytes, selected_hash, selection_hash,
    )


def _package_payload(package: FrozenMot2DZeusPackage) -> dict[str, Any]:
    return {
        "version": 1, "family": "mot_2d", "run_id": package.run_id,
        "commit": package.commit, "username": package.username,
        "project_directory": package.project_directory,
        "package_sha256": package.package_sha256,
        "pbs_sha256": package.pbs_sha256,
        "submission_key": package.submission_key,
        "records": {name: base64.b64encode(value).decode("ascii")
                    for name, value in package.records.items()},
        "selected_states": base64.b64encode(package.selected_states).decode("ascii"),
        "selected_states_sha256": package.selected_states_sha256,
        "selection_sha256": package.selection_sha256,
        "pbs": base64.b64encode(package.pbs).decode("ascii"),
    }


class PinnedSshMot2DTransport(PinnedSshZeemanTransport):
    operations = _OPERATIONS

    def __init__(self, repository_root: Path, ssh_executable: Path, profile: ZeusProfile, *, timeout=90):
        self.profile = profile
        self.runner = PinnedSshRunner(PinnedSshPolicy.mot_2d_individual(
            repository_root, ssh_executable, timeout=timeout
        ))

    def _submission(self, operation: str, package: FrozenMot2DZeusPackage, nonce: str):
        value = self._request(ReceiverOperation(operation), {
            "identity": _package_payload(package), "nonce": nonce,
        })
        if set(value) != {"state", "nonce", "job_id"}:
            raise Mot2DZeusError("remote_response_invalid")
        return RemoteSubmission(value["state"], value["nonce"], value["job_id"])


class IndividualMot2DZeusCoordinator(IndividualZeemanZeusCoordinator):
    family = "mot_2d"

    def _build_package(self, evidence, profile, *, require_configured=True):
        return build_frozen_mot_2d_package(
            self.root, evidence, profile, require_configured=require_configured
        )
