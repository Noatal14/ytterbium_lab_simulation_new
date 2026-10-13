"""Pinned transport for sealed final-validation submission."""

from workflow_api.mot_3d_preliminary_submission import RemotePreliminarySubmissionState
from workflow_api.mot_3d_final_validation_submission import (
    Mot3DFinalValidationSubmissionError,
)
from workflow_api.pinned_ssh import (
    PinnedSshPolicy,
    PinnedSshProcessError,
    PinnedSshRunner,
    ReceiverOperation,
)
import json
import subprocess


class PinnedSshMot3DFinalValidationSubmissionTransport:
    def __init__(self, root, ssh, profile, *, timeout=60):
        self.profile = profile
        self.runner = PinnedSshRunner(
            PinnedSshPolicy.mot_3d_final_validation_submission(
                root, ssh, timeout=timeout
            )
        )

    def _call(self, operation, payload):
        receiver_operation = {
            "inspect": ReceiverOperation.INSPECT,
            "submit": ReceiverOperation.SUBMIT,
            "status": ReceiverOperation.STATUS,
        }[operation]
        try:
            result = self.runner.run(receiver_operation, self.profile, payload)
        except (subprocess.TimeoutExpired, PinnedSshProcessError):
            raise Mot3DFinalValidationSubmissionError(
                "final_validation_submission_outcome_unknown"
                if operation == "submit"
                else "zeus_timeout"
            ) from None
        if result.returncode or result.stderr:
            raise Mot3DFinalValidationSubmissionError(
                "final_validation_submission_outcome_unknown"
                if operation == "submit"
                else "remote_response_invalid"
            )
        try:
            data = json.loads(result.stdout)
        except Exception:
            raise Mot3DFinalValidationSubmissionError(
                "remote_response_invalid"
            ) from None
        if not isinstance(data, dict) or set(data) != {
            "lifecycle",
            "branch",
            "jobs",
            "submission_nonce",
            "submitted_unix_s",
            "completed_array_tasks",
            "completed_merge_jobs",
        }:
            raise Mot3DFinalValidationSubmissionError("remote_response_invalid")
        return RemotePreliminarySubmissionState(
            data["lifecycle"],
            data["branch"],
            data["jobs"],
            data["submission_nonce"],
            data["submitted_unix_s"],
            data["completed_array_tasks"],
            data["completed_merge_jobs"],
        )

    def inspect(self, **payload):
        return self._call("inspect", payload)

    def submit(self, **payload):
        return self._call("submit", payload)

    def status(self, **payload):
        return self._call("status", payload)
