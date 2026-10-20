"""Explicit, immutable workload policies for isolated physical UI acceptance.

No environment variables or process-global overrides alter scientific defaults.
Callers must authenticate each manifest and propagate its identity to artifacts.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

PROFILE_ID = 'ui_acceptance_v1'
PROFILE_SHA256 = 'f4f666548ada90aab2938878822dfe5173a140496cadbd7baba68144ad873148'
ACCEPTANCE_KINDS = MappingProxyType({'mot_2d': 'mot_2d_ui_acceptance_v1', 'mot_3d': 'mot_3d_ui_acceptance_v1'})
SCIENTIFIC_KINDS = frozenset(('mot_2d_s0_campaign', 'mot_3d_campaign_v2'))


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate acceptance policy field.')
        result[key] = value
    return result


def physical_identity() -> dict[str, str]:
    from lab_setup.physical_specification import LABORATORY_SPEC_SHA256, CANONICAL_ZEEMAN_PROFILE_SHA256
    from lab_setup.numerical_policy import NUMERICAL_POLICY_SHA256
    from lab_setup.mot_3d_timestep_policy import MOT_3D_TIMESTEP_POLICY_SHA256
    return {'laboratory_spec_sha256': LABORATORY_SPEC_SHA256,
            'zeeman_profile_sha256': CANONICAL_ZEEMAN_PROFILE_SHA256,
            'numerical_policy_sha256': NUMERICAL_POLICY_SHA256,
            'mot_3d_timestep_policy_sha256': MOT_3D_TIMESTEP_POLICY_SHA256}


@dataclass(frozen=True)
class AcceptanceProfile:
    profile_id: str
    sha256: str
    policy: Mapping[str, Any]

    def family(self, family: str) -> Mapping[str, Any]:
        if family not in ACCEPTANCE_KINDS:
            raise ValueError('Unknown acceptance family.')
        return self.policy[family]

    def stage(self, family: str, stage: str) -> Mapping[str, Any]:
        try:
            return self.family(family)['stages'][stage]
        except KeyError as error:
            raise ValueError('Unknown acceptance stage.') from error

    def provenance(self) -> dict[str, Any]:
        return {'profile_id': self.profile_id, 'profile_sha256': self.sha256,
                'suitability': 'acceptance_only', 'physical_identity': physical_identity()}


def load_acceptance_profile(profile_id: str = PROFILE_ID) -> AcceptanceProfile:
    if profile_id != PROFILE_ID:
        raise ValueError('Unknown acceptance profile.')
    path = Path(__file__).with_name('specifications') / f'{PROFILE_ID}.json'
    value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_unique)
    if _digest(value) != PROFILE_SHA256:
        raise ValueError('Acceptance policy differs from its reviewed immutable version.')
    from lab_setup.numerical_policy import NUMERICAL_POLICY
    from lab_setup.mot_3d_timestep_policy import MOT_3D_TIMESTEP_POLICY
    physics = value['physics']
    expected = {
        'solver_2d': NUMERICAL_POLICY['mot_2d']['solver'], 'working_dt_2d_s': 1.25e-6,
        'final_dt_2d_s': NUMERICAL_POLICY['mot_2d']['dt_s'], 't_max_2d_s': NUMERICAL_POLICY['mot_2d']['t_max_s'],
        'solver_3d': MOT_3D_TIMESTEP_POLICY['solver'], 'search_dt_3d_s': MOT_3D_TIMESTEP_POLICY['search_dt_s'],
        'final_dt_3d_s': MOT_3D_TIMESTEP_POLICY['sealed_final_validation_dt_s'], 't_max_3d_s': MOT_3D_TIMESTEP_POLICY['t_max_s'],
        'zeeman_dt_s': NUMERICAL_POLICY['zeeman']['dt_s'], 'zeeman_t_max_s': NUMERICAL_POLICY['zeeman']['t_max_s'],
    }
    if physics != expected:
        raise ValueError('Acceptance physics no longer matches the canonical physical policy.')
    return AcceptanceProfile(PROFILE_ID, PROFILE_SHA256, _freeze(value))


def is_acceptance_manifest(manifest: Mapping[str, Any]) -> bool:
    return manifest.get('kind') in ACCEPTANCE_KINDS.values()


def policy_for_manifest(manifest: Mapping[str, Any]) -> AcceptanceProfile | None:
    """Return None for unchanged scientific policy; fail closed on mixed identity."""
    marker = manifest.get('acceptance')
    if not is_acceptance_manifest(manifest):
        if 'acceptance' in manifest or manifest.get('suitability') == 'acceptance_only':
            raise ValueError('Acceptance provenance cannot use a scientific or unknown kind.')
        if manifest.get('kind') not in SCIENTIFIC_KINDS:
            raise ValueError('Unknown campaign kind.')
        return None
    profile = load_acceptance_profile()
    if not isinstance(marker, Mapping) or dict(marker) != profile.provenance():
        raise ValueError('Acceptance manifest lacks exact reviewed profile and physical provenance.')
    return profile


def stage_policy(manifest: Mapping[str, Any], stage: str) -> Mapping[str, Any] | None:
    profile = policy_for_manifest(manifest)
    if profile is None:
        return None
    family = next(family for family, kind in ACCEPTANCE_KINDS.items() if kind == manifest['kind'])
    return profile.stage(family, stage)


def assert_acceptance_path(path: str | Path, repository_root: str | Path) -> Path:
    """Allow only dedicated acceptance descendants, including symlink resolution."""
    root = Path(repository_root).resolve()
    target = Path(path)
    target = (root / target).resolve() if not target.is_absolute() else target.resolve()
    allowed = ('data/acceptance', 'data/optimization/mot_2d/ui_acceptance',
               'data/optimization/mot_3d/ui_acceptance', 'data/particle_states/after_zeeman/ui_acceptance',
               'data/particle_states/after_mot_2d/ui_acceptance')
    if not any(target.is_relative_to(root / prefix) and target != root / prefix for prefix in allowed):
        raise ValueError('Acceptance output must be inside a dedicated acceptance directory.')
    return target


def assert_scientific_source(value: Mapping[str, Any]) -> None:
    """Promotion boundary: reject acceptance lineage, including nested artifacts."""
    def marked(item):
        if isinstance(item, Mapping):
            if ('acceptance' in item or item.get('kind') in ACCEPTANCE_KINDS.values()
                    or item.get('suitability') == 'acceptance_only'
                    or item.get('profile_id') == PROFILE_ID):
                return True
            return any(marked(child) for child in item.values())
        if isinstance(item, (list, tuple)):
            return any(marked(child) for child in item)
        return False
    if marked(value):
        raise ValueError('TEST ONLY acceptance artifacts cannot be promoted as scientific sources.')


def assert_same_acceptance_lineage(parent: Mapping[str, Any], child: Mapping[str, Any]) -> None:
    """Both sides must be acceptance, with the exact same reviewed identity."""
    if policy_for_manifest(parent) is None or policy_for_manifest(child) is None:
        raise ValueError('Acceptance lineage cannot cross into a scientific campaign.')
    if parent['acceptance'] != child['acceptance']:
        raise ValueError('Acceptance profile lineage changed.')
