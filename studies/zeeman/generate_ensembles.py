"""Generate canonical production ensembles with the corrected 19-ring slower."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

from config import ZEEMAN_MAGNET_PROFILES
from lab_setup.physical_specification import CANONICAL_ZEEMAN_PROFILE_NAME
from simulations.zeeman import run_and_save_zeeman


PROFILE_NAME = CANONICAL_ZEEMAN_PROFILE_NAME
OUTPUT_DIR = Path("data/particle_states/after_zeeman") / PROFILE_NAME
N_INITIAL = 50_000


def corrected_field():
    radii, positions, tilts = ZEEMAN_MAGNET_PROFILES[PROFILE_NAME]
    arrays = [np.asarray(values, dtype=float) for values in (radii, positions, tilts)]
    if [len(values) for values in arrays] != [19, 19, 19]:
        raise ValueError("Corrected Zeeman profile must contain 19 complete rings.")
    if not all(np.all(np.isfinite(values)) for values in arrays):
        raise ValueError("Corrected Zeeman profile contains non-finite values.")
    if np.any(np.diff(arrays[1]) <= 0.0):
        raise ValueError("Corrected Zeeman positions must be strictly increasing.")
    return {"radii_m": radii, "positions_m": positions, "tilt_angles_deg": tilts}


def output_path(seed, output_dir=OUTPUT_DIR, *, n_initial=N_INITIAL):
    return Path(output_dir) / f"production_zeeman_n{n_initial}_dt40us_seed{seed}.npy"


def run(seed, npools=200, output_dir=OUTPUT_DIR, *, acceptance_profile=None, input_manifest=None, input_generation_plan=None):
    if input_manifest is not None and input_generation_plan is not None:
        raise ValueError("Choose either a campaign manifest or an initial input-generation plan.")
    profile = None
    expected_commit = None
    input_record = input_generation_plan if input_generation_plan is not None else input_manifest
    n_initial = N_INITIAL
    if acceptance_profile is not None:
        from workflow_api.acceptance_profile import (
            assert_acceptance_path, load_acceptance_profile, policy_for_manifest,
        )
        profile = load_acceptance_profile(acceptance_profile)
        if input_record is None:
            raise ValueError("Acceptance generation requires a frozen campaign or initial input-generation plan.")
        assert_acceptance_path(input_record, Path.cwd())
        assert_acceptance_path(output_dir, Path.cwd())
        if input_generation_plan is not None:
            from workflow_api.acceptance_inputs import validate_input_generation_plan
            plan = validate_input_generation_plan(input_generation_plan, Path.cwd(), output_directory=output_dir, seed=seed, npools=npools)
            expected_commit = plan['code']['git_commit']
        else:
            manifest = json.loads(Path(input_manifest).read_text(encoding="utf-8"))
            if policy_for_manifest(manifest) != profile:
                raise ValueError("Acceptance generation profile does not match the campaign.")
            if npools != 1:
                raise ValueError("Acceptance generation requires exactly one CPU worker.")
            allowed_seeds = profile.family('mot_3d')['final_validation_zeeman_seeds']
            if seed not in allowed_seeds:
                raise ValueError("Fresh acceptance seed is not in the sealed validation registry.")
            from workflow_api.mot_3d_workload import policy as campaign_policy
            if campaign_policy(manifest) != profile:
                raise ValueError('Fresh acceptance generation requires an authenticated 3D campaign.')
            expected_commit = manifest.get('provenance', {}).get('git_commit')
            if not isinstance(expected_commit, str) or re.fullmatch(r'[0-9a-f]{40}', expected_commit) is None:
                raise ValueError('Acceptance campaign generation requires a valid frozen Git commit.')
            from workflow_api.acceptance_inputs import code_identity
            if code_identity(Path.cwd())['git_commit'] != expected_commit:
                raise ValueError('Acceptance campaign generation code differs from its frozen commit.')
        n_initial = profile.policy['generation']['zeeman_initial_particles']
    elif input_record is not None or "ui_acceptance" in Path(output_dir).parts:
        raise ValueError("Acceptance generation requires an explicit reviewed profile.")
    path = output_path(seed, output_dir, n_initial=n_initial)
    metadata = path.with_suffix(".json")
    if path.exists() and metadata.exists():
        if profile is not None:
            _validate_completed(path, input_record, seed, n_initial, profile, expected_commit)
        print(f"Skipping complete corrected Zeeman ensemble seed {seed}: {path}")
        return path
    if profile is not None and (path.exists() or metadata.exists()):
        raise ValueError("Partial acceptance ensemble requires inspection before retry.")
    path.parent.mkdir(parents=True, exist_ok=True)
    controlled_origin = None
    controlled_arguments = {}
    if profile is not None and 'controlled_input_recipe' in profile.policy['generation']:
        from workflow_api.acceptance_inputs import controlled_initial_states
        states, controlled_origin = controlled_initial_states(seed, profile)
        controlled_arguments['initial_states'] = states
    run_and_save_zeeman(
        path,
        N_particles=n_initial,
        seed=seed,
        dt=4e-5,
        npools=npools,
        stochastic=True,
        collimation_angle_deg=1.5,
        zeeman_field_config=corrected_field(),
        **controlled_arguments,
    )
    if profile is not None:
        from utils.file_helpers import save_file_json
        payload = json.loads(metadata.read_text(encoding="utf-8"))
        payload['acceptance'] = profile.provenance()
        if controlled_origin is not None:
            payload['controlled_input_origin'] = controlled_origin
        if input_generation_plan is not None:
            from workflow_api.acceptance_inputs import file_digest, KIND
            payload['input_generation'] = {
                'kind': KIND, 'plan_sha256': plan['plan_sha256'],
                'plan_file_sha256': file_digest(Path(input_generation_plan)),
            }
        save_file_json(metadata, payload)
        _publish_completion(path, input_record, seed, n_initial, profile, expected_commit)
    return path



def _completion_record(path, input_record, seed, n_initial, profile, expected_commit):
    from workflow_api.acceptance_inputs import file_digest, validate_ensemble
    validate_ensemble(path, seed=seed, n_initial=n_initial, acceptance=profile.provenance(), expected_commit=expected_commit)
    return {'kind': 'zeeman_ui_acceptance_generation_completion_v1',
            'acceptance': profile.provenance(), 'seed': seed,
            'input_record_sha256': file_digest(Path(input_record)),
            'array_sha256': file_digest(path), 'metadata_sha256': file_digest(path.with_suffix('.json'))}


def _receipt_path(input_record, seed):
    return Path(input_record).parent / 'generation_receipts' / f'seed_{seed}.json'


def _validate_completed(path, input_record, seed, n_initial, profile, expected_commit):
    from workflow_api.acceptance_inputs import read_record
    expected = _completion_record(path, input_record, seed, n_initial, profile, expected_commit)
    receipt = _receipt_path(input_record, seed)
    if read_record(receipt) != expected:
        raise ValueError('Acceptance completion hashes changed; resume is blocked.')


def _publish_completion(path, input_record, seed, n_initial, profile, expected_commit):
    value = _completion_record(path, input_record, seed, n_initial, profile, expected_commit)
    receipt = _receipt_path(input_record, seed)
    if receipt.exists() or receipt.is_symlink():
        raise ValueError('An existing acceptance completion receipt cannot be replaced.')
    receipt.parent.mkdir(parents=True, exist_ok=True)
    if receipt.parent.is_symlink():
        raise ValueError('Unsafe acceptance receipt directory.')
    import os
    with receipt.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--npools", type=int, default=200)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--acceptance-profile")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--input-manifest")
    inputs.add_argument("--input-generation-plan")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    run(args.seed, args.npools, args.output_dir, acceptance_profile=args.acceptance_profile,
        input_manifest=args.input_manifest, input_generation_plan=args.input_generation_plan)
