"""Pinned SSH adapter for zero-submit Final Validation completion."""

from workflow_api.mot_3d_final_validation_completion import (
    Mot3DFinalValidationCompletionError,
)
from workflow_api.mot_3d_preliminary_transition import (
    PinnedSshMot3DPreliminaryTransitionTransport,
)
from workflow_api.pinned_ssh import PinnedSshPolicy


class PinnedSshMot3DFinalValidationCompletionTransport(
    PinnedSshMot3DPreliminaryTransitionTransport
):
    policy_factory = staticmethod(PinnedSshPolicy.mot_3d_final_validation_completion)
    error_type = Mot3DFinalValidationCompletionError
    error_prefix = "final_validation_completion"
