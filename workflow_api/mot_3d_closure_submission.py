"""Guarded submission facade for the canonical 3D Closure job chain."""

from __future__ import annotations

from lab_setup.mot_3d_timestep_policy import MOT_3D_TIMESTEP_POLICY

import hashlib
import json
from workflow_api.platform_io import os
import subprocess
from pathlib import Path
from typing import Mapping

from workflow_api.mot_3d_discovery_transition import (
    _DIRECTORY_FLAGS,
    _bounded_read_at,
    _open_directory_at,
    _strict_json,
)
from workflow_api.mot_3d_preliminary_submission import (
    Mot3DPreliminarySubmissionCoordinator,
    Mot3DPreliminarySubmissionError,
)
from workflow_api.mot_3d_refinement_transition import (
    Mot3DRefinementTransitionCoordinator,
)
from workflow_api.mot_3d_stage_topology import (
    FAMILIES,
    CLOSURE_SCIENTIFIC_DESIGN,
    CLOSURE_TOPOLOGY,
)
from workflow_api.mot_3d_selection_submission import (
    validate_selection_submission_state,
)
from workflow_api.zeus_discovery_submission import canonical_digest

HEX40 = __import__("re").compile(r"^[0-9a-f]{40}$")
HEX64 = __import__("re").compile(r"^[0-9a-f]{64}$")
FILES = frozenset(
    {
        "campaign.json",
        *(f"selection/closure/{family}.json" for family in FAMILIES),
        *(
            f"jobs/closure/{family}_{kind}.pbs"
            for family in FAMILIES
            for kind in ("array", "merge")
        ),
    }
)
CODE_FILES = frozenset(
    {
        "config.py",
        "simulations/mot_3d.py",
        "studies/mot_3d_campaign.py",
        "studies/mot_3d/integrity.py",
        "studies/mot_3d/refinement/run.py",
        "studies/mot_3d/refinement/merge.py",
        "studies/mot_3d/refinement/select_closure.py",
        "workflow_api/mot_3d_refinement_results.py",
        "workflow_api/mot_3d_refinement_transition.py",
        "workflow_api/mot_3d_refinement_transition_remote.py",
        "workflow_api/mot_3d_stage_topology.py",
        "workflow_api/mot_3d_selection_submission.py",
        "workflow_api/mot_3d_closure_submission.py",
        "workflow_api/mot_3d_selection_submission_remote.py",
        "workflow_api/mot_3d_closure_submission_remote.py",
        "lab_setup/specifications/laboratory_physical_v1.json",
        "lab_setup/specifications/mot_3d_timestep_policy_v2.json",
    }
)


class Mot3DClosureSubmissionError(Mot3DPreliminarySubmissionError):
    """Closed public error for the Closure submission workflow."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_relative(root_fd: int, relative: str, limit=8 * 1024 * 1024) -> bytes:
    parts = Path(relative).parts
    if (
        not parts
        or Path(relative).is_absolute()
        or any(p in {"", ".", ".."} for p in parts)
    ):
        raise OSError("unsafe path")
    descriptor = root_fd
    opened = []
    try:
        for part in parts[:-1]:
            descriptor = _open_directory_at(descriptor, part, create=False)
            opened.append(descriptor)
        return _bounded_read_at(descriptor, parts[-1], limit)
    finally:
        for value in reversed(opened):
            os.close(value)


def validate_prior_transition_sync(
    campaign_fd: int,
    expected_paths: frozenset[str],
    receipt_name: str = "refinement_to_closure.json",
) -> tuple[dict[str, object], bytes]:
    """Return the exact descriptor-bound Stage3 synchronization attestation."""
    mot_fd = _open_directory_at(campaign_fd, ".mot_ui", create=False)
    try:
        sync_fd = _open_directory_at(mot_fd, "sync", create=False)
        try:
            raw = _bounded_read_at(sync_fd, receipt_name, 256 * 1024)
        finally:
            os.close(sync_fd)
    finally:
        os.close(mot_fd)
    sync = _strict_json(raw)
    if (
        not isinstance(sync, dict)
        or set(sync)
        != {
            "status",
            "transition_key",
            "remote_receipt_sha256",
            "bundle_sha256",
            "files",
            "completed_unix_s",
        }
        or sync.get("status") != "synchronized"
        or type(sync.get("completed_unix_s")) is not int
        or not 0 <= sync["completed_unix_s"] <= 253402300799
        or any(
            not isinstance(sync.get(key), str) or not HEX64.fullmatch(sync[key])
            for key in ("transition_key", "remote_receipt_sha256", "bundle_sha256")
        )
        or not isinstance(sync.get("files"), dict)
        or set(sync["files"]) != expected_paths
        or any(
            not isinstance(name, str)
            or not isinstance(digest, str)
            or not HEX64.fullmatch(digest)
            or _sha(_read_relative(campaign_fd, name)) != digest
            for name, digest in sync["files"].items()
        )
    ):
        raise ValueError("invalid prior synchronization receipt")
    return sync, raw


class Mot3DClosureSubmissionCoordinator(Mot3DPreliminarySubmissionCoordinator):
    topology = CLOSURE_TOPOLOGY
    stage_id = "closure"
    stage_label = "Closure"
    submit_effect = "submit_closure"
    already_started_code = "closure_already_started"
    partial_code = "closure_partial_submission"
    outcome_unknown_code = "closure_submission_outcome_unknown"
    completed_action = "await_result_synchronization"
    authority_class = Mot3DRefinementTransitionCoordinator
    expected_stage = "closure"
    files = FILES
    code_files = CODE_FILES
    preparation_error = "closure_preparation_invalid"
    validation_candidates = CLOSURE_TOPOLOGY.candidates_per_family
    sync_receipt_name = "refinement_to_closure.json"
    expected_dt_s = 1e-5
    expected_solver = "RK4StHybridCustom"

    def _science(self, manifest):
        design = manifest.get("design", {})
        return {
            "classification": "candidate_selection_not_final_validation",
            "candidates_per_family": CLOSURE_TOPOLOGY.candidates_per_family,
            "input_ensembles": 4,
            "particles_per_ensemble": CLOSURE_SCIENTIFIC_DESIGN.particles_per_ensemble,
            "total_particles": 3000,
            "recoil_seeds": [42001, 42002, 42003],
            "dt_s": design.get("screening_dt_s"),
            "t_max_s": MOT_3D_TIMESTEP_POLICY["t_max_s"],
            "solver": design.get("solver"),
            "selection_seed": CLOSURE_SCIENTIFIC_DESIGN.selection_seed,
            "bootstrap_replicates": 10_000,
            "bootstrap_seed": CLOSURE_SCIENTIFIC_DESIGN.bootstrap_seed,
        }

    @staticmethod
    def _validate(state, operation: str):
        validate_selection_submission_state(
            state,
            operation,
            error=Mot3DClosureSubmissionError,
        )

    def _default_transport(self, profile):
        from workflow_api.mot_3d_closure_submission_remote_client import (
            PinnedSshMot3DClosureSubmissionTransport,
        )

        return PinnedSshMot3DClosureSubmissionTransport(self.root, self.ssh, profile)

    def _plan(self, request: Mapping[str, object]):
        authority = self.authority_class(
            self.root,
            self.ssh,
            self.git,
            transport_factory=lambda _profile: None,
        )
        try:
            base = authority._recovery_plan(request)
            campaign_id, profile, campaign, manifest, commit = base[:5]
            expected_sync_paths = base[9]
            if (
                manifest.get("stage") != self.expected_stage
                or manifest.get("name") != campaign.name
            ):
                raise ValueError
            campaign_fd = os.open(campaign, _DIRECTORY_FLAGS)
            try:
                sync, sync_raw = validate_prior_transition_sync(
                    campaign_fd, expected_sync_paths, self.sync_receipt_name
                )
                files = {
                    name: _sha(_read_relative(campaign_fd, name)) for name in self.files
                }
            finally:
                os.close(campaign_fd)
            science = self._science(manifest)
            if (
                science["dt_s"] != self.expected_dt_s
                or science["solver"] != self.expected_solver
            ):
                raise ValueError
            root_fd = os.open(self.root, _DIRECTORY_FLAGS)
            try:
                code_files = {
                    name: _sha(_read_relative(root_fd, name))
                    for name in self.code_files
                }
            finally:
                os.close(root_fd)
            identity = {
                "campaign_sha256": files["campaign.json"],
                "local_transition_receipt_sha256": _sha(sync_raw),
                "transition_key": sync.get("transition_key"),
                "remote_transition_receipt_sha256": sync.get("remote_receipt_sha256"),
                "bundle_sha256": sync.get("bundle_sha256"),
                "files": files,
                "science": science,
                "physical_model_sha256": manifest.get("provenance", {}).get(
                    "physical_model_sha256"
                ),
                "upstream_campaign_sha256": manifest.get(
                    "upstream_2d_campaign", {}
                ).get("campaign_sha256"),
                "upstream_final_report_sha256": manifest.get(
                    "upstream_2d_campaign", {}
                ).get("final_report_sha256"),
                "timestep_policy_sha256": manifest.get("design", {})
                .get("timestep_evidence", {})
                .get("policy_sha256"),
                "code_files": code_files,
            }
            if any(
                not isinstance(identity[key], str) or not HEX64.fullmatch(identity[key])
                for key in (
                    "transition_key",
                    "remote_transition_receipt_sha256",
                    "bundle_sha256",
                    "physical_model_sha256",
                    "upstream_campaign_sha256",
                    "upstream_final_report_sha256",
                    "timestep_policy_sha256",
                )
            ):
                raise ValueError
            if any(
                not HEX64.fullmatch(value) for value in identity["code_files"].values()
            ):
                raise ValueError
        except Exception as exc:
            raise Mot3DClosureSubmissionError(self.preparation_error) from exc
        revision = subprocess.run(
            [self.git, "-C", self.root, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        dirty = subprocess.run(
            [
                self.git,
                "-C",
                self.root,
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if (
            revision.returncode
            or revision.stderr
            or revision.stdout.strip() != commit
            or dirty.returncode
            or dirty.stderr
            or dirty.stdout
        ):
            raise Mot3DClosureSubmissionError("local_files_changed")
        relative = campaign.relative_to(self.root).as_posix()
        key = canonical_digest({"campaign": relative, "commit": commit, **identity})
        return campaign_id, profile, campaign, manifest, commit, identity, key, relative

    @staticmethod
    def _synchronized(identity):
        return {
            "status": "synchronized",
            "receipt_sha256": identity["local_transition_receipt_sha256"],
        }

    def _status_local_sync(self, plan):
        return self._synchronized(plan[5])

    def _preview_local_sync(self, pending):
        return self._synchronized(pending.identity)

    def _confirm_local_sync(self, pending):
        return self._synchronized(pending.identity)

    def status(self, request):
        try:
            value = super().status(request)
        except Mot3DPreliminarySubmissionError as exc:
            raise Mot3DClosureSubmissionError(exc.code) from exc
        value["validation"] = {
            "status": "not_started",
            "expected_candidates_per_family": self.validation_candidates,
            "expected_recoil_seeds_per_candidate": 3,
        }
        return value

    def preview(self, request, *, session_id: str):
        try:
            return super().preview(request, session_id=session_id)
        except Mot3DPreliminarySubmissionError as exc:
            raise Mot3DClosureSubmissionError(exc.code) from exc

    def confirm(self, request, *, session_id: str):
        try:
            return super().confirm(request, session_id=session_id)
        except Mot3DPreliminarySubmissionError as exc:
            raise Mot3DClosureSubmissionError(exc.code) from exc
