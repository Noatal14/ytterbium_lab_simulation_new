"""Static workflow catalog for application discovery."""

from __future__ import annotations

from workflow_api.models import WorkflowDescriptor


_WORKFLOWS = (
    WorkflowDescriptor(
        workflow_id="mot_2d_fixed_s0",
        label="2D MOT fixed-s0 campaign",
        maturity="active",
        entrypoint="studies.mot_2d_s0_campaign",
        capabilities=("inspect",),
        notes="Manifest-driven and resumable; the UI API is currently read-only.",
    ),
    WorkflowDescriptor(
        workflow_id="mot_3d_optimization",
        label="3D MOT optimization studies",
        maturity="provisional",
        entrypoint="studies.submit_3d_mot_weekly_discovery",
        capabilities=(),
        notes="Scientific workflow is still evolving; UI submission is intentionally disabled.",
    ),
    WorkflowDescriptor(
        workflow_id="zeeman_validation",
        label="Zeeman validation tools",
        maturity="reusable-validation",
        entrypoint="studies.validate_zeeman_configuration",
        capabilities=(),
        notes="Validation commands remain independent CLI tools.",
    ),
)


def list_workflows() -> tuple[WorkflowDescriptor, ...]:
    """Return the supported workflows without importing simulation modules."""
    return _WORKFLOWS
