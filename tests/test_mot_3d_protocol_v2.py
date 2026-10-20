"""New campaigns use 50 ms/5 us without rewriting historical evidence."""
import importlib
import json
from argparse import Namespace
from pathlib import Path
import shutil

import pytest

from config import MOT_2D_SIM_CONFIG, MOT_3D_SIM_CONFIG
from lab_setup.mot_3d_timestep_policy import MOT_3D_TIMESTEP_POLICY
from studies.mot_3d.final_validation import merge, run
from workflow_api import mot_3d_stage_topology as topology


def test_current_and_historical_protocols_are_distinct_and_2d_is_unchanged():
    historical = json.loads(Path('lab_setup/specifications/mot_3d_timestep_policy_v1.json').read_text())
    assert historical['sealed_final_validation_dt_s'] == 0.625e-6
    assert MOT_3D_TIMESTEP_POLICY['sealed_final_validation_dt_s'] == 5e-6
    assert MOT_3D_TIMESTEP_POLICY['t_max_s'] == .05
    assert MOT_3D_SIM_CONFIG['production_dt_s'] == 5e-6
    assert MOT_3D_SIM_CONFIG['t_max_s'] == .05
    assert MOT_2D_SIM_CONFIG['dt_s'] == .625e-6
    assert MOT_2D_SIM_CONFIG['t_max_s'] == .025
    for policy in (topology.PRELIMINARY_SCIENTIFIC_DESIGN,
                   topology.CLOSURE_SCIENTIFIC_DESIGN,
                   topology.FINALIST_SELECTION_SCIENTIFIC_DESIGN,
                   topology.FINAL_VALIDATION_SCIENTIFIC_DESIGN):
        assert policy.t_max_s == .05
    assert topology.FINAL_VALIDATION_SCIENTIFIC_DESIGN.dt_s == 5e-6


@pytest.mark.parametrize('stage,extra', [
    ('preliminary.run', ['--worker-index', '0']),
    ('refinement.run', ['--worker-index', '0']),
    ('finalists.run', ['--finalist-index', '0']),
])
def test_stage_cli_defaults_match_reviewed_policy(stage, extra):
    module = importlib.import_module('studies.mot_3d.' + stage)
    args = module.parse_args(['--family', 'angled_donut', '--selection', 'selection.json',
                              '--input-manifest', 'campaign.json', '--output-dir', 'unused', *extra])
    assert args.t_max == .05
    assert args.dt == 10e-6


def test_discovery_cli_default_is_50ms():
    from studies.mot_3d.discovery.optimize import parse_args
    args = parse_args(['--family', 'angled_donut', '--worker-index', '0',
                       '--target-completed-trials', '1', '--output-dir', 'unused',
                       '--input', 'unused.npy', '--sampler-seed', '1'])
    assert args.t_max == .05


def test_final_validation_rejects_100ms_before_loading_states(tmp_path):
    campaign = tmp_path/'campaign.json'
    locked = tmp_path/'locked.json'
    campaign.write_text(json.dumps({'design': {'production_dt_s': 5e-6}}))
    locked.write_text('{}')
    args = Namespace(locked_nominals=locked, campaign_manifest=campaign, dt=5e-6, t_max=.1)
    with pytest.raises(ValueError, match='endpoint'):
        run(args)


def test_large_valid_archive_uses_scoped_limit_without_relaxing_preliminary():
    from workflow_api.mot_3d_preliminary_results import (
        PreliminaryResultError, validate_npz_container_bytes,
    )
    raw = Path('data/validation/mot_3d/final_campaign_20261020/'
               'final_validation_5us_50ms/angled_donut/seed_44001.npz').read_bytes()
    with pytest.raises(PreliminaryResultError):
        validate_npz_container_bytes(raw)
    validate_npz_container_bytes(raw, max_member_bytes=2 * 1024 * 1024)
    for limit in (True, 0, -1, 2 * 1024 * 1024 + 1):
        with pytest.raises(PreliminaryResultError):
            validate_npz_container_bytes(raw, max_member_bytes=limit)


@pytest.mark.parametrize('old_value', [None, 'old_endpoint', 'old_timestep'])
def test_real_saved_outcomes_merge_at_50ms_and_reject_legacy_mixing(tmp_path, old_value):
    source = Path('data/validation/mot_3d/final_campaign_20261020')
    root = tmp_path/'results'
    root.mkdir()
    for name in ('campaign', 'locked', 'inputs'):
        original = {'campaign': source/'validation_5us_50ms_manifest.json',
                    'locked': source/'selection/locked_nominals.json',
                    'inputs': source/'final_validation_inputs/input_manifest.json'}[name]
        shutil.copyfile(original, tmp_path/f'{name}.json')
    for seed in (44001, 44002, 44003):
        original = source/f'final_validation_5us_50ms/angled_donut/seed_{seed}.json'
        row = json.loads(original.read_text())
        archive = root/f'seed_{seed}.npz'
        shutil.copyfile(original.with_suffix('.npz'), archive)
        row['outcomes_path'] = str(archive)
        if old_value == 'old_endpoint':
            row['design']['t_max_s'] = .1
        elif old_value == 'old_timestep':
            row['design']['dt_s'] = .625e-6
        (root/f'seed_{seed}.json').write_text(json.dumps(row))
    args = Namespace(input_root=root, output=tmp_path/'summary.json', family='angled_donut',
                     campaign_manifest=tmp_path/'campaign.json', locked_nominals=tmp_path/'locked.json',
                     input_manifest=tmp_path/'inputs.json', dt=5e-6,
                     bootstrap_replicates=30, bootstrap_seed=92001)
    if old_value:
        with pytest.raises(ValueError, match='Foreign or stale'):
            merge(args)
        assert not args.output.exists()
    else:
        merge(args)
        summary = json.loads(args.output.read_text())
        assert summary['design']['t_max_s'] == .05
        assert summary['design']['dt_s'] == 5e-6
        assert summary['conditional_efficiency'] == pytest.approx(.9976611694152924)
