"""Per-manifest workload selection; scientific defaults are never overridden."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
from typing import Mapping

from workflow_api.acceptance_profile import policy_for_manifest, assert_acceptance_path
from workflow_api.mot_3d_stage_topology import (
    PRELIMINARY_CHECK_TOPOLOGY,
    REFINEMENT_TOPOLOGY,
    CLOSURE_TOPOLOGY,
    FINALIST_SELECTION_TOPOLOGY,
    FINAL_VALIDATION_TOPOLOGY,
)


def policy(manifest):
    if (
        "kind" not in manifest
        and "acceptance" not in manifest
        and manifest.get("suitability") != "acceptance_only"
    ):
        return None
    profile = policy_for_manifest(manifest)
    if profile is not None and manifest["kind"] != "mot_3d_ui_acceptance_v1":
        raise ValueError("3D workload requires a 3D acceptance manifest.")
    if profile is not None:
        # A profile marker authenticates the workload, not arbitrary physical
        # values next to it. Re-attest every immutable physical design field.
        import json
        from studies.mot_3d_campaign import build_campaign_manifest

        expected = build_campaign_manifest(
            name="policy-check",
            input_directory=".",
            upstream={},
            roles={},
            revision="",
            physical_model_sha256="",
        )["design"]
        observed = manifest.get("design")
        keys = tuple(key for key in expected if key != "timestep_evidence")
        if not isinstance(observed, Mapping):
            raise ValueError("Acceptance campaign lacks its frozen physical design.")
        try:
            actual = json.dumps(
                {key: observed[key] for key in keys},
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            required = json.dumps(
                {key: expected[key] for key in keys},
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "Acceptance campaign physical design is incomplete or invalid."
            ) from error
        if actual != required:
            raise ValueError(
                "Acceptance campaign physical design differs from canonical physics."
            )
    return profile


def stage(manifest, name):
    profile = policy(manifest)
    return None if profile is None else profile.stage("mot_3d", name)


def particles_per_ensemble(manifest, name, scientific):
    value = stage(manifest, name)
    return scientific if value is None else value["particles_per_ensemble"]


def discovery_targets(manifest, family):
    from studies.mot_3d_campaign import _targets
    from config import MOT_3D_OPTIMIZATION_CONFIG

    profile = policy(manifest)
    return (
        _targets(MOT_3D_OPTIMIZATION_CONFIG[family]["total_discovery_trials"])
        if profile is None
        else tuple(profile.family("mot_3d")["discovery_targets"][family])
    )


def topology(manifest, name):
    original = {
        "preliminary_check": PRELIMINARY_CHECK_TOPOLOGY,
        "refinement": REFINEMENT_TOPOLOGY,
        "closure": CLOSURE_TOPOLOGY,
        "finalist_selection": FINALIST_SELECTION_TOPOLOGY,
        "final_validation": FINAL_VALIDATION_TOPOLOGY,
    }[name]
    selected = stage(manifest, name)
    if selected is None:
        return original
    return replace(
        original,
        array_ncpus=selected["ncpus"],
        array_memory_gb=selected["memory_gb"],
        array_walltime=_walltime(selected["walltime_seconds"]),
        merge_ncpus=selected["merge_ncpus"],
        merge_memory_gb=selected["merge_memory_gb"],
        merge_walltime=_walltime(selected["merge_walltime_seconds"]),
    )


def array_range(manifest, name):
    """Authenticate per-stage concurrency without changing the three task indices."""
    selected = stage(manifest, name)
    throttle = None if selected is None else selected.get("array_throttle")
    return "0-2:1" if throttle is None else f"0-2:1%{throttle}"


def rendered_job(text, manifest, name, *, merge=False):
    """Apply the authenticated workload to ordinary PBS rendering, never physics."""
    selected = stage(manifest, name)
    if selected is None:
        return text
    prefix = "merge_" if merge else ""
    if not merge and selected.get("array_throttle") is not None:
        text = text.replace("set -euo pipefail\n", f"#PBS -J {array_range(manifest, name)}\nset -euo pipefail\n")
    return _render_policy_job(
        text,
        manifest,
        {
            "ncpus": selected[prefix + "ncpus"],
            "memory_gb": selected[prefix + "memory_gb"],
            "walltime_seconds": selected[prefix + "walltime_seconds"],
            "npools": selected["npools"],
            "particles_per_ensemble": selected["particles_per_ensemble"],
        },
    )


def _walltime(seconds):
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def generation_job(manifest, name):
    profile = policy(manifest)
    if profile is None:
        return None
    if name not in {"zeeman", "mot_2d", "freeze"}:
        raise ValueError("Unknown final-input generation job.")
    return profile.policy["generation"]["jobs"][name]


def rendered_generation_job(text, manifest, name):
    selected = generation_job(manifest, name)
    return text if selected is None else _render_policy_job(text, manifest, selected)


def _render_policy_job(text, manifest, selected):
    vnode = policy(manifest).policy.get("scheduler", {}).get("vnode")
    placement = "" if vnode is None else f":vnode={vnode}"
    text = re.sub(
        r"(#PBS -l select=1:ncpus=)\d+:mem=\d+gb",
        lambda match: f"{match[1]}{selected['ncpus']}:mem={selected['memory_gb']}gb{placement}",
        text,
    )
    text = re.sub(
        r"(#PBS -l walltime=)[0-9:]+",
        lambda m: m[1] + _walltime(selected["walltime_seconds"]),
        text,
    )
    text = re.sub(r"--npools \d+", f"--npools {selected['npools']}", text)
    if isinstance(selected.get("particles_per_ensemble"), int):
        text = re.sub(
            r"--particles-per-ensemble \d+",
            f"--particles-per-ensemble {selected['particles_per_ensemble']}",
            text,
        )
    text = re.sub(r"--timeout-s \d+", "--timeout-s 3000", text)
    text = text.replace(
        "cd ~/ytterbium_lab_simulation_new\n",
        "cd ~/ytterbium_lab_simulation_ui_acceptance\n",
    )
    text = text.replace(
        "source ~/venvs/atomsmltr/bin/activate",
        "source ~/venvs/atomsmltr-ui-test/bin/activate",
    )
    return text.replace(
        "set -euo pipefail\n",
        "set -euo pipefail\n# TEST ONLY: ui_acceptance_v1; no scientific promotion\n",
    )


def validate_worker(args, manifest_path, name):
    """Validate explicit physical worker arguments against the frozen test policy."""
    import json

    manifest = json.loads(Path(manifest_path).read_text())
    selected = stage(manifest, name)
    if selected is None:
        return manifest
    repo = Path(__file__).resolve().parents[1]
    assert_acceptance_path(manifest_path, repo)
    assert_acceptance_path(
        args.output_dir if hasattr(args, "output_dir") else args.output, repo
    )
    expected_stage = "discovery" if name == "smoke" else name
    if manifest.get("stage") != expected_stage:
        raise ValueError("Acceptance worker stage differs from its frozen campaign.")
    expected_dt = (
        manifest["design"]["production_dt_s"]
        if name == "final_validation"
        else manifest["design"]["screening_dt_s"]
    )
    if (
        args.npools != selected["npools"]
        or args.dt != expected_dt
        or args.t_max != manifest["design"]["t_max_s"]
    ):
        raise ValueError(
            "Acceptance worker resources or physical policy differ from the frozen profile."
        )
    count = selected["particles_per_ensemble"]
    if (
        hasattr(args, "particles_per_ensemble")
        and isinstance(count, int)
        and args.particles_per_ensemble != count
    ):
        raise ValueError(
            "Acceptance worker particle count differs from the frozen profile."
        )
    if name in {"smoke", "discovery"}:
        from config import DEFAULT_RANDOM_SEED
        from studies.mot_3d_campaign import _cumulative_targets, FAMILIES

        family_policy = policy(manifest).family("mot_3d")
        worker = args.worker_index
        if (
            type(worker) is not int
            or worker not in range(3)
            or args.family not in FAMILIES
        ):
            raise ValueError("Acceptance discovery worker identity is invalid.")
        if name == "smoke":
            targets = {1}
            sampler = 281001 + FAMILIES.index(args.family)
            if worker != 0:
                raise ValueError(
                    "Acceptance smoke requires its single declared worker."
                )
        else:
            final = tuple(family_policy["discovery_targets"][args.family])
            rounds = family_policy["discovery_rounds"][args.family]
            targets = {
                _cumulative_targets(final, index, rounds)[worker]
                for index in range(1, rounds + 1)
            }
            sampler = family_policy["sampler_seeds"][worker]
        if (
            args.target_completed_trials not in targets
            or args.sampler_seed != sampler
            or args.input_role != "discovery"
            or args.startup_trials != 24
            or args.selection_seed != DEFAULT_RANDOM_SEED
            or args.simulation_seed != DEFAULT_RANDOM_SEED
        ):
            raise ValueError(
                "Acceptance discovery budget, seed or role differs from the frozen workflow."
            )
    elif name in {"preliminary_check", "refinement", "closure"}:
        expected = scientific_design(manifest, name)
        if (
            args.num_workers != selected["workers"]
            or args.worker_index not in range(selected["workers"])
            or args.selection_seed != expected.selection_seed
        ):
            raise ValueError(
                "Acceptance selection worker differs from its frozen workload."
            )
    elif name == "finalist_selection" and args.finalist_index not in range(
        selected["candidates_per_family"]
    ):
        raise ValueError("Acceptance finalist index differs from its frozen workload.")
    elif (
        name == "final_validation" and args.recoil_seed not in selected["recoil_seeds"]
    ):
        raise ValueError(
            "Acceptance final-validation recoil seed differs from its frozen workload."
        )
    return manifest


def artifact_identity(manifest):
    return (
        {}
        if policy(manifest) is None
        else {"acceptance": manifest["acceptance"], "suitability": "acceptance_only"}
    )


def scientific_design(manifest, name):
    from workflow_api.mot_3d_stage_topology import (
        PRELIMINARY_SCIENTIFIC_DESIGN,
        REFINEMENT_SCIENTIFIC_DESIGN,
        CLOSURE_SCIENTIFIC_DESIGN,
        FINALIST_SELECTION_SCIENTIFIC_DESIGN,
        FINAL_VALIDATION_SCIENTIFIC_DESIGN,
    )

    original = {
        "preliminary_check": PRELIMINARY_SCIENTIFIC_DESIGN,
        "refinement": REFINEMENT_SCIENTIFIC_DESIGN,
        "closure": CLOSURE_SCIENTIFIC_DESIGN,
        "finalist_selection": FINALIST_SELECTION_SCIENTIFIC_DESIGN,
        "final_validation": FINAL_VALIDATION_SCIENTIFIC_DESIGN,
    }[name]
    selected = stage(manifest, name)
    if selected is None:
        return original
    changes = {}
    if hasattr(original, "particles_per_ensemble"):
        changes["particles_per_ensemble"] = selected["particles_per_ensemble"]
    if hasattr(original, "npools"):
        changes["npools"] = selected["npools"]
    return replace(original, **changes)


def submission_science(manifest, name, original):
    selected = stage(manifest, name)
    result = dict(original)
    if selected is None:
        return result
    if "particles_per_ensemble" in result:
        result["particles_per_ensemble"] = selected["particles_per_ensemble"]
        result["total_particles"] = (
            result["input_ensembles"] * selected["particles_per_ensemble"]
        )
    if "npools" in result:
        result["npools"] = selected["npools"]
    return result


def validate_location(manifest, relative):
    from pathlib import PurePosixPath

    path = PurePosixPath(relative)
    expected = (
        "data",
        "optimization",
        "mot_3d",
        *(("ui_acceptance",) if policy(manifest) else ()),
        manifest.get("name"),
    )
    if path.is_absolute() or path.parts != expected:
        raise ValueError(
            "Campaign location does not match its scientific or acceptance provenance."
        )


def generation_science(manifest, original):
    profile = policy(manifest)
    if profile is None:
        return original
    resources = {}
    for name in ("zeeman", "mot_2d", "freeze"):
        job = generation_job(manifest, name)
        resources[name] = {
            "ncpus": job["ncpus"],
            "memory_gb": job["memory_gb"],
            "walltime": _walltime(job["walltime_seconds"]),
        }
        vnode = profile.policy.get("scheduler", {}).get("vnode")
        if vnode is not None:
            resources[name]["vnode"] = vnode
    return {
        **original,
        "npools": generation_job(manifest, "mot_2d")["npools"],
        "resources": resources,
    }


def assert_receiver_target(
    manifest, username, project, relative, *, trusted_root_override=None
):
    """Authenticate real requests; permit only explicit legacy test projections.

    The receiver CLI cannot provide trusted_root_override. Missing-kind fixture
    fragments can therefore never bypass authentication on a real Zeus target.
    """
    from workflow_api.acceptance_remote import assert_campaign_target
    from workflow_api.zeus_snapshot import USERNAME_RE

    if not isinstance(username, str) or USERNAME_RE.fullmatch(username) is None:
        raise ValueError("Invalid campaign account.")
    legacy_fixture = (
        trusted_root_override is not None
        and "kind" not in manifest
        and "acceptance" not in manifest
        and manifest.get("suitability") != "acceptance_only"
        and project == f"/home/{username}/ytterbium_lab_simulation_new"
    )
    if not legacy_fixture:
        assert_campaign_target(manifest, username, project, relative)
        validate_location(manifest, relative)


def discovery_review(manifest):
    """Describe the exact frozen Discovery worker policy for operator review."""
    from lab_setup.mot_3d_timestep_policy import MOT_3D_TIMESTEP_POLICY

    selected = stage(manifest, "discovery")
    per_ensemble = 50 if selected is None else selected["particles_per_ensemble"]
    targets = {
        family: list(discovery_targets(manifest, family))
        for family in ("angled_donut", "single_pass")
    }
    resources = {
        "array": {
            "ncpus_per_task": 200 if selected is None else selected["ncpus"],
            "memory_gb_per_task": 64 if selected is None else selected["memory_gb"],
            "walltime": (
                "24:00:00"
                if selected is None
                else _walltime(selected["walltime_seconds"])
            ),
        }
    }
    if selected is not None:
        vnode = policy(manifest).policy.get("scheduler", {}).get("vnode")
        if vnode is not None:
            resources["array"]["vnode"] = vnode
    science = {
        "classification": "candidate_selection_not_final_validation",
        "input_role": "discovery",
        "input_ensembles": 12,
        "particles_per_ensemble": per_ensemble,
        "total_particles_per_trial": 12 * per_ensemble,
        "npools": 200 if selected is None else selected["npools"],
        "dt_s": MOT_3D_TIMESTEP_POLICY["search_dt_s"],
        "t_max_s": MOT_3D_TIMESTEP_POLICY["t_max_s"],
        "solver": MOT_3D_TIMESTEP_POLICY["solver"],
        "final_trial_targets": targets,
        "total_trials": sum(sum(rows) for rows in targets.values()),
    }
    return resources, science


def validate_discovery_job_bytes(manifest, commit, campaign_relative, files):
    """Bind reviewed Discovery numbers to the exact submitted frozen PBS bytes."""
    from studies.mot_3d_campaign import render_discovery_jobs

    relative = Path(campaign_relative)
    rendered, _, _, _ = render_discovery_jobs(
        relative,
        commit,
        manifest["input_directory"],
        command_campaign=relative,
        command_input=Path(manifest["input_directory"]),
        manifest=manifest,
    )
    if set(files) != set(rendered) or any(
        files[name] != text.encode() for name, text in rendered.items()
    ):
        raise ValueError("Discovery job bytes differ from the reviewed workload.")


def discovery_selection(manifest, summary, family):
    """Authenticate workload identity; candidate selection is always canonical."""
    from studies.mot_3d.discovery.select import select_candidates

    policy(manifest)
    return select_candidates(summary, family, count=12)
