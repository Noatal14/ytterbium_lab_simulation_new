"""Pinned SSH adapter for the Refinement -> Closure transition receiver."""

from workflow_api.mot_3d_preliminary_transition import (
    PinnedSshMot3DPreliminaryTransitionTransport,
)
from workflow_api.mot_3d_refinement_transition import (
    Mot3DRefinementTransitionError,
)
from workflow_api.pinned_ssh import PinnedSshPolicy


class PinnedSshMot3DRefinementTransitionTransport(
    PinnedSshMot3DPreliminaryTransitionTransport
):
    """Stage-specific binding of the shared strict transition transport."""

    policy_factory = staticmethod(PinnedSshPolicy.mot_3d_refinement_transition)
    error_type = Mot3DRefinementTransitionError
    error_prefix = "refinement_transition"
