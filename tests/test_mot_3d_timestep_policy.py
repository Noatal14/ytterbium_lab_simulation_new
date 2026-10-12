import json
from types import MappingProxyType

import pytest

from config import MOT_3D_SIM_CONFIG
from lab_setup.mot_3d_timestep_policy import (
    MOT_3D_TIMESTEP_POLICY,
    MOT_3D_TIMESTEP_POLICY_SHA256,
    MOT_3D_TIMESTEP_POLICY_VERSION,
    _validate,
)


def _payload():
    def thaw(value):
        if isinstance(value, MappingProxyType):
            return {key: thaw(child) for key, child in value.items()}
        if isinstance(value, tuple):
            return [thaw(child) for child in value]
        return value

    return thaw(MOT_3D_TIMESTEP_POLICY)


def test_policy_is_immutable_nonconverged_and_matches_runtime():
    assert isinstance(MOT_3D_TIMESTEP_POLICY, MappingProxyType)
    assert MOT_3D_TIMESTEP_POLICY_VERSION == "mot-3d-timestep-policy-v1"
    assert len(MOT_3D_TIMESTEP_POLICY_SHA256) == 64
    assert MOT_3D_TIMESTEP_POLICY["convergence_claim"] == "not_established"
    assert MOT_3D_TIMESTEP_POLICY["search_dt_s"] == 10e-6
    assert MOT_3D_TIMESTEP_POLICY["sealed_final_validation_dt_s"] == 0.625e-6
    assert MOT_3D_SIM_CONFIG["screening_dt_s"] == 10e-6
    assert MOT_3D_SIM_CONFIG["production_dt_s"] == 0.625e-6
    assert MOT_3D_TIMESTEP_POLICY["decision"]["requires_new_campaign"] is True
    assert (
        MOT_3D_TIMESTEP_POLICY["decision"]["legacy_campaign_mutation_forbidden"]
        is True
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update(search_dt_s=True),
        lambda row: row.update(search_dt_s=5e-6),
        lambda row: row.update(convergence_claim="established"),
        lambda row: row["decision"].update(requires_new_campaign=False),
        lambda row: row["inconclusive_evidence"].update(status="approved"),
        lambda row: row["inconclusive_evidence"].update(evidence_sha256="NOT-A-HASH"),
        lambda row: row.update(extra=True),
    ],
)
def test_policy_rejects_scientific_or_schema_drift(mutation):
    payload = _payload()
    mutation(payload)
    with pytest.raises(ValueError):
        _validate(payload)
