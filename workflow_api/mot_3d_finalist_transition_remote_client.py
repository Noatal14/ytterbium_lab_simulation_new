"""Pinned SSH adapter for finalist selection -> validation inputs."""

import re

from workflow_api.mot_3d_preliminary_transition import (
    PinnedSshMot3DPreliminaryTransitionTransport,
)
from workflow_api.mot_3d_finalist_transition import Mot3DFinalistTransitionError
from workflow_api.pinned_ssh import PinnedSshPolicy
from studies.mot_3d.finalists.merge import FINALIST_WINNER_RANKING_RULE


class PinnedSshMot3DFinalistTransitionTransport(
    PinnedSshMot3DPreliminaryTransitionTransport
):
    policy_factory = staticmethod(PinnedSshPolicy.mot_3d_finalist_transition)
    error_type = Mot3DFinalistTransitionError
    error_prefix = "finalist_transition"

    def _call(self, operation, payload):
        state = super()._call(operation, payload)
        selection = state.winner_selection
        if selection is not None:
            winners = selection.get("winners") if isinstance(selection, dict) else None
            if (
                not isinstance(selection, dict)
                or set(selection) != {"rule", "winners", "evidence_sha256"}
                or selection.get("rule") != FINALIST_WINNER_RANKING_RULE
                or not isinstance(winners, list)
                or len(winners) != 2
                or any(
                    not isinstance(row, dict)
                    or set(row) != {"family", "candidate_id"}
                    or row.get("family") != family
                    or type(row.get("candidate_id")) is not str
                    or re.fullmatch(
                        rf"{re.escape(family)}_finalist_0[1-3]", row["candidate_id"]
                    )
                    is None
                    for row, family in zip(
                        winners, ("angled_donut", "single_pass"), strict=True
                    )
                )
                or type(selection.get("evidence_sha256")) is not str
                or re.fullmatch(r"[0-9a-f]{64}", selection["evidence_sha256"]) is None
                or selection["evidence_sha256"] != state.evidence_sha256
            ):
                raise self.error_type("remote_response_invalid")
        return state
