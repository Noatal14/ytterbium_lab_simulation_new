"""Pinned SSH adapter for Closure -> finalist selection."""

from workflow_api.mot_3d_preliminary_transition import (
    PinnedSshMot3DPreliminaryTransitionTransport,
)
from workflow_api.mot_3d_closure_transition import Mot3DClosureTransitionError
from workflow_api.pinned_ssh import PinnedSshPolicy


class PinnedSshMot3DClosureTransitionTransport(
    PinnedSshMot3DPreliminaryTransitionTransport
):
    policy_factory = staticmethod(PinnedSshPolicy.mot_3d_closure_transition)
    error_type = Mot3DClosureTransitionError
    error_prefix = "closure_transition"
