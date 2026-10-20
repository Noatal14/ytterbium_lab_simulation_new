"""Regression gate for the archived, owner-accepted final scientific result."""
import hashlib
import io
import json
from pathlib import Path
import tarfile

import numpy as np


ROOT = Path(__file__).resolve().parents[1] / 'data/validation/mot_3d/final_campaign_20261020'


def test_closed_campaign_artifact_hashes_and_original_manifest():
    closure = json.loads((ROOT / 'closure.json').read_text())
    assert closure['status'] == 'closed_with_approved_protocol_amendment'
    assert closure['additional_jobs_authorized'] is False
    assert closure['protocol']['dt_s'] == 5e-6
    assert closure['protocol']['t_max_s'] == .05
    assert json.loads((ROOT / 'campaign.json').read_text())['stage'] == 'final_validation'
    for name, digest in closure['artifact_sha256'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    assert closure['results']['single_pass']['precision_target_met'] is False
    assert closure['precision_exception']['accepted_by']
    assert closure['software_release']['mac_windows_zeus_manual_acceptance_claimed'] is False


def test_archived_checkpoints_equal_all_published_outcomes():
    closure = json.loads((ROOT / 'closure.json').read_text())
    inputs = json.loads((ROOT / 'final_validation_inputs/input_manifest.json').read_text())
    states = []
    with tarfile.open(ROOT / 'sealed_inputs.tar.gz', 'r:gz') as sealed:
        for row in inputs['ensembles']:
            name = 'final_validation_inputs/after_2d_mot/' + Path(row['path']).name
            raw = sealed.extractfile(name).read()
            assert hashlib.sha256(raw).hexdigest() == row['sha256']
            values = np.load(io.BytesIO(raw), allow_pickle=False)
            assert list(values.shape) == row['shape']
            assert np.isfinite(values).all()
            states.append(values)
    states_digest = hashlib.sha256(np.concatenate(states).astype(float).tobytes()).hexdigest()
    with tarfile.open(ROOT / 'runtime_audit.tar.gz', 'r:gz') as runtime:
        receipt_bytes = runtime.extractfile('runtime_receipt.json').read()
        receipt = json.loads(receipt_bytes)
        runtime_digest = hashlib.sha256(receipt_bytes).hexdigest()
        assert receipt['baseline_commit'] == closure['protocol']['baseline_commit']
        for name, digest in receipt['files'].items():
            assert hashlib.sha256(runtime.extractfile(name).read()).hexdigest() == digest, name
    with tarfile.open(ROOT / 'evidence.tar.gz', 'r:gz') as archive:
        for family in ('angled_donut', 'single_pass'):
            rates = []
            for seed in (44001, 44002, 44003):
                prefix = f'diagnostics/checkpoints_5us_50ms_v1/{family}/seed_{seed}/'
                design = json.load(archive.extractfile(prefix + 'checkpoint_design.json'))
                fingerprint = hashlib.sha256(json.dumps(design, sort_keys=True).encode()).hexdigest()
                assert design['dt'] == 5e-6 and design['t_max'] == .05
                assert design['runtime_receipt_sha256'] == runtime_digest
                assert design['states_sha256'] == states_digest
                chunks = sorted(m for m in archive.getnames()
                                if m.startswith(prefix + 'particles_') and m.endswith('.npz'))
                end, ever, early = [], [], []
                stop = 0
                for member in chunks:
                    with np.load(io.BytesIO(archive.extractfile(member).read()), allow_pickle=False) as data:
                        assert int(data['start']) == stop
                        assert str(data['fingerprint']) == fingerprint
                        stop = int(data['stop'])
                        end.append(data['usable_at_end'])
                        ever.append(data['usable_ever'])
                        early.append(data['diagnostic_eligible_at_30ms'])
                        np.testing.assert_array_equal(data['diagnostic_eligible_at_50ms'], end[-1])
                assert stop == 16675
                result = ROOT / f'final_validation_5us_50ms/{family}/seed_{seed}.json'
                metadata = json.loads(result.read_text())
                with np.load(result.with_suffix('.npz'), allow_pickle=False) as data:
                    np.testing.assert_array_equal(data['usable_at_end'], np.concatenate(end))
                    np.testing.assert_array_equal(data['usable_ever'], np.concatenate(ever))
                    assert len(data['ensemble_ids']) == 16675
                    assert len(np.unique(data['ensemble_ids'])) == 20
                    assert metadata['usable_at_end_count'] == int(data['usable_at_end'].sum())
                    rates.append(data['usable_at_end'].mean())
                diagnostic = ROOT / f'diagnostics/capture_time_comparison_30_50ms/{family}/seed_{seed}.npz'
                with np.load(diagnostic, allow_pickle=False) as data:
                    np.testing.assert_array_equal(data['eligible_at_30ms'], np.concatenate(early))
                    np.testing.assert_array_equal(data['eligible_at_50ms'], np.concatenate(end))
            summary = json.loads((ROOT / f'final_validation_5us_50ms/{family}/final_validation_summary.json').read_text())
            assert np.isclose(np.mean(rates), summary['conditional_efficiency'], rtol=0, atol=1e-15)
            assert summary['conditional_efficiency'] == closure['results'][family]['conditional_efficiency']
            assert summary['bootstrap_95_ci'] == closure['results'][family]['bootstrap_95_ci']
