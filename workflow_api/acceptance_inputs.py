"""Honest, immutable input-generation plans preceding acceptance campaigns.

A plan is not a campaign and cannot be passed to the campaign manifest codec.
Its outputs are produced by the ordinary physical Zeeman worker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from workflow_api.acceptance_profile import assert_acceptance_path, load_acceptance_profile

KIND = 'zeeman_ui_acceptance_input_generation_v1'


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate input-generation plan field.')
        value[key] = item
    return value


def read_record(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Unsafe input-generation record.')
    value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_unique)
    if not isinstance(value, dict):
        raise ValueError('Input-generation record must be an object.')
    return value


def code_identity(repository_root: Path) -> dict[str, Any]:
    """Freeze the complete local physics/policy closure, requiring a clean commit."""
    root = Path(repository_root).resolve()
    names = {'config.py', 'studies/zeeman/generate_ensembles.py',
             'workflow_api/acceptance_inputs.py', 'workflow_api/acceptance_profile.py',
             'workflow_api/specifications/ui_acceptance_v1.json'}
    for directory in ('lab_setup', 'simulations', 'utils', 'atomsmltr/src/atomsmltr'):
        for pattern in ('*.py', '*.json'):
            names.update(path.relative_to(root).as_posix() for path in (root / directory).rglob(pattern))
    ordered = sorted(names)
    tracked = subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--'], cwd=root, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if tracked.returncode != 0:
        raise ValueError('Commit tracked changes before freezing or executing acceptance inputs.')
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *ordered], cwd=root, text=True).strip():
        raise ValueError('Commit the input-generation code and physical policy before freezing a plan.')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    return {'git_commit': commit, 'files': {name: file_digest(root / name) for name in ordered}}


def _body(root: Path, output_directory: str | Path) -> dict[str, Any]:
    profile = load_acceptance_profile()
    output = assert_acceptance_path(output_directory, root)
    expected_root = root / 'data/particle_states/after_zeeman/ui_acceptance'
    if not output.is_relative_to(expected_root) or output == expected_root:
        raise ValueError('Initial acceptance inputs require their dedicated Zeeman source directory.')
    return {'kind': KIND, 'acceptance': profile.provenance(), 'suitability': 'acceptance_only',
            'purpose': 'physical_initial_inputs_not_a_campaign', 'code': code_identity(root),
            'generation': {'seeds': list(range(3000, 3035)),
                           'n_initial_atoms': profile.policy['generation']['zeeman_initial_particles'],
                           'npools': 1, 'dt_s': profile.policy['physics']['zeeman_dt_s'],
                           't_max_s': profile.policy['physics']['zeeman_t_max_s'],
                           'stochastic': True, 'collimation_angle_deg': 1.5,
                           'minimum_survivors_per_ensemble': profile.policy['generation']['minimum_survivors_per_ensemble']},
            'output_directory': output.relative_to(root).as_posix(),
            'controlled_input_recipe': (dict(profile.policy['generation']['controlled_input_recipe'])
                                        if 'controlled_input_recipe' in profile.policy['generation'] else None),
            'scheduler': dict(profile.policy.get('scheduler', {})),
            'resources': (dict(profile.policy['generation']['jobs']['zeeman'])
                          if 'jobs' in profile.policy['generation'] else
                          {'npools': 1, 'ncpus': 1, 'memory_gb': 4, 'walltime_seconds': 3600})}


def build_input_generation_plan(repository_root: Path, output_directory: str | Path) -> dict[str, Any]:
    body = _body(Path(repository_root).resolve(), output_directory)
    return {**body, 'plan_sha256': digest(body)}


def save_input_generation_plan(repository_root: Path, destination: str | Path,
                               output_directory: str | Path) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    path = assert_acceptance_path(destination, root)
    if not path.is_relative_to(root / 'data/acceptance') or path.suffix != '.json':
        raise ValueError('Input-generation plans belong under data/acceptance/<run>/*.json.')
    value = build_input_generation_plan(root, output_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + '\n')
    return value


def validate_input_generation_plan(path: str | Path, repository_root: Path,
                                   *, output_directory: str | Path | None = None,
                                   seed: int | None = None, npools: int = 1) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    plan_path = assert_acceptance_path(path, root)
    if not plan_path.is_relative_to(root / 'data/acceptance'):
        raise ValueError('Input-generation plan is outside its dedicated namespace.')
    value = read_record(plan_path)
    if value.get('kind') != KIND:
        raise ValueError('Expected an input-generation plan, not a campaign manifest.')
    expected = build_input_generation_plan(root, value.get('output_directory', ''))
    if value != expected or digest({key: item for key, item in value.items() if key != 'plan_sha256'}) != value.get('plan_sha256'):
        raise ValueError('Input-generation plan, code, or physical policy changed.')
    if output_directory is not None and assert_acceptance_path(output_directory, root) != root / value['output_directory']:
        raise ValueError('Input-generation output differs from its frozen plan.')
    if npools != value['generation']['npools'] or (seed is not None and (isinstance(seed, bool) or seed not in value['generation']['seeds'])):
        raise ValueError('Input-generation seed or resource request differs from its frozen plan.')
    return value


def validate_ensemble(path: Path, *, seed: int, n_initial: int, acceptance: dict,
                      expected_commit: str | None = None) -> dict[str, Any]:
    """Validate the full reusable array and its adjacent physical metadata."""
    import numpy as np
    from lab_setup.physical_specification import CANONICAL_ZEEMAN_PROFILE_NAME, attest_canonical_zeeman_metadata
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Unsafe acceptance survivor array.')
    metadata = read_record(path.with_suffix('.json'))
    parameters = metadata.get('parameters', {})
    array = np.load(path, allow_pickle=False, mmap_mode='r')
    required = {'seed': seed, 'n_initial_atoms': n_initial, 'dt_s': 4e-5,
                'stochastic': True, 'npools': 1, 'gravity_enabled': True,
                'collimation_angle_deg': 1.5, 'full_angular_distribution': False,
                'angular_broadening_factor': 1.0,
                'resolved_zeeman_magnet_profile': CANONICAL_ZEEMAN_PROFILE_NAME}
    if (metadata.get('kind') != 'zeeman_survivor_ensemble' or metadata.get('acceptance') != acceptance
            or any(parameters.get(key) != value for key, value in required.items())
            or metadata.get('output_file') != path.name or metadata.get('output_sha256') != file_digest(path)
            or array.ndim != 2 or array.shape[1] != 6 or str(array.dtype) != 'float64'
            or not np.all(np.isfinite(array)) or len(array) > n_initial
            or metadata.get('shape') != list(array.shape) or metadata.get('dtype') != str(array.dtype)
            or metadata.get('n_survivors') != len(array)
            or metadata.get('survival_fraction') != len(array) / n_initial
            or (expected_commit is not None and (metadata.get('software', {}).get('git_commit') != expected_commit
                or metadata.get('software', {}).get('tracked_worktree_was_dirty') is not False))):
        raise ValueError('Acceptance ensemble metadata or array integrity changed.')
    attest_canonical_zeeman_metadata(metadata, allow_legacy=False)
    from workflow_api.acceptance_profile import policy_for_marker
    profile = policy_for_marker(acceptance)
    if 'controlled_input_recipe' in profile.policy['generation']:
        _, origin = controlled_initial_states(seed, profile)
        expected_explicit = {'kind': 'explicit_initial_states', 'suitability': 'acceptance_only',
                             'thermal_sampler_used': False,
                             'initial_state_sha256': origin['initial_state_sha256'],
                             'particle_count': n_initial}
        if metadata.get('controlled_input_origin') != origin or metadata.get('input_origin') != expected_explicit:
            raise ValueError('Controlled physical input origin differs from the reviewed seeded recipe.')
    return metadata



def controlled_initial_states(seed: int, profile=None):
    """Generate only the reviewed, seeded controlled INPUTS; no result fabrication."""
    import numpy as np
    from config import ZEEMAN_BEAM_DIRECTION, ZEEMAN_SIM_CONFIG
    profile = load_acceptance_profile() if profile is None else profile
    recipe = profile.policy['generation']['controlled_input_recipe']
    if isinstance(seed, bool) or seed not in range(3000, 3055):
        raise ValueError('Controlled input seed is outside the reviewed independent registries.')
    count = profile.policy['generation']['zeeman_initial_particles']
    rng = np.random.Generator(np.random.PCG64(seed))
    axis = np.asarray(ZEEMAN_BEAM_DIRECTION, dtype=np.float64)
    vertical = np.array([1.0, 0.0, 0.0])
    transverse = np.cross(axis, vertical)
    def sample(size):
        distance = (ZEEMAN_SIM_CONFIG['cutoff_distance_m'] + recipe['upstream_offset_m']
                    + rng.uniform(-recipe['longitudinal_jitter_m'], recipe['longitudinal_jitter_m'], size))
        positions = distance[:, None] * axis
        positions += rng.uniform(-recipe['radial_jitter_m'], recipe['radial_jitter_m'], (size, 1)) * vertical
        positions += rng.uniform(-recipe['radial_jitter_m'], recipe['radial_jitter_m'], (size, 1)) * transverse
        speed = recipe['speed_m_s'] + rng.uniform(-recipe['speed_jitter_m_s'], recipe['speed_jitter_m_s'], size)
        velocities = -speed[:, None] * axis
        velocities += rng.uniform(-recipe['transverse_speed_jitter_m_s'], recipe['transverse_speed_jitter_m_s'], (size, 1)) * vertical
        velocities += rng.uniform(-recipe['transverse_speed_jitter_m_s'], recipe['transverse_speed_jitter_m_s'], (size, 1)) * transverse
        return np.concatenate((positions, velocities), axis=1)
    admitted = recipe['admitted_particles']
    if not isinstance(admitted, int) or isinstance(admitted, bool) or not 1 <= admitted <= count:
        raise ValueError('Controlled input admission count must lie within the frozen particle count.')
    near_axis = sample(admitted)
    off_aperture = sample(count - admitted)
    off_aperture[:, :3] += recipe['off_aperture_radius_m'] * vertical
    from config import Geometry
    if np.any(np.linalg.norm(off_aperture[:, :3] - (off_aperture[:, :3] @ axis)[:, None] * axis, axis=1) <= Geometry.ZEEMAN_ARM_1_RADIUS_M):
        raise ValueError('Rejection controls must start outside the physical arm aperture.')
    states = np.ascontiguousarray(np.concatenate((near_axis, off_aperture), axis=0), dtype='<f8')
    if (not np.all(np.isfinite(states)) or np.any(states[:, :3] @ axis <= ZEEMAN_SIM_CONFIG['cutoff_distance_m'])
            or np.any(states[:, 3:] @ axis >= 0.0)):
        raise ValueError('Controlled initial states must propagate from upstream through the physical cutoff.')
    origin = {'kind': 'controlled_zeeman_initial_states', 'recipe_version': recipe['recipe_version'],
              'recipe': json.loads(json.dumps(dict(recipe))), 'seed': seed, 'particle_count': count,
              'cutoff_distance_m': ZEEMAN_SIM_CONFIG['cutoff_distance_m'], 'beam_direction': axis.tolist(),
              'initial_state_sha256': hashlib.sha256(states.tobytes(order='C')).hexdigest(),
              'suitability': 'acceptance_only'}
    return states, origin

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create')
    create.add_argument('--plan', required=True)
    create.add_argument('--output-dir', required=True)
    check = commands.add_parser('validate')
    check.add_argument('--plan', required=True)
    arguments = parser.parse_args()
    root = Path.cwd()
    if arguments.command == 'create':
        value = save_input_generation_plan(root, arguments.plan, arguments.output_dir)
    else:
        value = validate_input_generation_plan(arguments.plan, root)
        minimum = value['generation']['minimum_survivors_per_ensemble']
        for seed in value['generation']['seeds']:
            path = root / value['output_directory'] / f'production_zeeman_n32_dt40us_seed{seed}.npy'
            from studies.zeeman.generate_ensembles import _validate_completed
            _validate_completed(path, arguments.plan, seed, 32, load_acceptance_profile(), value['code']['git_commit'])
            metadata = validate_ensemble(path, seed=seed, n_initial=32, acceptance=value['acceptance'], expected_commit=value['code']['git_commit'])
            if metadata['n_survivors'] < minimum:
                raise ValueError(f'Seed {seed} has insufficient physical survivors; no input qualification was granted.')
    print(json.dumps({'kind': value['kind'], 'plan_sha256': value['plan_sha256'], 'suitability': 'acceptance_only'}))


if __name__ == '__main__':
    main()
