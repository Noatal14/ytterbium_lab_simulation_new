# Studies command catalog

`studies` is the stable command-line compatibility surface for scientific runs.
Existing manifests, PBS files, tests, and documentation refer to module names
such as `python -m studies.mot_2d_s0_campaign`; do not move or rename these
modules while those campaign records remain relevant.

The directory is organized logically as follows. The flat filenames are kept
for compatibility, not because every module has equal status.

## Active 2D-MOT campaign

- `mot_2d_s0_campaign.py` — manifest-driven orchestration.
- `optimize_2d_mot_joint.py` — screening/refinement worker.
- `run_2d_mot_final_production.py` — sealed production and uncertainty report.
- `generate_corrected_zeeman_ensembles.py` — corrected input generation.

These paths and command-line interfaces are frozen for existing campaigns.

## Reusable Zeeman and 2D validation

- `validate_zeeman_configuration.py`
- `diagnose_zeeman_trajectories.py`
- `scan_zeeman_capture_velocity.py`
- `zeeman_stochastic_convergence.py`
- `estimate_oven_flux.py`
- `full_thermal_zeeman_flux.py`
- `diagnose_2d_mot_photon_counts.py`

## Active 3D-MOT campaign

`mot_3d_campaign.py` is the canonical manifest-driven manager. It generates the
PBS chains and calls the retained `optimize_*`, `select_*`, `run_*`, and
`merge_*` engines directly. The old standalone `submit_*` wrappers for these
same stages were removed because they duplicated the manager and could bypass
its frozen-manifest and stage-integrity checks.

The module names used by the campaign manager remain a frozen compatibility
surface for generated PBS files and resumable campaigns.

## Historical exploratory chains

The decisions from the donut-velocity/aperture and early single-pass scripts,
together with surviving evidence paths, are recorded in
`docs/3D_MOT_HISTORICAL_STUDIES.md`. These programs are not part of the active
campaign command surface.

## Application boundary

New UI code must use `workflow_api`, not import `submit_*` modules. The API is
side-effect-free: inspecting a campaign may produce a job plan, but it cannot
submit to Zeus. Scheduler submission will remain a separate, explicit user
action.

The current read-only boundary can also be inspected from the terminal:

```bash
python -m workflow_api list
python -m workflow_api inspect-2d path/to/campaign
```
