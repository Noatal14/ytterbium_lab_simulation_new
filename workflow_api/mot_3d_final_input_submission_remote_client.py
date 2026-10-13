"""Pinned SSH transport for final-validation input generation submission."""

import json
import subprocess

from workflow_api.mot_3d_final_input_submission import (
    Mot3DFinalInputSubmissionError,
    RemoteFinalInputSubmissionState,
)
from workflow_api.pinned_ssh import (
    PinnedSshPolicy,
    PinnedSshProcessError,
    PinnedSshRunner,
    ReceiverOperation,
)


class PinnedSshMot3DFinalInputSubmissionTransport:
    def __init__(self, repository_root, executable, profile):
        self.profile = profile
        self.runner = PinnedSshRunner(
            PinnedSshPolicy.mot_3d_final_input_submission(
                repository_root, executable, timeout=30.0
            )
        )

    def _call(self, operation, payload):
        selected = {
            "inspect": ReceiverOperation.INSPECT,
            "submit": ReceiverOperation.SUBMIT,
            "status": ReceiverOperation.STATUS,
        }[operation]
        try:
            result = self.runner.run(selected, self.profile, payload)
        except subprocess.TimeoutExpired:
            raise Mot3DFinalInputSubmissionError(
                "final_input_submission_outcome_unknown"
                if operation == "submit"
                else "zeus_timeout"
            ) from None
        except PinnedSshProcessError as exc:
            raise Mot3DFinalInputSubmissionError("zeus_unavailable") from exc
        try:
            value = json.loads(result.stdout)
        except Exception as exc:
            raise Mot3DFinalInputSubmissionError(
                "final_input_submission_outcome_unknown"
                if operation == "submit" and result.returncode
                else "remote_response_invalid"
            ) from exc
        if isinstance(value, dict) and set(value) == {"error"}:
            if result.stderr:
                raise Mot3DFinalInputSubmissionError(
                    "final_input_submission_outcome_unknown"
                    if operation == "submit"
                    else "remote_response_invalid"
                )
            allowed = {
                "invalid_request",
                "remote_checkout_mismatch",
                "final_input_preparation_invalid",
                "final_input_submission_conflict",
                "final_input_submission_busy",
                "final_input_submission_outcome_unknown",
            }
            code = value["error"]
            raise Mot3DFinalInputSubmissionError(
                code
                if type(code) is str and code in allowed
                else "remote_response_invalid"
            )
        if result.returncode or result.stderr:
            raise Mot3DFinalInputSubmissionError(
                "final_input_submission_outcome_unknown"
                if operation == "submit"
                else "remote_response_invalid"
            )
        keys = {
            "lifecycle",
            "branch",
            "jobs",
            "nonce",
            "submitted_unix_s",
            "completed_array_tasks",
            "completed_scalar_jobs",
        }
        if not isinstance(value, dict) or set(value) != keys:
            raise Mot3DFinalInputSubmissionError("remote_response_invalid")
        return RemoteFinalInputSubmissionState(**value)

    def inspect(self, **payload):
        return self._call("inspect", payload)

    def submit(self, **payload):
        return self._call("submit", payload)

    def status(self, **payload):
        return self._call("status", payload)
