"""Locate the effective blue-light slowing region of the yz single pass."""

import argparse
import copy
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from config import (
    BLUE_SATURATION_INTENSITY_MW_CM2,
    DEFAULT_RANDOM_SEED,
    Geometry,
    MOT_3D_CONFIGURATIONS,
    MOT_3D_SIM_CONFIG,
)
from lab_setup.laser_setup_3d import setup_3dmot_lasers
from simulations.mot_3d import mot_3d_simulation
from studies.compare_3d_mot_retention import (
    DEFAULT_INPUT,
    analyze_results,
    load_shared_ensemble,
)


def _sample_trajectories(results, sample_times):
    states = np.full((len(results), len(sample_times), 6), np.nan, dtype=np.float32)
    for particle_index, trajectory in enumerate(results):
        trajectory_times = np.asarray(trajectory.t, dtype=float)
        trajectory_states = np.asarray(trajectory.y, dtype=float)
        if not trajectory_times.size or trajectory_states.shape[0] < 6:
            continue
        indices = np.searchsorted(trajectory_times, sample_times)
        valid = indices < len(trajectory_times)
        exact = np.zeros_like(valid)
        exact[valid] = np.isclose(
            trajectory_times[indices[valid]], sample_times[valid], atol=1e-12, rtol=0.0
        )
        states[particle_index, exact] = trajectory_states[:6, indices[exact]].T
    return states


def _blue_intensities(profile, states):
    blue_beams = [
        beam for beam in setup_3dmot_lasers(profile) if "3DMOT_399" in beam.tag
    ]
    valid = np.all(np.isfinite(states[:, :, :3]), axis=2)
    positions = states[:, :, :3][valid]
    values = np.full((len(blue_beams), *valid.shape), np.nan, dtype=np.float32)
    saturation_w_m2 = BLUE_SATURATION_INTENSITY_MW_CM2 * 10.0
    for beam_index, beam in enumerate(blue_beams):
        values[beam_index][valid] = (
            np.asarray(beam.get_value(positions), dtype=float) / saturation_w_m2
        )
    return [beam.tag for beam in blue_beams], values


def _slowing_rate(states, sample_times):
    rate = np.full(states.shape[:2], np.nan, dtype=np.float32)
    for index, row in enumerate(states[:, :, 5]):
        valid_count = int(np.isfinite(row).sum())
        if valid_count < 5:
            continue
        values = row[:valid_count].astype(float)
        kernel = np.ones(5) / 5.0
        smooth = np.convolve(values, kernel, mode="same")
        smooth[:2] = values[:2]
        smooth[-2:] = values[-2:]
        rate[index, :valid_count] = -np.gradient(smooth, sample_times[:valid_count])
    return rate


def _binned_median(z_mm, values, bins):
    centers = 0.5 * (bins[:-1] + bins[1:])
    medians = np.full_like(centers, np.nan, dtype=float)
    for index, (left, right) in enumerate(zip(bins[:-1], bins[1:])):
        selected = values[(z_mm >= left) & (z_mm < right) & np.isfinite(values)]
        if selected.size:
            medians[index] = np.median(selected)
    return centers, medians


def run(args):
    selected, input_files = load_shared_ensemble(args.input, args.max_atoms, args.seed)
    selected = selected[: args.max_atoms]
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    sample_times = np.arange(0.0, args.t_max + 0.5 * args.sample_interval, args.sample_interval)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    plot_data = []

    for z_offset_m in args.z_offset_m_values:
        profile = copy.deepcopy(MOT_3D_CONFIGURATIONS["single_pass"])
        profile["blue_crossing_z_offset_m"] = z_offset_m
        profile["399"].update(
            s0=args.blue_s0,
            detuning_gamma=args.blue_detuning_gamma,
            waist_m=args.blue_waist_m,
        )
        print(f"Starting slowing diagnostic at z={1000*z_offset_m:g} mm", flush=True)
        trajectories, _ = mot_3d_simulation(
            selected,
            _3d_mot_config=profile,
            gravity_enabled=True,
            npools=args.npools,
            dt=args.dt,
            t_max=args.t_max,
            seed=args.seed,
        )
        analysis = analyze_results(trajectories, time_points)
        captured = np.any(analysis["eligible_masks"], axis=1)
        states = _sample_trajectories(trajectories, sample_times)
        beam_tags, beam_s0 = _blue_intensities(profile, states)
        total_blue_s0 = np.nansum(beam_s0, axis=0)
        slowing_rate = _slowing_rate(states, sample_times)
        z_m = states[:, :, 2] - float(Geometry.MOT_3D_CENTER_M[2])
        peak_z = np.full(len(states), np.nan)
        for particle_index in range(len(states)):
            valid = (
                np.isfinite(slowing_rate[particle_index])
                & (total_blue_s0[particle_index] > 1e-3)
                & (z_m[particle_index] < 0.0)
            )
            if np.any(valid):
                indices = np.flatnonzero(valid)
                peak_index = indices[np.nanargmax(slowing_rate[particle_index, valid])]
                peak_z[particle_index] = z_m[particle_index, peak_index]
        row = {
            "blue_crossing_z_offset_m": float(z_offset_m),
            "input_particle_count": len(selected),
            "usable_ever_count": int(captured.sum()),
            "captured_peak_slowing_z_median_m": (
                float(np.nanmedian(peak_z[captured])) if np.any(captured) else None
            ),
            "not_captured_peak_slowing_z_median_m": (
                float(np.nanmedian(peak_z[~captured])) if np.any(~captured) else None
            ),
        }
        rows.append(row)
        np.savez_compressed(
            output_dir / f"slowing_z_{abs(round(1000*z_offset_m)):02d}mm.npz",
            time_s=sample_times,
            states=states,
            capture_eligible_ever=captured,
            blue_beam_tags=np.asarray(beam_tags),
            blue_s0_along_trajectory=beam_s0,
            total_blue_s0_along_trajectory=total_blue_s0,
            slowing_rate_m_s2=slowing_rate,
            peak_slowing_z_m=peak_z,
        )
        plot_data.append((z_offset_m, states, captured, beam_tags, beam_s0, slowing_rate, peak_z))
        print(
            f"Completed z={1000*z_offset_m:g} mm: captured={captured.sum()}/{len(captured)}, "
            f"median peak slowing z={1000*np.nanmedian(peak_z[captured]):.1f} mm",
            flush=True,
        )

    summary = {
        "status": "single-pass effective slowing-region diagnostic",
        "input_files": [str(path) for path in input_files],
        "blue_s0": args.blue_s0,
        "blue_detuning_gamma": args.blue_detuning_gamma,
        "blue_waist_m": args.blue_waist_m,
        "sample_interval_s": args.sample_interval,
        "records": rows,
    }
    summary_path = output_dir / "single_pass_slowing_diagnostic_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    bins = np.linspace(-120.0, 5.0, 64)
    fig, axes = plt.subplots(3, len(plot_data), figsize=(12.0, 10.0), sharex="col")
    if len(plot_data) == 1:
        axes = axes[:, None]
    for column, (z_offset_m, states, captured, beam_tags, beam_s0, slowing_rate, peak_z) in enumerate(plot_data):
        z_mm = 1000.0 * (
            states[:, :, 2] - float(Geometry.MOT_3D_CENTER_M[2])
        )
        vz = states[:, :, 5]
        for particle_index in range(len(states)):
            color = "tab:blue" if captured[particle_index] else "0.65"
            alpha = 0.35 if captured[particle_index] else 0.22
            axes[0, column].plot(z_mm[particle_index], vz[particle_index], color=color, alpha=alpha, lw=0.7)
        axes[0, column].axvline(1000*z_offset_m, color="tab:red", ls="--", lw=1.2, label="geometric crossing")
        axes[0, column].set_title(f"crossing z = {1000*z_offset_m:g} mm")
        axes[0, column].set_ylabel("vz [m/s]")
        axes[0, column].legend(fontsize=8)

        for beam_index, beam_tag in enumerate(beam_tags):
            centers, medians = _binned_median(z_mm.ravel(), beam_s0[beam_index].ravel(), bins)
            axes[1, column].plot(centers, medians, label=beam_tag.replace("3DMOT_399_", ""))
        axes[1, column].set_ylabel("median local blue s0")
        axes[1, column].legend(fontsize=7)

        captured_values = np.broadcast_to(captured[:, None], slowing_rate.shape)
        centers, medians = _binned_median(
            z_mm[captured_values], slowing_rate[captured_values], bins
        )
        axes[2, column].plot(centers, medians, color="tab:blue")
        axes[2, column].axvline(1000*z_offset_m, color="tab:red", ls="--", lw=1.2)
        axes[2, column].set_ylabel("median slowing rate [m/s²]")
        axes[2, column].set_xlabel("z relative to MOT center [mm]")
        axes[2, column].set_xlim(-120, 5)
    fig.suptitle("Where does the physical yz single pass slow the atoms?")
    fig.tight_layout()
    graph_dir = Path(args.graph_dir)
    graph_dir.mkdir(parents=True, exist_ok=True)
    graph_path = graph_dir / "single_pass_yz_slowing_region.png"
    fig.savefig(graph_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved summary: {summary_path}")
    print(f"Saved graph: {graph_path}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--graph-dir", default="graphs/mot_3d_configuration_decision")
    parser.add_argument("--max-atoms", type=int, default=120)
    parser.add_argument("--npools", type=int, default=120)
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=0.1)
    parser.add_argument("--sample-interval", type=float, default=0.0001)
    parser.add_argument("--z-offset-m-values", nargs="+", type=float, default=(-0.050, -0.045))
    parser.add_argument("--blue-s0", type=float, default=0.25)
    parser.add_argument("--blue-detuning-gamma", type=float, default=-2.75)
    parser.add_argument("--blue-waist-m", type=float, default=0.0075)
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
