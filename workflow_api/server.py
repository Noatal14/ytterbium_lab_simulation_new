"""Minimal localhost bridge for workflow inspection and guarded actions.

Remote surfaces are explicit and CSRF-protected: a read-only Zeus snapshot and
review-before-write campaign preparation and smoke submission.  There is no
generic command endpoint or caller-controlled scheduler operation.
"""

from __future__ import annotations

import json
import secrets
import time
import threading
from dataclasses import dataclass
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, TYPE_CHECKING
from urllib.parse import unquote, urlsplit

from workflow_api import list_workflows
from workflow_api.discovery import DiscoveryError, get_campaign, list_campaigns
from workflow_api.error_catalog import resolve_error, resolve_wire_error
from workflow_api.individual_run_discovery import (
    CanonicalIndividualRunRegistry,
    IndividualRunDiscoveryError,
    IndividualRunRegistry,
)
from workflow_api.models import SCHEMA_VERSION
from workflow_api.mot_2d_sources import list_sources
from workflow_api.mot_2d_individual_api import IndividualMot2DApi
from workflow_api.mot_2d_run_creation import Mot2DRunCreationService
from workflow_api.mot_2d_local_execution import Mot2DBoundedLocalExecutionPool
from workflow_api.mot_2d_zeus_execution import (
    IndividualMot2DZeusCoordinator,
    PinnedSshMot2DTransport,
)
from workflow_api.mot_3d_individual_api import IndividualMot3DApi
from workflow_api.mot_3d_run_creation import Mot3DRunCreationService
from workflow_api.mutation import CreationService
from workflow_api.repository_snapshot import (
    RepositorySnapshotProvider,
    ZeemanRepositorySnapshotProvider,
    Mot2DIndividualRepositorySnapshotProvider,
    Mot3DIndividualRepositorySnapshotProvider,
)
from workflow_api.run_execution import issue_execution_authority
from workflow_api.zeeman_run_creation import ZeemanRunCreationService
from workflow_api.zeeman_local_execution import BoundedLocalExecutionPool
from workflow_api.zeeman_zeus_execution import (
    IndividualZeemanZeusCoordinator,
    PinnedSshZeemanTransport,
)
from workflow_api.zeus_snapshot import ZeusProfile
from workflow_api.zeus_snapshot import (
    ZeusSnapshotError,
    ZeusSnapshotProvider,
    ZeusSnapshotService,
)
from workflow_api.zeus_transfer import ZeusPreparationCoordinator, ZeusPreparationError
from workflow_api.zeus_submission import (
    ZeusSmokeSubmissionCoordinator,
    ZeusSubmissionError,
)
from workflow_api.zeus_screening import ZeusScreeningCoordinator, ZeusScreeningError
from workflow_api.zeus_screen_submission import (
    ZeusScreenSubmissionCoordinator,
    ZeusScreenSubmissionError,
)
from workflow_api.zeus_refinement import ZeusRefinementCoordinator, ZeusRefinementError
from workflow_api.zeus_refinement_submission import (
    ZeusRefinementSubmissionCoordinator,
    ZeusRefinementSubmissionError,
)
from workflow_api.zeus_confirmation import (
    ZeusConfirmationCoordinator,
    ZeusConfirmationError,
)
from workflow_api.zeus_confirmation_submission import (
    ZeusConfirmationSubmissionCoordinator,
    ZeusConfirmationSubmissionError,
)
from workflow_api.zeus_sensitivity import (
    ZeusSensitivityCoordinator,
    ZeusSensitivityError,
)
from workflow_api.zeus_sensitivity_submission import (
    ZeusSensitivitySubmissionCoordinator,
    ZeusSensitivitySubmissionError,
)
from workflow_api.zeus_production import ZeusProductionCoordinator, ZeusProductionError
from workflow_api.zeus_production_submission import (
    ZeusProductionSubmissionCoordinator,
    ZeusProductionSubmissionError,
)
from workflow_api.zeus_finalization import (
    ZeusFinalizationCoordinator,
    ZeusFinalizationError,
)
from workflow_api.zeus_discovery_submission import (
    ZeusMot3DDiscoverySubmissionCoordinator,
    ZeusMot3DDiscoverySubmissionError,
)
from workflow_api.mot_3d_discovery_transition import (
    Mot3DDiscoveryTransitionCoordinator,
    Mot3DDiscoveryTransitionError,
)
from workflow_api.mot_3d_preliminary_submission import (
    Mot3DPreliminarySubmissionCoordinator,
    Mot3DPreliminarySubmissionError,
)
from workflow_api.mot_3d_refinement_submission import (
    Mot3DRefinementSubmissionCoordinator,
    Mot3DRefinementSubmissionError,
)
from workflow_api.mot_3d_preliminary_transition import (
    Mot3DPreliminaryTransitionCoordinator,
    Mot3DPreliminaryTransitionError,
)
from workflow_api.zeeman_individual_api import IndividualZeemanApi
from workflow_api.zeeman_zeus_execution import ZeemanZeusError

if TYPE_CHECKING:
    from workflow_api.mot_3d_bootstrap import Mot3DDiscoveryBootstrapService

HOST = "127.0.0.1"
PORT = 8765


def workflow_catalog_payload() -> dict[str, Any]:
    return {
        "api_version": SCHEMA_VERSION,
        "data": [workflow.to_dict() for workflow in list_workflows()],
    }


@dataclass(frozen=True)
class PostRoute:
    path: str
    service_attr: str
    operation: str
    call_style: str
    unavailable_code: str
    unavailable_message: str
    success_status: HTTPStatus
    exception_family: type[Exception]


def _post_routes() -> tuple[PostRoute, ...]:
    rows = [
        (
            "/api/v1/campaigns/2d/preview",
            "creation_service",
            "preview",
            "creation_preview",
            "creation_unavailable",
            "Local campaign creation is unavailable.",
            HTTPStatus.OK,
            Exception,
        ),
        (
            "/api/v1/campaigns/2d/confirm",
            "creation_service",
            "confirm",
            "creation_confirm",
            "creation_unavailable",
            "Local campaign creation is unavailable.",
            HTTPStatus.CREATED,
            Exception,
        ),
        (
            "/api/v1/campaigns/3d/bootstrap/status",
            "mot_3d_bootstrap_service",
            "status",
            "payload",
            "mot_3d_bootstrap_unavailable",
            "3D campaign preparation is unavailable.",
            HTTPStatus.OK,
            ValueError,
        ),
        (
            "/api/v1/campaigns/3d/bootstrap/preview",
            "mot_3d_bootstrap_service",
            "preview",
            "session_kw",
            "mot_3d_bootstrap_unavailable",
            "3D campaign preparation is unavailable.",
            HTTPStatus.OK,
            ValueError,
        ),
        (
            "/api/v1/campaigns/3d/bootstrap/confirm",
            "mot_3d_bootstrap_service",
            "confirm",
            "session_kw",
            "mot_3d_bootstrap_unavailable",
            "3D campaign preparation is unavailable.",
            HTTPStatus.CREATED,
            ValueError,
        ),
        (
            "/api/v1/zeus/submissions/mot-3d-discovery/status",
            "mot_3d_discovery_submission_service",
            "status",
            "payload",
            "zeus_mot_3d_discovery_submission_unavailable",
            "Zeus 3D Discovery submission is unavailable.",
            HTTPStatus.OK,
            ZeusMot3DDiscoverySubmissionError,
        ),
        (
            "/api/v1/zeus/submissions/mot-3d-discovery/preview",
            "mot_3d_discovery_submission_service",
            "preview",
            "session_kw",
            "zeus_mot_3d_discovery_submission_unavailable",
            "Zeus 3D Discovery submission is unavailable.",
            HTTPStatus.OK,
            ZeusMot3DDiscoverySubmissionError,
        ),
        (
            "/api/v1/zeus/submissions/mot-3d-discovery/confirm",
            "mot_3d_discovery_submission_service",
            "confirm",
            "session_kw",
            "zeus_mot_3d_discovery_submission_unavailable",
            "Zeus 3D Discovery submission is unavailable.",
            HTTPStatus.CREATED,
            ZeusMot3DDiscoverySubmissionError,
        ),
        (
            "/api/v1/zeus/mot-3d/discovery-transition/status",
            "mot_3d_discovery_transition_service",
            "status",
            "payload",
            "mot_3d_discovery_transition_unavailable",
            "3D Discovery result synchronization is unavailable.",
            HTTPStatus.OK,
            Mot3DDiscoveryTransitionError,
        ),
        (
            "/api/v1/zeus/mot-3d/discovery-transition/preview",
            "mot_3d_discovery_transition_service",
            "preview",
            "session_kw",
            "mot_3d_discovery_transition_unavailable",
            "3D Discovery result synchronization is unavailable.",
            HTTPStatus.OK,
            Mot3DDiscoveryTransitionError,
        ),
        (
            "/api/v1/zeus/mot-3d/discovery-transition/confirm",
            "mot_3d_discovery_transition_service",
            "confirm",
            "session_kw",
            "mot_3d_discovery_transition_unavailable",
            "3D Discovery result synchronization is unavailable.",
            HTTPStatus.CREATED,
            Mot3DDiscoveryTransitionError,
        ),
        (
            "/api/v1/zeus/submissions/mot-3d-preliminary-check/status",
            "mot_3d_preliminary_submission_service",
            "status",
            "payload",
            "mot_3d_preliminary_submission_unavailable",
            "3D Preliminary-check submission is unavailable.",
            HTTPStatus.OK,
            Mot3DPreliminarySubmissionError,
        ),
        (
            "/api/v1/zeus/submissions/mot-3d-preliminary-check/preview",
            "mot_3d_preliminary_submission_service",
            "preview",
            "session_kw",
            "mot_3d_preliminary_submission_unavailable",
            "3D Preliminary-check submission is unavailable.",
            HTTPStatus.OK,
            Mot3DPreliminarySubmissionError,
        ),
        (
            "/api/v1/zeus/submissions/mot-3d-preliminary-check/confirm",
            "mot_3d_preliminary_submission_service",
            "confirm",
            "session_kw",
            "mot_3d_preliminary_submission_unavailable",
            "3D Preliminary-check submission is unavailable.",
            HTTPStatus.CREATED,
            Mot3DPreliminarySubmissionError,
        ),
        (
            "/api/v1/zeus/submissions/mot-3d-refinement/status",
            "mot_3d_refinement_submission_service",
            "status",
            "payload",
            "mot_3d_refinement_submission_unavailable",
            "3D Refinement submission is unavailable.",
            HTTPStatus.OK,
            Mot3DRefinementSubmissionError,
        ),
        (
            "/api/v1/zeus/submissions/mot-3d-refinement/preview",
            "mot_3d_refinement_submission_service",
            "preview",
            "session_kw",
            "mot_3d_refinement_submission_unavailable",
            "3D Refinement submission is unavailable.",
            HTTPStatus.OK,
            Mot3DRefinementSubmissionError,
        ),
        (
            "/api/v1/zeus/submissions/mot-3d-refinement/confirm",
            "mot_3d_refinement_submission_service",
            "confirm",
            "session_kw",
            "mot_3d_refinement_submission_unavailable",
            "3D Refinement submission is unavailable.",
            HTTPStatus.CREATED,
            Mot3DRefinementSubmissionError,
        ),
        (
            "/api/v1/zeus/mot-3d/preliminary-transition/status",
            "mot_3d_preliminary_transition_service",
            "status",
            "payload",
            "mot_3d_preliminary_transition_unavailable",
            "3D Preliminary-check result synchronization is unavailable.",
            HTTPStatus.OK,
            Mot3DPreliminaryTransitionError,
        ),
        (
            "/api/v1/zeus/mot-3d/preliminary-transition/preview",
            "mot_3d_preliminary_transition_service",
            "preview",
            "session_kw",
            "mot_3d_preliminary_transition_unavailable",
            "3D Preliminary-check result synchronization is unavailable.",
            HTTPStatus.OK,
            Mot3DPreliminaryTransitionError,
        ),
        (
            "/api/v1/zeus/mot-3d/preliminary-transition/confirm",
            "mot_3d_preliminary_transition_service",
            "confirm",
            "session_kw",
            "mot_3d_preliminary_transition_unavailable",
            "3D Preliminary-check result synchronization is unavailable.",
            HTTPStatus.CREATED,
            Mot3DPreliminaryTransitionError,
        ),
        (
            "/api/v1/zeus/snapshot",
            "zeus_service",
            "snapshot",
            "payload",
            "zeus_unavailable",
            "Read-only Zeus inspection is unavailable.",
            HTTPStatus.OK,
            ZeusSnapshotError,
        ),
        (
            "/api/v1/zeus/transfers/preview",
            "transfer_service",
            "preview",
            "session_kw",
            "zeus_preparation_unavailable",
            "Zeus campaign preparation is unavailable.",
            HTTPStatus.OK,
            ZeusPreparationError,
        ),
        (
            "/api/v1/zeus/transfers/confirm",
            "transfer_service",
            "confirm",
            "session_kw",
            "zeus_preparation_unavailable",
            "Zeus campaign preparation is unavailable.",
            HTTPStatus.CREATED,
            ZeusPreparationError,
        ),
        (
            "/api/v1/zeus/submissions/smoke/preview",
            "submission_service",
            "preview",
            "session_kw",
            "zeus_submission_unavailable",
            "Zeus smoke submission is unavailable.",
            HTTPStatus.OK,
            ZeusSubmissionError,
        ),
        (
            "/api/v1/zeus/submissions/smoke/confirm",
            "submission_service",
            "confirm",
            "session_kw",
            "zeus_submission_unavailable",
            "Zeus smoke submission is unavailable.",
            HTTPStatus.CREATED,
            ZeusSubmissionError,
        ),
        (
            "/api/v1/zeus/smoke/status",
            "screening_service",
            "status",
            "session_kw",
            "zeus_screening_unavailable",
            "Zeus smoke inspection is unavailable.",
            HTTPStatus.OK,
            ZeusScreeningError,
        ),
        (
            "/api/v1/zeus/screening/preview",
            "screening_service",
            "preview",
            "session_kw",
            "zeus_screening_unavailable",
            "Zeus smoke inspection is unavailable.",
            HTTPStatus.OK,
            ZeusScreeningError,
        ),
        (
            "/api/v1/zeus/screening/confirm",
            "screening_service",
            "confirm",
            "session_kw",
            "zeus_screening_unavailable",
            "Zeus smoke inspection is unavailable.",
            HTTPStatus.CREATED,
            ZeusScreeningError,
        ),
        (
            "/api/v1/zeus/submissions/screening/preview",
            "screen_submission_service",
            "preview",
            "session_kw",
            "zeus_screen_submission_unavailable",
            "Zeus screening submission is unavailable.",
            HTTPStatus.OK,
            ZeusScreenSubmissionError,
        ),
        (
            "/api/v1/zeus/submissions/screening/confirm",
            "screen_submission_service",
            "confirm",
            "session_kw",
            "zeus_screen_submission_unavailable",
            "Zeus screening submission is unavailable.",
            HTTPStatus.CREATED,
            ZeusScreenSubmissionError,
        ),
        (
            "/api/v1/zeus/screen/status",
            "refinement_service",
            "status",
            "payload",
            "zeus_refinement_unavailable",
            "Zeus refinement preparation is unavailable.",
            HTTPStatus.OK,
            ZeusRefinementError,
        ),
        (
            "/api/v1/zeus/refinement/preview",
            "refinement_service",
            "preview",
            "session_kw",
            "zeus_refinement_unavailable",
            "Zeus refinement preparation is unavailable.",
            HTTPStatus.OK,
            ZeusRefinementError,
        ),
        (
            "/api/v1/zeus/refinement/confirm",
            "refinement_service",
            "confirm",
            "session_kw",
            "zeus_refinement_unavailable",
            "Zeus refinement preparation is unavailable.",
            HTTPStatus.CREATED,
            ZeusRefinementError,
        ),
        (
            "/api/v1/zeus/submissions/refinement/status",
            "refinement_submission_service",
            "status",
            "payload",
            "zeus_refinement_submission_unavailable",
            "Zeus refinement submission is unavailable.",
            HTTPStatus.OK,
            ZeusRefinementSubmissionError,
        ),
        (
            "/api/v1/zeus/submissions/refinement/preview",
            "refinement_submission_service",
            "preview",
            "session_kw",
            "zeus_refinement_submission_unavailable",
            "Zeus refinement submission is unavailable.",
            HTTPStatus.OK,
            ZeusRefinementSubmissionError,
        ),
        (
            "/api/v1/zeus/submissions/refinement/confirm",
            "refinement_submission_service",
            "confirm",
            "session_kw",
            "zeus_refinement_submission_unavailable",
            "Zeus refinement submission is unavailable.",
            HTTPStatus.CREATED,
            ZeusRefinementSubmissionError,
        ),
        (
            "/api/v1/zeus/refinement-chain/status",
            "confirmation_service",
            "status",
            "payload",
            "zeus_confirmation_unavailable",
            "Zeus confirmation preparation is unavailable.",
            HTTPStatus.OK,
            ZeusConfirmationError,
        ),
        (
            "/api/v1/zeus/confirmation/preview",
            "confirmation_service",
            "preview",
            "session_kw",
            "zeus_confirmation_unavailable",
            "Zeus confirmation preparation is unavailable.",
            HTTPStatus.OK,
            ZeusConfirmationError,
        ),
        (
            "/api/v1/zeus/confirmation/confirm",
            "confirmation_service",
            "confirm",
            "session_kw",
            "zeus_confirmation_unavailable",
            "Zeus confirmation preparation is unavailable.",
            HTTPStatus.CREATED,
            ZeusConfirmationError,
        ),
        (
            "/api/v1/zeus/submissions/confirmation/status",
            "confirmation_submission_service",
            "status",
            "payload",
            "zeus_confirmation_submission_unavailable",
            "Zeus confirmation submission is unavailable.",
            HTTPStatus.OK,
            ZeusConfirmationSubmissionError,
        ),
        (
            "/api/v1/zeus/submissions/confirmation/preview",
            "confirmation_submission_service",
            "preview",
            "session_kw",
            "zeus_confirmation_submission_unavailable",
            "Zeus confirmation submission is unavailable.",
            HTTPStatus.OK,
            ZeusConfirmationSubmissionError,
        ),
        (
            "/api/v1/zeus/submissions/confirmation/confirm",
            "confirmation_submission_service",
            "confirm",
            "session_kw",
            "zeus_confirmation_submission_unavailable",
            "Zeus confirmation submission is unavailable.",
            HTTPStatus.CREATED,
            ZeusConfirmationSubmissionError,
        ),
        (
            "/api/v1/zeus/confirmation-results/status",
            "sensitivity_service",
            "status",
            "payload",
            "zeus_sensitivity_unavailable",
            "Zeus Sensitivity preparation is unavailable.",
            HTTPStatus.OK,
            ZeusSensitivityError,
        ),
        (
            "/api/v1/zeus/sensitivity/preview",
            "sensitivity_service",
            "preview",
            "session_kw",
            "zeus_sensitivity_unavailable",
            "Zeus Sensitivity preparation is unavailable.",
            HTTPStatus.OK,
            ZeusSensitivityError,
        ),
        (
            "/api/v1/zeus/sensitivity/confirm",
            "sensitivity_service",
            "confirm",
            "session_kw",
            "zeus_sensitivity_unavailable",
            "Zeus Sensitivity preparation is unavailable.",
            HTTPStatus.CREATED,
            ZeusSensitivityError,
        ),
        (
            "/api/v1/zeus/submissions/sensitivity/status",
            "sensitivity_submission_service",
            "status",
            "payload",
            "zeus_sensitivity_submission_unavailable",
            "Zeus Sensitivity submission is unavailable.",
            HTTPStatus.OK,
            ZeusSensitivitySubmissionError,
        ),
        (
            "/api/v1/zeus/submissions/sensitivity/preview",
            "sensitivity_submission_service",
            "preview",
            "session_kw",
            "zeus_sensitivity_submission_unavailable",
            "Zeus Sensitivity submission is unavailable.",
            HTTPStatus.OK,
            ZeusSensitivitySubmissionError,
        ),
        (
            "/api/v1/zeus/submissions/sensitivity/confirm",
            "sensitivity_submission_service",
            "confirm",
            "session_kw",
            "zeus_sensitivity_submission_unavailable",
            "Zeus Sensitivity submission is unavailable.",
            HTTPStatus.CREATED,
            ZeusSensitivitySubmissionError,
        ),
        (
            "/api/v1/zeus/sensitivity-results/status",
            "production_service",
            "status",
            "payload",
            "zeus_production_unavailable",
            "Zeus Production preparation is unavailable.",
            HTTPStatus.OK,
            ZeusProductionError,
        ),
        (
            "/api/v1/zeus/production/preview",
            "production_service",
            "preview",
            "session_kw",
            "zeus_production_unavailable",
            "Zeus Production preparation is unavailable.",
            HTTPStatus.OK,
            ZeusProductionError,
        ),
        (
            "/api/v1/zeus/production/confirm",
            "production_service",
            "confirm",
            "session_kw",
            "zeus_production_unavailable",
            "Zeus Production preparation is unavailable.",
            HTTPStatus.CREATED,
            ZeusProductionError,
        ),
        (
            "/api/v1/zeus/submissions/production/status",
            "production_submission_service",
            "status",
            "payload",
            "zeus_production_submission_unavailable",
            "Zeus Production submission is unavailable.",
            HTTPStatus.OK,
            ZeusProductionSubmissionError,
        ),
        (
            "/api/v1/zeus/submissions/production/preview",
            "production_submission_service",
            "preview",
            "session_kw",
            "zeus_production_submission_unavailable",
            "Zeus Production submission is unavailable.",
            HTTPStatus.OK,
            ZeusProductionSubmissionError,
        ),
        (
            "/api/v1/zeus/submissions/production/confirm",
            "production_submission_service",
            "confirm",
            "session_kw",
            "zeus_production_submission_unavailable",
            "Zeus Production submission is unavailable.",
            HTTPStatus.CREATED,
            ZeusProductionSubmissionError,
        ),
        (
            "/api/v1/zeus/production-results/status",
            "finalization_service",
            "status",
            "payload",
            "zeus_finalization_unavailable",
            "Zeus campaign finalization is unavailable.",
            HTTPStatus.OK,
            ZeusFinalizationError,
        ),
        (
            "/api/v1/zeus/finalization/preview",
            "finalization_service",
            "preview",
            "session_kw",
            "zeus_finalization_unavailable",
            "Zeus campaign finalization is unavailable.",
            HTTPStatus.OK,
            ZeusFinalizationError,
        ),
        (
            "/api/v1/zeus/finalization/confirm",
            "finalization_service",
            "confirm",
            "session_kw",
            "zeus_finalization_unavailable",
            "Zeus campaign finalization is unavailable.",
            HTTPStatus.CREATED,
            ZeusFinalizationError,
        ),
        (
            "/api/v1/individual-runs/zeeman/preview",
            "individual_zeeman_api",
            "preview",
            "session_kw",
            "individual_zeeman_unavailable",
            "Individual Zeeman runs are unavailable.",
            HTTPStatus.OK,
            Exception,
        ),
        (
            "/api/v1/individual-runs/zeeman/confirm",
            "individual_zeeman_api",
            "confirm",
            "session_kw",
            "individual_zeeman_unavailable",
            "Individual Zeeman runs are unavailable.",
            HTTPStatus.CREATED,
            Exception,
        ),
        (
            "/api/v1/individual-runs/zeeman/local/start",
            "individual_zeeman_api",
            "start_local",
            "session_kw",
            "individual_zeeman_unavailable",
            "Individual Zeeman runs are unavailable.",
            HTTPStatus.ACCEPTED,
            Exception,
        ),
        (
            "/api/v1/individual-runs/zeeman/zeus/preview",
            "individual_zeeman_api",
            "preview_zeus",
            "session_kw",
            "individual_zeeman_unavailable",
            "Individual Zeeman runs are unavailable.",
            HTTPStatus.OK,
            Exception,
        ),
        (
            "/api/v1/individual-runs/zeeman/zeus/confirm",
            "individual_zeeman_api",
            "confirm_zeus",
            "session_kw",
            "individual_zeeman_unavailable",
            "Individual Zeeman runs are unavailable.",
            HTTPStatus.ACCEPTED,
            Exception,
        ),
        (
            "/api/v1/individual-runs/zeeman/zeus/refresh",
            "individual_zeeman_api",
            "refresh_zeus",
            "session_kw",
            "individual_zeeman_unavailable",
            "Individual Zeeman runs are unavailable.",
            HTTPStatus.OK,
            Exception,
        ),
        (
            "/api/v1/individual-runs/mot-2d/preview",
            "individual_mot_2d_api",
            "preview",
            "session_kw",
            "individual_mot_2d_unavailable",
            "Individual 2D-MOT runs are unavailable.",
            HTTPStatus.OK,
            Exception,
        ),
        (
            "/api/v1/individual-runs/mot-2d/confirm",
            "individual_mot_2d_api",
            "confirm",
            "session_kw",
            "individual_mot_2d_unavailable",
            "Individual 2D-MOT runs are unavailable.",
            HTTPStatus.CREATED,
            Exception,
        ),
        (
            "/api/v1/individual-runs/mot-2d/local/start",
            "individual_mot_2d_api",
            "start_local",
            "session_kw",
            "individual_mot_2d_unavailable",
            "Individual 2D-MOT runs are unavailable.",
            HTTPStatus.ACCEPTED,
            Exception,
        ),
        (
            "/api/v1/individual-runs/mot-2d/zeus/preview",
            "individual_mot_2d_api",
            "preview_zeus",
            "session_kw",
            "individual_mot_2d_unavailable",
            "Individual 2D-MOT runs are unavailable.",
            HTTPStatus.OK,
            Exception,
        ),
        (
            "/api/v1/individual-runs/mot-2d/zeus/confirm",
            "individual_mot_2d_api",
            "confirm_zeus",
            "session_kw",
            "individual_mot_2d_unavailable",
            "Individual 2D-MOT runs are unavailable.",
            HTTPStatus.ACCEPTED,
            Exception,
        ),
        (
            "/api/v1/individual-runs/mot-2d/zeus/refresh",
            "individual_mot_2d_api",
            "refresh_zeus",
            "session_kw",
            "individual_mot_2d_unavailable",
            "Individual 2D-MOT runs are unavailable.",
            HTTPStatus.OK,
            Exception,
        ),
        (
            "/api/v1/individual-runs/mot-3d/preview",
            "individual_mot_3d_api",
            "preview",
            "session_kw",
            "individual_mot_3d_unavailable",
            "Individual 3D-MOT runs are unavailable.",
            HTTPStatus.OK,
            Exception,
        ),
        (
            "/api/v1/individual-runs/mot-3d/confirm",
            "individual_mot_3d_api",
            "confirm",
            "session_kw",
            "individual_mot_3d_unavailable",
            "Individual 3D-MOT runs are unavailable.",
            HTTPStatus.CREATED,
            Exception,
        ),
        (
            "/api/v1/individual-runs/mot-3d/local/start",
            "individual_mot_3d_api",
            "start_local",
            "session_kw",
            "individual_mot_3d_unavailable",
            "Individual 3D-MOT runs are unavailable.",
            HTTPStatus.ACCEPTED,
            Exception,
        ),
        (
            "/api/v1/individual-runs/mot-3d/zeus/preview",
            "individual_mot_3d_api",
            "preview_zeus",
            "session_kw",
            "individual_mot_3d_unavailable",
            "Individual 3D-MOT runs are unavailable.",
            HTTPStatus.OK,
            Exception,
        ),
        (
            "/api/v1/individual-runs/mot-3d/zeus/confirm",
            "individual_mot_3d_api",
            "confirm_zeus",
            "session_kw",
            "individual_mot_3d_unavailable",
            "Individual 3D-MOT runs are unavailable.",
            HTTPStatus.ACCEPTED,
            Exception,
        ),
        (
            "/api/v1/individual-runs/mot-3d/zeus/refresh",
            "individual_mot_3d_api",
            "refresh_zeus",
            "session_kw",
            "individual_mot_3d_unavailable",
            "Individual 3D-MOT runs are unavailable.",
            HTTPStatus.OK,
            Exception,
        ),
    ]
    return tuple(PostRoute(*row) for row in rows)


POST_ROUTES = {route.path: route for route in _post_routes()}

_INDIVIDUAL_ZEUS_ERRORS = {
    "confirmation_invalid": (
        HTTPStatus.BAD_REQUEST,
        "The Zeus confirmation is invalid or belongs to another session.",
    ),
    "confirmation_expired": (
        HTTPStatus.CONFLICT,
        "The Zeus review expired. Review the submission again.",
    ),
    "profile_invalid": (
        HTTPStatus.BAD_REQUEST,
        "The Zeus connection profile is invalid.",
    ),
    "run_not_submittable": (
        HTTPStatus.CONFLICT,
        "This run is not ready for Zeus submission.",
    ),
    "run_evidence_changed": (
        HTTPStatus.CONFLICT,
        "The reviewed run changed. Review it again.",
    ),
    "submission_outcome_unknown": (
        HTTPStatus.CONFLICT,
        "The Zeus submission outcome is unknown and requires inspection.",
    ),
    "profile_or_submission_identity_mismatch": (
        HTTPStatus.CONFLICT,
        "The Zeus connection does not match the submitted run.",
    ),
    "job_id_unavailable": (
        HTTPStatus.CONFLICT,
        "The Zeus job identifier is unavailable.",
    ),
    "remote_status_invalid": (
        HTTPStatus.BAD_GATEWAY,
        "Zeus returned an invalid job status.",
    ),
    "too_many_pending_previews": (
        HTTPStatus.TOO_MANY_REQUESTS,
        "Too many Zeus reviews are pending.",
    ),
}


def _invoke_post_route(
    route: PostRoute, service: object, payload: dict[str, Any], session: str
) -> Any:
    operation = getattr(service, route.operation)
    if route.call_style == "payload":
        return operation(payload)
    if route.call_style == "session_kw":
        return operation(payload, session_id=session)
    if route.call_style == "creation_preview":
        return operation(payload, session)
    if route.call_style == "creation_confirm":
        if set(payload) != {"preview_token"} or not isinstance(
            payload.get("preview_token"), str
        ):
            raise ValueError("Confirmation payload is invalid.")
        return operation(payload["preview_token"], session)
    raise RuntimeError("Invalid closed route call style.")


class WorkflowHandler(BaseHTTPRequestHandler):
    """Serve allowlisted inspection and explicitly confirmed action endpoints."""

    server_version = "WorkflowAPI/1"
    repository_root = Path(__file__).resolve().parents[1]
    creation_service: CreationService | None = None
    zeus_service: ZeusSnapshotService | None = None
    transfer_service: ZeusPreparationCoordinator | None = None
    submission_service: ZeusSmokeSubmissionCoordinator | None = None
    screening_service: ZeusScreeningCoordinator | None = None
    screen_submission_service: ZeusScreenSubmissionCoordinator | None = None
    refinement_service: ZeusRefinementCoordinator | None = None
    refinement_submission_service: ZeusRefinementSubmissionCoordinator | None = None
    confirmation_service: ZeusConfirmationCoordinator | None = None
    confirmation_submission_service: ZeusConfirmationSubmissionCoordinator | None = None
    sensitivity_service: ZeusSensitivityCoordinator | None = None
    sensitivity_submission_service: ZeusSensitivitySubmissionCoordinator | None = None
    production_service: ZeusProductionCoordinator | None = None
    production_submission_service: ZeusProductionSubmissionCoordinator | None = None
    finalization_service: ZeusFinalizationCoordinator | None = None
    mot_3d_bootstrap_service: "Mot3DDiscoveryBootstrapService | None" = None
    mot_3d_discovery_submission_service: (
        ZeusMot3DDiscoverySubmissionCoordinator | None
    ) = None
    mot_3d_discovery_transition_service: Mot3DDiscoveryTransitionCoordinator | None = (
        None
    )
    mot_3d_preliminary_submission_service: (
        Mot3DPreliminarySubmissionCoordinator | None
    ) = None
    mot_3d_refinement_submission_service: (
        Mot3DRefinementSubmissionCoordinator | None
    ) = None
    mot_3d_preliminary_transition_service: (
        Mot3DPreliminaryTransitionCoordinator | None
    ) = None
    individual_run_service: IndividualRunRegistry | None = None
    individual_zeeman_api: IndividualZeemanApi | None = None
    individual_mot_2d_api: IndividualMot2DApi | None = None
    individual_mot_3d_api: IndividualMot3DApi | None = None
    sessions: dict[str, tuple[str, float]] = {}
    sessions_lock = threading.Lock()

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._trusted_request_target():
            return
        target = urlsplit(self.path)
        path = target.path
        if target.query:
            self._catalog_error("protocol", "unsupported_query")
            return
        if path == "/api/health":
            self._json({"api_version": SCHEMA_VERSION, "status": "ok"})
            return
        if path == "/api/workflows":
            self._json(workflow_catalog_payload())
            return
        if path == "/api/v1/session":
            if (
                self.creation_service is None
                and self.mot_3d_bootstrap_service is None
                and self.mot_3d_discovery_submission_service is None
                and self.mot_3d_discovery_transition_service is None
                and self.mot_3d_preliminary_submission_service is None
                and self.mot_3d_refinement_submission_service is None
                and self.mot_3d_preliminary_transition_service is None
                and self.zeus_service is None
                and self.transfer_service is None
                and self.submission_service is None
                and self.screening_service is None
                and self.screen_submission_service is None
                and self.refinement_service is None
                and self.refinement_submission_service is None
                and self.confirmation_service is None
                and self.confirmation_submission_service is None
                and self.sensitivity_service is None
                and self.sensitivity_submission_service is None
                and self.production_service is None
                and self.production_submission_service is None
                and self.finalization_service is None
                and self.individual_zeeman_api is None
                and self.individual_mot_2d_api is None
                and self.individual_mot_3d_api is None
            ):
                self._catalog_error("protocol", "session_unavailable")
                return
            if self.headers.get("Sec-Fetch-Site") != "same-origin":
                self._catalog_error("protocol", "untrusted_origin")
                return
            now = time.monotonic()
            with type(self).sessions_lock:
                sessions = {
                    key: value
                    for key, value in type(self).sessions.items()
                    if value[1] > now
                }
                type(self).sessions = sessions
                if len(sessions) >= 64:
                    self._error(
                        "rate_limited",
                        "Too many local creation sessions.",
                        HTTPStatus.TOO_MANY_REQUESTS,
                    )
                    return
                session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                sessions[session] = (csrf, now + 600)
            self._json(
                {"api_version": SCHEMA_VERSION, "data": {"csrf_token": csrf}},
                extra_headers={
                    "Set-Cookie": f"mot_ui_session={session}; HttpOnly; SameSite=Strict; Path=/"
                },
            )
            return
        if path == "/api/v1/campaigns":
            try:
                data = list_campaigns(self.repository_root)
            except Exception:
                self._catalog_error("protocol", "inspection_failed")
                return
            self._json({"api_version": SCHEMA_VERSION, "data": data})
            return
        if path == "/api/v1/campaigns/2d/sources":
            try:
                data = list_sources(self.repository_root)
            except Exception:
                self._catalog_error("protocol", "source_inspection_failed")
                return
            self._json({"api_version": SCHEMA_VERSION, "data": data})
            return
        if path == "/api/v1/individual-runs/mot-2d/sources":
            service = self.individual_mot_2d_api
            if service is None:
                self._error(
                    "individual_mot_2d_unavailable",
                    "Individual 2D-MOT runs are unavailable.",
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return
            try:
                data = service.sources()
            except Exception:
                self._error(
                    "source_inspection_failed",
                    "2D-MOT sources could not be inspected safely.",
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._json({"api_version": SCHEMA_VERSION, "data": data})
            return
        if path == "/api/v1/individual-runs/mot-3d/sources":
            service = self.individual_mot_3d_api
            if service is None:
                self._error(
                    "individual_mot_3d_unavailable",
                    "Individual 3D-MOT runs are unavailable.",
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return
            try:
                data = service.sources()
            except Exception:
                self._error(
                    "source_inspection_failed",
                    "3D-MOT sources could not be inspected safely.",
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._json({"api_version": SCHEMA_VERSION, "data": data})
            return
        if path == "/api/v1/individual-runs":
            service = self.individual_run_service
            if service is None:
                self._error(
                    "individual_runs_unavailable",
                    "Individual-run inspection is unavailable.",
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return
            try:
                data = service.list_runs()
            except Exception:
                self._error(
                    "run_inspection_failed",
                    "Individual runs could not be inspected safely.",
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._json({"api_version": SCHEMA_VERSION, "data": data})
            return
        run_prefix = "/api/v1/individual-runs/"
        if path.startswith(run_prefix):
            encoded_id = path[len(run_prefix) :]
            if not encoded_id or "/" in encoded_id or unquote(encoded_id) != encoded_id:
                self._error(
                    "invalid_run_id",
                    "Individual-run identifier is invalid.",
                    HTTPStatus.BAD_REQUEST,
                )
                return
            service = self.individual_run_service
            if service is None:
                self._error(
                    "individual_runs_unavailable",
                    "Individual-run inspection is unavailable.",
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return
            try:
                data = service.get_run(encoded_id)
            except IndividualRunDiscoveryError as error:
                status = (
                    HTTPStatus.NOT_FOUND
                    if error.code == "run_not_found"
                    else (
                        HTTPStatus.BAD_REQUEST
                        if error.code == "invalid_run_id"
                        else HTTPStatus.INTERNAL_SERVER_ERROR
                    )
                )
                self._error(error.code, error.message, status)
                return
            except Exception:
                self._error(
                    "run_inspection_failed",
                    "Individual run could not be inspected safely.",
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._json({"api_version": SCHEMA_VERSION, "data": data})
            return
        prefix = "/api/v1/campaigns/"
        if path.startswith(prefix):
            encoded_id = path[len(prefix) :]
            if not encoded_id or "/" in encoded_id or unquote(encoded_id) != encoded_id:
                self._catalog_error("protocol", "invalid_campaign_id")
                return
            try:
                campaign = get_campaign(self.repository_root, encoded_id)
            except DiscoveryError as error:
                resolved = resolve_wire_error("local_read", error.code, error.message)
                self._error(resolved.code, resolved.message, resolved.status)
                return
            except Exception:
                self._catalog_error("protocol", "inspection_failed")
                return
            self._json({"api_version": SCHEMA_VERSION, "data": campaign})
            return
        self._catalog_error("protocol", "not_found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._trusted_request_target():
            return
        target = urlsplit(self.path)
        route = POST_ROUTES.get(target.path)
        if target.query or route is None:
            self._method_not_allowed()
            return
        service = getattr(self, route.service_attr)
        if service is None:
            self._error(
                route.unavailable_code,
                route.unavailable_message,
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        if not self._trusted_mutation_headers():
            return
        try:
            payload = self._read_json_body()
            session = self._session_id()
            data = _invoke_post_route(route, service, payload, session)
        except PermissionError:
            self._catalog_error("protocol", "invalid_preview")
            return
        except ZeusSnapshotError as error:
            resolved = resolve_error("snapshot", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except ZeusPreparationError as error:
            resolved = resolve_error("transfer", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except ZeusSubmissionError as error:
            resolved = resolve_error("smoke_submission", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except ZeusScreeningError as error:
            resolved = resolve_error("smoke_transition", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except ZeusScreenSubmissionError as error:
            resolved = resolve_error("screen_submission", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except ZeusRefinementError as error:
            resolved = resolve_error("refinement_transition", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except ZeusRefinementSubmissionError as error:
            resolved = resolve_error("refinement_submission", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except ZeusConfirmationError as error:
            resolved = resolve_error("confirmation_transition", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except ZeusConfirmationSubmissionError as error:
            resolved = resolve_error("confirmation_submission", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except ZeusSensitivityError as error:
            resolved = resolve_error("sensitivity_transition", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except ZeusSensitivitySubmissionError as error:
            resolved = resolve_error("sensitivity_submission", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except ZeusProductionError as error:
            resolved = resolve_error("production_transition", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except ZeusProductionSubmissionError as error:
            resolved = resolve_error("production_submission", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except ZeusFinalizationError as error:
            resolved = resolve_error("finalization", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except ZeusMot3DDiscoverySubmissionError as error:
            resolved = resolve_error("mot_3d_discovery_submission", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except Mot3DDiscoveryTransitionError as error:
            resolved = resolve_error("mot_3d_discovery_transition", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except Mot3DRefinementSubmissionError as error:
            resolved = resolve_error("mot_3d_refinement_submission", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except Mot3DPreliminarySubmissionError as error:
            resolved = resolve_error("mot_3d_preliminary_submission", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except Mot3DPreliminaryTransitionError as error:
            resolved = resolve_error("mot_3d_preliminary_transition", error.code)
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except ZeemanZeusError as error:
            status, message = _INDIVIDUAL_ZEUS_ERRORS.get(
                error.code,
                (
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "The individual Zeus operation stopped safely.",
                ),
            )
            code = (
                error.code
                if error.code in _INDIVIDUAL_ZEUS_ERRORS
                else "individual_zeus_failed"
            )
            self._error(code, message, status)
            return
        except BlockingIOError:
            self._catalog_error("creation", "rate_limited")
            return
        except FileExistsError:
            self._catalog_error("creation", "campaign_exists")
            return
        except ValueError as error:
            if route.service_attr == "mot_3d_bootstrap_service":
                self._error(
                    "mot_3d_bootstrap_failed",
                    "3D campaign preparation stopped safely.",
                    HTTPStatus.PRECONDITION_FAILED,
                )
                return
            resolved = resolve_wire_error("creation", "invalid_request", str(error))
            self._error(resolved.code, resolved.message, resolved.status)
            return
        except Exception:
            self._catalog_error("creation", "creation_failed")
            return
        self._json(
            {"api_version": SCHEMA_VERSION, "data": data}, status=route.success_status
        )

    def do_PUT(self) -> None:
        self._method_not_allowed()  # noqa: N802

    do_PATCH = do_PUT
    do_DELETE = do_PUT
    do_HEAD = do_PUT
    do_OPTIONS = do_PUT

    def _trusted_request_target(self) -> bool:
        target = urlsplit(self.path)
        if target.scheme or target.netloc:
            self._catalog_error("protocol", "invalid_request_target")
            return False
        host = self.headers.get("Host", "")
        hostname = host.rsplit(":", 1)[0].lower()
        if hostname not in {"127.0.0.1", "localhost"}:
            self._catalog_error("protocol", "untrusted_host")
            return False
        return True

    def _session_id(self) -> str:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("mot_ui_session")
        with type(self).sessions_lock:
            if (
                morsel is None
                or morsel.value not in type(self).sessions
                or type(self).sessions[morsel.value][1] <= time.monotonic()
            ):
                raise PermissionError("Missing session")
        return morsel.value

    def _trusted_mutation_headers(self) -> bool:
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin", "")
        if (
            origin != f"http://{host}"
            or self.headers.get("Sec-Fetch-Site") != "same-origin"
        ):
            self._catalog_error("protocol", "untrusted_origin")
            return False
        try:
            session = self._session_id()
        except PermissionError:
            self._catalog_error("protocol", "invalid_session")
            return False
        with type(self).sessions_lock:
            expected_csrf = type(self).sessions.get(session, (None, 0))[0]
        if self.headers.get("X-CSRF-Token") != expected_csrf:
            self._catalog_error("protocol", "invalid_csrf")
            return False
        return True

    def _read_json_body(self) -> dict[str, Any]:
        if self.headers.get("Content-Type", "").split(";", 1)[
            0
        ].strip().lower() != "application/json" or self.headers.get(
            "Transfer-Encoding"
        ):
            raise ValueError("A bounded JSON request body is required.")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not raw_length.isdigit():
            raise ValueError("Content-Length is required.")
        length = int(raw_length)
        if length > 32 * 1024:
            raise ValueError("Request body is too large.")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")

        def depth(value: Any, level: int = 0) -> int:
            if level > 12:
                raise ValueError("JSON body is too deeply nested.")
            if isinstance(value, dict):
                for key, child in value.items():
                    if not isinstance(key, str):
                        raise ValueError("JSON object keys must be strings.")
                    depth(child, level + 1)
            elif isinstance(value, list):
                for child in value:
                    depth(child, level + 1)
            return level

        depth(payload)
        return payload

    def _method_not_allowed(self) -> None:
        error = resolve_error("protocol", "method_not_allowed")
        self._json(
            {"error": {"code": error.code, "message": error.message}},
            status=error.status,
            extra_headers={"Allow": "GET, POST"},
        )

    def _catalog_error(self, domain: str, case: str) -> None:
        error = resolve_error(domain, case)
        self._error(error.code, error.message, error.status)

    def _error(self, code: str, message: str, status: HTTPStatus) -> None:
        self._json({"error": {"code": code, "message": message}}, status=status)

    def _json(
        self,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


# Compatibility for external imports and existing test harnesses.
ReadOnlyWorkflowHandler = WorkflowHandler


def main() -> None:
    # Keep scientific simulation/study modules behind process startup.  Merely
    # importing the HTTP contract layer must not initialize physics modules.
    from workflow_api.mot_3d_local_execution import Mot3DBoundedLocalExecutionPool
    from workflow_api.mot_3d_zeus_execution import (
        IndividualMot3DZeusCoordinator,
        PinnedSshMot3DTransport,
    )

    from workflow_api.mot_3d_bootstrap import Mot3DDiscoveryBootstrapService

    authority = issue_execution_authority()
    zeeman_creation = ZeemanRunCreationService(
        WorkflowHandler.repository_root,
        ZeemanRepositorySnapshotProvider(
            WorkflowHandler.repository_root, Path("/usr/bin/git")
        ),
    )
    zeeman_local = BoundedLocalExecutionPool(
        WorkflowHandler.repository_root,
        authority,
        max_concurrent=1,
        max_pending=4,
    )

    def zeeman_transport(profile: ZeusProfile) -> PinnedSshZeemanTransport:
        return PinnedSshZeemanTransport(
            WorkflowHandler.repository_root, Path("/usr/bin/ssh"), profile
        )

    zeeman_zeus = IndividualZeemanZeusCoordinator(
        WorkflowHandler.repository_root,
        authority,
        zeeman_transport,
    )
    WorkflowHandler.individual_zeeman_api = IndividualZeemanApi(
        zeeman_creation, zeeman_local, zeeman_zeus
    )
    mot_2d_creation = Mot2DRunCreationService(
        WorkflowHandler.repository_root,
        Mot2DIndividualRepositorySnapshotProvider(
            WorkflowHandler.repository_root, Path("/usr/bin/git")
        ),
    )
    mot_2d_local = Mot2DBoundedLocalExecutionPool(
        WorkflowHandler.repository_root,
        authority,
        max_concurrent=1,
        max_pending=4,
    )

    def mot_2d_transport(profile: ZeusProfile) -> PinnedSshMot2DTransport:
        return PinnedSshMot2DTransport(
            WorkflowHandler.repository_root, Path("/usr/bin/ssh"), profile
        )

    mot_2d_zeus = IndividualMot2DZeusCoordinator(
        WorkflowHandler.repository_root,
        authority,
        mot_2d_transport,
    )
    WorkflowHandler.individual_mot_2d_api = IndividualMot2DApi(
        WorkflowHandler.repository_root,
        mot_2d_creation,
        mot_2d_local,
        mot_2d_zeus,
    )
    mot_3d_creation = Mot3DRunCreationService(
        WorkflowHandler.repository_root,
        Mot3DIndividualRepositorySnapshotProvider(
            WorkflowHandler.repository_root, Path("/usr/bin/git")
        ),
    )
    mot_3d_local = Mot3DBoundedLocalExecutionPool(
        WorkflowHandler.repository_root,
        authority,
        max_concurrent=1,
        max_pending=4,
    )

    def mot_3d_transport(profile: ZeusProfile) -> PinnedSshMot3DTransport:
        return PinnedSshMot3DTransport(
            WorkflowHandler.repository_root, Path("/usr/bin/ssh"), profile
        )

    mot_3d_zeus = IndividualMot3DZeusCoordinator(
        WorkflowHandler.repository_root,
        authority,
        mot_3d_transport,
    )
    WorkflowHandler.individual_mot_3d_api = IndividualMot3DApi(
        WorkflowHandler.repository_root,
        mot_3d_creation,
        mot_3d_local,
        mot_3d_zeus,
    )
    WorkflowHandler.individual_run_service = CanonicalIndividualRunRegistry(
        WorkflowHandler.repository_root
    )
    WorkflowHandler.creation_service = CreationService(
        WorkflowHandler.repository_root,
        RepositorySnapshotProvider(
            WorkflowHandler.repository_root, Path("/usr/bin/git")
        ),
    )
    WorkflowHandler.mot_3d_bootstrap_service = Mot3DDiscoveryBootstrapService(
        WorkflowHandler.repository_root
    )
    WorkflowHandler.mot_3d_discovery_submission_service = (
        ZeusMot3DDiscoverySubmissionCoordinator(
            WorkflowHandler.repository_root, Path("/usr/bin/ssh"), Path("/usr/bin/git")
        )
    )
    WorkflowHandler.mot_3d_discovery_transition_service = (
        Mot3DDiscoveryTransitionCoordinator(
            WorkflowHandler.repository_root,
            Path("/usr/bin/ssh"),
            Path("/usr/bin/git"),
        )
    )
    WorkflowHandler.mot_3d_preliminary_submission_service = (
        Mot3DPreliminarySubmissionCoordinator(
            WorkflowHandler.repository_root,
            Path("/usr/bin/ssh"),
            Path("/usr/bin/git"),
        )
    )
    WorkflowHandler.mot_3d_refinement_submission_service = (
        Mot3DRefinementSubmissionCoordinator(
            WorkflowHandler.repository_root,
            Path("/usr/bin/ssh"),
            Path("/usr/bin/git"),
        )
    )
    WorkflowHandler.mot_3d_preliminary_transition_service = (
        Mot3DPreliminaryTransitionCoordinator(
            WorkflowHandler.repository_root,
            Path("/usr/bin/ssh"),
            Path("/usr/bin/git"),
        )
    )
    WorkflowHandler.zeus_service = ZeusSnapshotService(
        ZeusSnapshotProvider(WorkflowHandler.repository_root, Path("/usr/bin/ssh")),
    )
    WorkflowHandler.transfer_service = ZeusPreparationCoordinator(
        WorkflowHandler.repository_root,
        Path("/usr/bin/ssh"),
        Path("/usr/bin/git"),
    )
    WorkflowHandler.submission_service = ZeusSmokeSubmissionCoordinator(
        WorkflowHandler.repository_root,
        Path("/usr/bin/ssh"),
        Path("/usr/bin/git"),
    )
    WorkflowHandler.screening_service = ZeusScreeningCoordinator(
        WorkflowHandler.repository_root,
        Path("/usr/bin/ssh"),
        Path("/usr/bin/git"),
    )
    WorkflowHandler.screen_submission_service = ZeusScreenSubmissionCoordinator(
        WorkflowHandler.repository_root,
        Path("/usr/bin/ssh"),
        Path("/usr/bin/git"),
    )
    WorkflowHandler.refinement_service = ZeusRefinementCoordinator(
        WorkflowHandler.repository_root,
        Path("/usr/bin/ssh"),
        Path("/usr/bin/git"),
    )
    WorkflowHandler.refinement_submission_service = ZeusRefinementSubmissionCoordinator(
        WorkflowHandler.repository_root,
        Path("/usr/bin/ssh"),
        Path("/usr/bin/git"),
    )
    WorkflowHandler.confirmation_service = ZeusConfirmationCoordinator(
        WorkflowHandler.repository_root,
        Path("/usr/bin/ssh"),
        Path("/usr/bin/git"),
    )
    WorkflowHandler.confirmation_submission_service = (
        ZeusConfirmationSubmissionCoordinator(
            WorkflowHandler.repository_root,
            Path("/usr/bin/ssh"),
            Path("/usr/bin/git"),
        )
    )
    WorkflowHandler.sensitivity_service = ZeusSensitivityCoordinator(
        WorkflowHandler.repository_root,
        Path("/usr/bin/ssh"),
        Path("/usr/bin/git"),
    )
    WorkflowHandler.sensitivity_submission_service = (
        ZeusSensitivitySubmissionCoordinator(
            WorkflowHandler.repository_root,
            Path("/usr/bin/ssh"),
            Path("/usr/bin/git"),
        )
    )
    WorkflowHandler.production_service = ZeusProductionCoordinator(
        WorkflowHandler.repository_root,
        Path("/usr/bin/ssh"),
        Path("/usr/bin/git"),
    )
    WorkflowHandler.production_submission_service = ZeusProductionSubmissionCoordinator(
        WorkflowHandler.repository_root,
        Path("/usr/bin/ssh"),
        Path("/usr/bin/git"),
    )
    WorkflowHandler.finalization_service = ZeusFinalizationCoordinator(
        WorkflowHandler.repository_root,
        Path("/usr/bin/ssh"),
        Path("/usr/bin/git"),
    )
    server = ThreadingHTTPServer((HOST, PORT), WorkflowHandler)
    print(f"Local workflow API listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        try:
            mot_2d_local.close(wait=False)
        finally:
            zeeman_local.close(wait=False)


if __name__ == "__main__":
    main()
