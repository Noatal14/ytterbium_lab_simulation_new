"""Independent illustrative trajectories; never modifies campaign artifacts.

Run as a module from the repository root. One job runs both families sequentially.
Raw states are sampled every 100 us for plotting; capture is evaluated at every
integration output (10 us). This small sample is not a finalist validation run.
"""
import argparse
import gc
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
import numpy as np


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plot(path, output):
    with np.load(path, allow_pickle=False) as data:
        time = data["time_s"]*1000
        vz, initial = data["states"][:, 5, :], data["initial_states"][:, 5]
        captured = data["captured_at_end"]
    metadata = json.loads(path.with_suffix(".json").read_text())
    fig, ax = plt.subplots(figsize=(11, 7), layout="constrained")
    norm = Normalize(float(initial.min()), float(initial.max()))
    cmap = plt.get_cmap("coolwarm")
    # Select by initial velocity alone, before consulting capture outcomes.
    # A deterministic nearest-bin-center representative avoids outcome bias.
    bins = np.floor(initial).astype(int)
    selected = np.array([members[np.argmin(np.abs(initial[members]-(b+.5)))]
                         for b in np.unique(bins) for members in [np.flatnonzero(bins == b)]])
    shown_captured = selected[captured[selected]]
    missed = selected[~captured[selected]]
    visible = time <= 30.+1e-9
    for i in shown_captured:
        ax.plot(time[visible], vz[i, visible], color=cmap(norm(initial[i])), alpha=1.0, linewidth=1.6, zorder=2)
    for i in missed:
        ax.plot(time[visible], vz[i, visible], color="#545b62",
                alpha=.35, linewidth=1.1, zorder=1)
    threshold = metadata["maximum_speed_m_s"]
    for sign in (-1, 1):
        ax.axhline(sign*threshold, color="#333333", linestyle=":", linewidth=1)
    ax.set(xlabel="Simulation time (ms)", ylabel=r"Longitudinal velocity $v_z$ (m/s)",
           xlim=(0, 30))
    ax.grid(alpha=.18)
    fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=ax,
                 label=r"Initial longitudinal velocity $v_{z,0}$ (m/s)")
    output.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "pdf"):
        fig.savefig(output/f"05_velocity_time_{metadata['family']}.{extension}", dpi=220, bbox_inches="tight")
    plt.close(fig)


def run(args):
    from simulations.mot_3d import mot_3d_simulation
    from studies.mot_3d.analysis.retention import analyze_results
    from studies.mot_3d_campaign import load_all_frozen_particles
    from config import MOT_3D_CAPTURE_CONFIG

    root = args.campaign
    manifest = root/"campaign.json"
    all_states, all_ids, provenance = load_all_frozen_particles(manifest)
    if not 0 < args.atoms <= len(all_states):
        raise ValueError("Invalid sample size")
    indices = np.sort(np.random.default_rng(54001).choice(len(all_states), args.atoms, replace=False))
    initial = all_states[indices]
    args.output.mkdir(parents=True, exist_ok=False)
    dt = 1e-5
    time = np.linspace(0, args.t_max, int(np.ceil(args.t_max/dt))+1)
    for family, candidate_index in (("angled_donut", 1), ("single_pass", 0)):
        selection_path = root/"selection/finalists"/(family+".json")
        candidate = json.loads(selection_path.read_text())["candidates"][candidate_index]
        print(f"START {family} {candidate['candidate_id']} atoms={len(initial)}", flush=True)
        trajectories, _ = mot_3d_simulation(initial.copy(), _3d_mot_config=candidate["resolved_profile"],
                          gravity_enabled=True, npools=args.npools, dt=dt, t_max=args.t_max, seed=54002)
        analysis = analyze_results(trajectories, time)
        masks = analysis["eligible_masks"]
        # Save decimated full six-component states; keep actual timestamps and
        # NaNs beyond terminated trajectories rather than inventing continuation.
        sample_indices = np.unique(np.r_[np.arange(0, len(time), 10), len(time)-1])
        saved = np.full((len(initial), 6, len(sample_indices)), np.nan, dtype=np.float32)
        for i, trajectory in enumerate(trajectories):
            times = np.asarray(trajectory.t)
            selected = sample_indices[sample_indices < len(times)]
            if not np.allclose(times[selected], time[selected], rtol=0, atol=1e-12):
                raise ValueError("Trajectory output grid differs from expected grid")
            saved[i, :, :len(selected)] = np.asarray(trajectory.y)[:6, selected]
        path = args.output/(family+".npz")
        np.savez_compressed(path, time_s=time[sample_indices], states=saved, initial_states=initial,
                            global_particle_indices=indices, ensemble_ids=all_ids[indices],
                            captured_ever=np.any(masks, axis=1), captured_at_end=masks[:, -1])
        metadata = dict(family=family, candidate_id=candidate["candidate_id"], candidate=candidate,
                        input_manifest_sha256=digest(manifest), selection_sha256=digest(selection_path),
                        script_sha256=digest(__file__), source_provenance=provenance,
                        selection_seed=54001, recoil_seed=54002, dt_s=dt, t_max_s=args.t_max,
                        npools=args.npools, atom_count=len(initial),
                        maximum_speed_m_s=MOT_3D_CAPTURE_CONFIG["maximum_final_speed_m_s"],
                        capture_definition="Campaign analyze_results eligible_masks; ever means eligible at least once",
                        selection_reason="Best available mean among three-seed-complete finalists at submission; provisional",
                        outcomes_sha256=digest(path))
        path.with_suffix(".json").write_text(json.dumps(metadata, indent=2)+"\n")
        plot(path, args.graphs)
        print(f"DONE {family} captured_ever={np.any(masks, axis=1).sum()}/{len(initial)}", flush=True)
        del trajectories, analysis, masks, saved
        gc.collect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--graphs", type=Path, default=Path("graphs/report_optimization"))
    parser.add_argument("--atoms", type=int, default=600)
    parser.add_argument("--npools", type=int, default=200)
    parser.add_argument("--t-max", type=float, default=.1)
    args = parser.parse_args()
    if args.npools < 1 or args.t_max <= 0:
        parser.error("npools and t-max must be positive")
    run(args)


if __name__ == "__main__":
    main()
