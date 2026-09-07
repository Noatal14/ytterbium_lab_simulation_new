"""Compare time-resolved 3D-MOT retention for the configured geometries.

The study sends one shared ensemble of saved 2D-MOT survivor states through
each requested 3D-MOT configuration.  For each configuration it finds the time
at which the instantaneous population inside the configured spherical capture
region is largest.  The retention cohort is the set of atoms inside at that
time, and an atom remains in the cohort only while it stays continuously inside
the region thereafter.

An exponential-with-plateau lifetime is reported only when the observed loss
and fit quality pass explicit thresholds.  This avoids assigning a misleading
``tau`` to a flat, non-exponential, or insufficiently sampled curve.
"""

import argparse
import copy
import gc
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import curve_fit

from config import (
    DEFAULT_NUM_POOLS,
    DEFAULT_RANDOM_SEED,
    Geometry,
    MOT_3D_CAPTURE_CONFIG,
    MOT_3D_CONFIGURATIONS,
    MOT_3D_SIM_CONFIG,
)
from simulations.mot_3d import mot_3d_simulation
from utils.data_paths import AFTER_2D_MOT_DIR, load_particle_states


DEFAULT_INPUT = AFTER_2D_MOT_DIR / "final_ensemble_v23"
DEFAULT_OUTPUT_DIR = Path("data/validation/mot_3d/retention")
DEFAULT_PROFILES = tuple(MOT_3D_CONFIGURATIONS)
DEFAULT_MIN_LOSS_FRACTION = 0.10
DEFAULT_MIN_FIT_R_SQUARED = 0.90


def load_shared_ensemble(input_path, max_atoms=None, seed=DEFAULT_RANDOM_SEED):
    """Load one state file or concatenate every state file in a directory."""
    input_path = Path(input_path)
    files = (
        [input_path]
        if input_path.is_file()
        else sorted(input_path.glob("*.npy"))
    )
    if not files:
        raise FileNotFoundError(f"No .npy particle-state files found at {input_path}")

    arrays = [load_particle_states(path) for path in files]
    states = np.concatenate(arrays, axis=0)
    if max_atoms is not None:
        if max_atoms <= 0:
            raise ValueError("max_atoms must be positive.")
        if max_atoms < len(states):
            rng = np.random.default_rng(seed)
            indices = np.sort(rng.choice(len(states), size=max_atoms, replace=False))
            states = states[indices]
    return states, files


def inside_capture_masks(results, time_points, center_m, capture_radius_m):
    """Return a particle-by-time mask for presence inside the capture sphere."""
    time_points = np.asarray(time_points, dtype=float)
    center = np.asarray(center_m, dtype=float)
    masks = np.zeros((len(results), len(time_points)), dtype=bool)

    for particle_index, trajectory in enumerate(results):
        trajectory_times = np.asarray(trajectory.t, dtype=float)
        states = np.asarray(trajectory.y, dtype=float)
        if trajectory_times.size == 0 or states.ndim != 2 or states.shape[0] < 3:
            continue
        grid_indices = np.searchsorted(time_points, trajectory_times)
        valid = grid_indices < len(time_points)
        grid_indices = grid_indices[valid]
        trajectory_times = trajectory_times[valid]
        states = states[:, valid]
        exact = np.isclose(
            time_points[grid_indices], trajectory_times, rtol=0.0, atol=1e-12
        )
        distances = np.linalg.norm(states[:3, exact].T - center, axis=1)
        masks[particle_index, grid_indices[exact]] = distances <= capture_radius_m
    return masks


def retention_from_masks(inside_masks):
    """Find the peak cohort and its continuous post-peak retention curve."""
    inside_masks = np.asarray(inside_masks, dtype=bool)
    instantaneous = inside_masks.sum(axis=0)
    peak_index = int(np.argmax(instantaneous))
    cohort = inside_masks[:, peak_index]
    post_peak_inside = inside_masks[cohort, peak_index:]
    retained_post_peak = np.logical_and.accumulate(post_peak_inside, axis=1)
    retained = retained_post_peak.sum(axis=0)
    return instantaneous, peak_index, retained, np.flatnonzero(cohort)


def _retention_model(elapsed_time_s, tau_s, plateau_count, initial_count):
    return plateau_count + (initial_count - plateau_count) * np.exp(
        -elapsed_time_s / tau_s
    )


def fit_retention_lifetime(
    elapsed_time_s,
    retained_counts,
    min_loss_fraction=DEFAULT_MIN_LOSS_FRACTION,
    min_r_squared=DEFAULT_MIN_FIT_R_SQUARED,
):
    """Fit exponential retention with a plateau, or explain why no tau is valid."""
    elapsed = np.asarray(elapsed_time_s, dtype=float)
    counts = np.asarray(retained_counts, dtype=float)
    if len(elapsed) < 5 or counts[0] <= 0:
        return {"accepted": False, "reason": "insufficient post-peak samples"}

    loss_fraction = float((counts[0] - counts[-1]) / counts[0])
    if loss_fraction < min_loss_fraction:
        return {
            "accepted": False,
            "reason": "observed loss is below the configured threshold",
            "loss_fraction": loss_fraction,
        }
    if np.unique(counts).size < 4:
        return {
            "accepted": False,
            "reason": "too few distinct population levels for a stable fit",
            "loss_fraction": loss_fraction,
        }

    duration = float(elapsed[-1] - elapsed[0])
    positive_steps = np.diff(elapsed)
    positive_steps = positive_steps[positive_steps > 0]
    if duration <= 0 or positive_steps.size == 0:
        return {"accepted": False, "reason": "zero post-peak duration"}

    initial_count = float(counts[0])
    model = lambda t, tau, plateau: _retention_model(
        t, tau, plateau, initial_count
    )
    try:
        parameters, covariance = curve_fit(
            model,
            elapsed,
            counts,
            p0=(max(duration / 2.0, positive_steps.min()), counts[-1]),
            bounds=(
                (positive_steps.min() / 10.0, 0.0),
                (100.0 * duration, initial_count),
            ),
            maxfev=20_000,
        )
    except (RuntimeError, ValueError) as error:
        return {
            "accepted": False,
            "reason": f"fit failed: {error}",
            "loss_fraction": loss_fraction,
        }

    fitted = model(elapsed, *parameters)
    residual_sum = float(np.sum((counts - fitted) ** 2))
    total_sum = float(np.sum((counts - counts.mean()) ** 2))
    r_squared = 1.0 - residual_sum / total_sum if total_sum > 0 else float("nan")
    tau_s, plateau_count = map(float, parameters)
    tau_std_s = float(np.sqrt(covariance[0, 0])) if covariance.size else float("nan")
    accepted = bool(np.isfinite(r_squared) and r_squared >= min_r_squared)
    return {
        "accepted": accepted,
        "reason": "accepted" if accepted else "fit R-squared is below threshold",
        "tau_s": tau_s,
        "tau_std_s": tau_std_s,
        "plateau_count": plateau_count,
        "loss_fraction": loss_fraction,
        "r_squared": float(r_squared),
        "fitted_counts": fitted,
    }


def analyze_results(results, time_points):
    """Build instantaneous and peak-cohort retention curves for one profile."""
    masks = inside_capture_masks(
        results,
        time_points,
        Geometry.MOT_3D_CENTER_M,
        MOT_3D_CAPTURE_CONFIG["capture_radius_m"],
    )
    instantaneous, peak_index, retained, cohort_indices = retention_from_masks(masks)
    elapsed = np.asarray(time_points[peak_index:], dtype=float) - time_points[peak_index]
    fit = fit_retention_lifetime(elapsed, retained)
    return {
        "instantaneous_counts": instantaneous,
        "peak_index": peak_index,
        "peak_time_s": float(time_points[peak_index]),
        "peak_count": int(instantaneous[peak_index]),
        "cohort_indices": cohort_indices,
        "retained_counts": retained,
        "elapsed_post_peak_s": elapsed,
        "fit": fit,
    }


def _json_ready_analysis(analysis):
    fit = {key: value for key, value in analysis["fit"].items() if key != "fitted_counts"}
    return {
        "peak_time_s": analysis["peak_time_s"],
        "peak_count": analysis["peak_count"],
        "instantaneous_counts": analysis["instantaneous_counts"].tolist(),
        "retained_counts": analysis["retained_counts"].tolist(),
        "elapsed_post_peak_s": analysis["elapsed_post_peak_s"].tolist(),
        "fit": fit,
    }


def plot_comparison(time_points, analyses, output_path):
    """Plot instantaneous occupancy and continuous retention for all profiles."""
    fig, (occupancy_ax, retention_ax) = plt.subplots(2, 1, figsize=(10, 9))
    time_ms = np.asarray(time_points) * 1e3

    for profile_name, analysis in analyses.items():
        occupancy_ax.plot(
            time_ms,
            analysis["instantaneous_counts"],
            label=profile_name,
        )
        occupancy_ax.axvline(
            analysis["peak_time_s"] * 1e3,
            color=occupancy_ax.lines[-1].get_color(),
            alpha=0.25,
            linestyle="--",
        )

        retained = analysis["retained_counts"].astype(float)
        normalized = retained / retained[0] if retained.size and retained[0] else retained
        elapsed_ms = analysis["elapsed_post_peak_s"] * 1e3
        retention_ax.step(
            elapsed_ms,
            normalized,
            where="post",
            label=profile_name,
        )
        fit = analysis["fit"]
        if fit.get("accepted"):
            fitted = np.asarray(fit["fitted_counts"]) / retained[0]
            retention_ax.plot(
                elapsed_ms,
                fitted,
                linestyle="--",
                color=retention_ax.lines[-1].get_color(),
                label=f"{profile_name} fit: tau={fit['tau_s'] * 1e3:.2f} ms",
            )

    occupancy_ax.set_title("Instantaneous population inside the capture region")
    occupancy_ax.set_xlabel("simulation time [ms]")
    occupancy_ax.set_ylabel("atom count")
    occupancy_ax.grid(alpha=0.25)
    occupancy_ax.legend()

    retention_ax.set_title("Continuous retention of the peak population")
    retention_ax.set_xlabel("time since profile-specific population peak [ms]")
    retention_ax.set_ylabel("retained fraction of peak cohort")
    retention_ax.set_ylim(-0.03, 1.03)
    retention_ax.grid(alpha=0.25)
    retention_ax.legend()

    fig.tight_layout()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def run_study(args):
    """Run all requested profiles and save a comparison plot and JSON report."""
    unknown = sorted(set(args.profiles) - set(MOT_3D_CONFIGURATIONS))
    if unknown:
        raise ValueError(f"Unknown 3D-MOT profiles: {unknown}")
    if args.dt <= 0 or args.t_max <= 0:
        raise ValueError("dt and t_max must be positive.")

    states, input_files = load_shared_ensemble(
        args.input,
        max_atoms=args.max_atoms,
        seed=args.seed,
    )
    time_points = np.linspace(0.0, args.t_max, int(np.ceil(args.t_max / args.dt)) + 1)
    analyses = {}

    for profile_name in args.profiles:
        print(f"Running {profile_name} with {len(states)} shared input atoms...")
        profile = copy.deepcopy(MOT_3D_CONFIGURATIONS[profile_name])
        results, _ = mot_3d_simulation(
            states,
            _3d_mot_config=profile,
            gravity_enabled=not args.no_gravity,
            npools=args.npools,
            dt=args.dt,
            t_max=args.t_max,
            seed=args.seed,
        )
        analysis = analyze_results(results, time_points)
        analyses[profile_name] = analysis
        fit = analysis["fit"]
        tau_text = (
            f"tau={fit['tau_s'] * 1e3:.3f} ms, R2={fit['r_squared']:.4f}"
            if fit.get("accepted")
            else f"tau not reported ({fit['reason']})"
        )
        print(
            f"  peak={analysis['peak_count']} at "
            f"{analysis['peak_time_s'] * 1e3:.3f} ms; {tau_text}"
        )
        del results
        gc.collect()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_path = output_dir / "retention_comparison.png"
    summary_path = output_dir / "retention_summary.json"
    plot_comparison(time_points, analyses, plot_path)

    summary = {
        "purpose": "compare continuous retention of each profile's peak cohort",
        "input_files": [str(path) for path in input_files],
        "input_particle_count": int(len(states)),
        "profiles": list(args.profiles),
        "shared_seed": int(args.seed),
        "dt_s": float(args.dt),
        "t_max_s": float(args.t_max),
        "gravity_enabled": not args.no_gravity,
        "capture_radius_m": MOT_3D_CAPTURE_CONFIG["capture_radius_m"],
        "retention_definition": (
            "atoms inside the spherical capture region at the profile-specific "
            "instantaneous population peak that never leave it afterward"
        ),
        "fit_model": "N_inf + (N0 - N_inf) * exp(-elapsed_time / tau)",
        "fit_acceptance": {
            "minimum_loss_fraction": DEFAULT_MIN_LOSS_FRACTION,
            "minimum_r_squared": DEFAULT_MIN_FIT_R_SQUARED,
        },
        "time_points_s": time_points.tolist(),
        "results": {
            name: _json_ready_analysis(analysis)
            for name, analysis in analyses.items()
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Saved plot: {plot_path}")
    print(f"Saved summary: {summary_path}")
    return analyses, plot_path, summary_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--profiles", nargs="+", default=list(DEFAULT_PROFILES))
    parser.add_argument("--max-atoms", type=int)
    parser.add_argument("--npools", type=int, default=DEFAULT_NUM_POOLS)
    parser.add_argument("--dt", type=float, default=MOT_3D_SIM_CONFIG["dt_s"])
    parser.add_argument("--t-max", type=float, default=MOT_3D_SIM_CONFIG["t_max_s"])
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    parser.add_argument("--no-gravity", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_study(parse_args())
