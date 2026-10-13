"""Pinned SSH adapter for final-input-generation -> final-validation."""

from workflow_api.mot_3d_preliminary_transition import (
    PinnedSshMot3DPreliminaryTransitionTransport,
)
from workflow_api.mot_3d_final_validation_transition import (
    Mot3DFinalValidationTransitionError,
)
from workflow_api.pinned_ssh import PinnedSshPolicy


class PinnedSshMot3DFinalValidationTransitionTransport(
    PinnedSshMot3DPreliminaryTransitionTransport
):
    policy_factory = staticmethod(PinnedSshPolicy.mot_3d_final_validation_transition)
    error_type = Mot3DFinalValidationTransitionError
    error_prefix = "final_validation_transition"
