import hashlib
import json

import pytest

from studies.mot_3d_campaign import (
    FAMILIES,
    prepare_final_validation_inputs,
    render_final_validation_input_transition,
)


def test_renderer_is_pure_portable_exact_and_byte_equal_to_adapter(
    tmp_path, monkeypatch
):
    import studies.mot_3d.discovery.optimize as optimizer

    monkeypatch.setattr(
        optimizer,
        "build_profile_from_parameters",
        lambda family, parameters: ({"family": family}, parameters, {}),
    )
    manifest = {
        "name": "example",
        "stage": "finalist_selection",
        "provenance": {"git_commit": "a" * 40},
        "upstream_2d_campaign": {
            "expected_survivor_parameters": {
                "s0": 1.3,
                "detuning_gamma": -1.0,
                "magnet_radius": 0.046,
            },
            "expected_survivor_design": {"zeeman_profile": "corrected"},
        },
        "stages": {},
    }
    summaries = {
        family: {
            "kind": "merged_mot_3d_finalist_selection",
            "family": family,
            "ranked_candidates": [
                {
                    "candidate_id": f"{family}_winner_{index}",
                    "parameters": {"green_s0": 1.0},
                }
                for index in range(3)
            ],
        }
        for family in FAMILIES
    }
    summary_raw = {
        family: json.dumps(value).encode() for family, value in summaries.items()
    }
    hashes = {
        family: hashlib.sha256(raw).hexdigest() for family, raw in summary_raw.items()
    }
    artifacts, updated = render_final_validation_input_transition(
        "data/optimization/mot_3d/example", manifest, summaries, hashes, "b" * 64
    )
    assert set(artifacts) == {
        "selection/locked_nominals.json",
        "campaign.json",
        "jobs/final_validation_inputs/01_generate_zeeman.pbs",
        "jobs/final_validation_inputs/02_generate_2d_survivors.pbs",
        "jobs/final_validation_inputs/03_freeze_inputs.pbs",
    }
    assert manifest["stages"] == {}
    assert updated["stage"] == "final_validation_input_generation"
    assert all(
        b"/home/" not in raw and str(tmp_path).encode() not in raw
        for raw in artifacts.values()
    )

    root = tmp_path / "data/optimization/mot_3d/example"
    root.mkdir(parents=True)
    (root / "campaign.json").write_bytes(b"manifest-original")
    for family, raw in summary_raw.items():
        destination = (
            root / "finalist_selection" / family / "merged/finalist_summary.json"
        )
        destination.parent.mkdir(parents=True)
        destination.write_bytes(raw)
    mutable = json.loads(json.dumps(manifest))
    prepare_final_validation_inputs(root, mutable)
    expected, expected_manifest = render_final_validation_input_transition(
        "data/optimization/mot_3d/example",
        manifest,
        summaries,
        hashes,
        hashlib.sha256(b"manifest-original").hexdigest(),
    )
    assert {name: (root / name).read_bytes() for name in expected} == expected
    assert mutable == expected_manifest


def _real_renderer_inputs():
    from studies.mot_3d.discovery.optimize import build_profile_from_parameters

    manifest = {
        "name": "example",
        "stage": "finalist_selection",
        "provenance": {"git_commit": "a" * 40},
        "upstream_2d_campaign": {
            "expected_survivor_parameters": {
                "s0": 1.3,
                "detuning_gamma": -1.0,
                "magnet_radius": 0.046,
            },
            "expected_survivor_design": {"zeeman_profile": "corrected"},
        },
        "stages": {},
    }
    base = {
        "angled_donut": {
            "green_s0": 18.0,
            "green_detuning_gamma": -18.0,
            "green_waist_m": 0.0065,
            "blue_s0": 1.4,
            "blue_waist_m": 0.0074,
            "magnetic_gradient_G_cm": 5.5,
            "blue_detuning_gamma": -0.8,
            "core_shell_split_radius_m": 0.0026,
        },
        "single_pass": {
            "green_s0": 38.0,
            "green_detuning_gamma": -25.0,
            "green_waist_m": 0.0074,
            "blue_s0": 0.2,
            "blue_waist_m": 0.0073,
            "magnetic_gradient_G_cm": 2.3,
            "blue_detuning_anchor_gamma": -2.5,
            "blue_crossing_angle_deg": 46.0,
            "blue_crossing_z_offset_m": -0.046,
        },
    }
    summaries = {}
    expected = {}
    for family in FAMILIES:
        profile, parameters, derived = build_profile_from_parameters(
            family, base[family]
        )
        expected[family] = (profile, parameters, derived)
        summaries[family] = {
            "kind": "merged_mot_3d_finalist_selection",
            "family": family,
            "ranked_candidates": [
                {
                    "candidate_id": f"{family}_finalist_{index:02d}",
                    "parameters": parameters,
                }
                for index in range(1, 4)
            ],
        }
    return (
        manifest,
        summaries,
        {family: hashlib.sha256(family.encode()).hexdigest() for family in FAMILIES},
        expected,
    )


def test_renderer_locks_real_profiles_and_rejects_noncanonical_boundaries():
    manifest, summaries, hashes, expected = _real_renderer_inputs()
    artifacts, _ = render_final_validation_input_transition(
        "data/optimization/mot_3d/example", manifest, summaries, hashes, "f" * 64
    )
    locked = json.loads(artifacts["selection/locked_nominals.json"])
    for family in FAMILIES:
        profile, parameters, derived = expected[family]
        assert locked["families"][family]["resolved_profile"] == json.loads(
            json.dumps(profile)
        )
        assert locked["families"][family]["parameters"] == parameters
        assert locked["families"][family]["derived_parameters"] == derived
        assert locked["families"][family]["selection_summary_sha256"] == hashes[family]

    cases = []
    missing = dict(summaries)
    missing.pop("angled_donut")
    cases.append(
        (manifest, missing, hashes, "f" * 64, "data/optimization/mot_3d/example")
    )
    extra = dict(summaries)
    extra["foreign"] = summaries["angled_donut"]
    cases.append(
        (manifest, extra, hashes, "f" * 64, "data/optimization/mot_3d/example")
    )
    bad_hashes = dict(hashes)
    bad_hashes["angled_donut"] = "not-a-digest"
    cases.append(
        (manifest, summaries, bad_hashes, "f" * 64, "data/optimization/mot_3d/example")
    )
    bad_stage = json.loads(json.dumps(manifest))
    bad_stage["stage"] = "closure"
    cases.append(
        (bad_stage, summaries, hashes, "f" * 64, "data/optimization/mot_3d/example")
    )
    bad_name = json.loads(json.dumps(manifest))
    bad_name["name"] = "other"
    cases.append(
        (bad_name, summaries, hashes, "f" * 64, "data/optimization/mot_3d/example")
    )
    cases.append(
        (manifest, summaries, hashes, "short", "data/optimization/mot_3d/example")
    )
    for bad_root in (
        ".",
        "other/example",
        "data/optimization/mot_3d/other",
        "/absolute/example",
        "data/../example",
    ):
        cases.append((manifest, summaries, hashes, "f" * 64, bad_root))
    for manifest_value, summary_value, hash_value, before_hash, root in cases:
        with pytest.raises((KeyError, TypeError, ValueError)):
            render_final_validation_input_transition(
                root, manifest_value, summary_value, hash_value, before_hash
            )


@pytest.mark.parametrize('acceptance', [False, True])
def test_fresh_2d_job_preserves_exact_frozen_radius_in_si_units(acceptance):
    import shlex
    from studies.mot_2d.production import parse_args, parameters_from_args
    source, summaries, hashes, _ = _real_renderer_inputs()
    if acceptance:
        from tests.test_mot_3d_acceptance_workload import manifest as acceptance_manifest
        manifest = acceptance_manifest()
        manifest['stage'] = 'finalist_selection'
        manifest['upstream_2d_campaign'] = source['upstream_2d_campaign']
        root = 'data/optimization/mot_3d/ui_acceptance/' + manifest['name']
    else:
        manifest = source
        root = 'data/optimization/mot_3d/example'
    radius = 0.048772914725133266
    assert float(str(radius * 1000)) * 1e-3 != radius
    manifest['upstream_2d_campaign']['expected_survivor_parameters']['magnet_radius'] = radius
    files, _ = render_final_validation_input_transition(root, manifest, summaries, hashes, 'f' * 64)
    command = files['jobs/final_validation_inputs/02_generate_2d_survivors.pbs'].decode()
    tokens = shlex.split(command)
    assert '--magnet-radius-mm' not in tokens
    encoded = tokens[tokens.index('--magnet-radius-m') + 1]
    args = parse_args(['--zeeman-seeds', '3035', '--mot-seeds', '43035', '--s0', '1.3', '--detuning-gamma', '-1', '--magnet-radius-m', encoded])
    assert parameters_from_args(args)['magnet_radius'].hex() == radius.hex()
