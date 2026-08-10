import argparse

from split_simulation import mot_simulation
from pathlib import Path
from utils.file_helpers import read_data_json, save_file_json


MOT_DT = 8e-6


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--zeeman-dt",
        type=float,
        required=True,
        help="Timestep used in the Zeeman simulation",
    )

    parser.add_argument(
        "--npools",
        type=int,
        default=8,
        help="Number of worker processes",
    )

    parser.add_argument(
        "--n-values",
        type=int,
        nargs="+",
        default=[1000, 10000, 50000, 100000],
        help="List of initial particle counts",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    zeeman_dt = args.zeeman_dt
    npools = args.npools
    N_vals = args.n_values

    for N in N_vals:
        path = (
            "find_n_particles/"
            f"zeeman_survivors_dt_{zeeman_dt:.1e}/"
            f"N_{N}_survivors.json"
        )

        survivors = read_data_json(path)

        n_zeeman_survivors = len(survivors)

        print(
            f"Loaded {n_zeeman_survivors} Zeeman survivors "
            f"for N={N}, Zeeman dt={zeeman_dt:.2e}"
        )

        print(
            f"Running MOT simulation with "
            f"MOT dt={MOT_DT:.2e}, npools={npools}..."
        )

        _, success_count, mot_survivor_states = mot_simulation(
            survivor_states=survivors,
            _2d_mot_config={
                "s0": 1.4,
                "detuning_gamma": -1.47,
            },
            magnet_radius=0.053,
            seed=42,
            npools=npools,
            stochastic=True,
            dt=MOT_DT,
        )

        capture_fraction_total = success_count / N
        capture_fraction_from_zeeman = (
            success_count / n_zeeman_survivors
            if n_zeeman_survivors > 0
            else 0.0
        )

        print(f"N={N}")
        print(f"Zeeman survivors: {n_zeeman_survivors}")
        print(f"MOT captured: {success_count}")
        print(
            f"Total capture fraction: "
            f"{capture_fraction_total:.6e}"
        )
        print(
            f"MOT capture fraction among Zeeman survivors: "
            f"{capture_fraction_from_zeeman:.6e}"
        )

        save_dir = Path(
            "find_n_particles/"
            f"mot_results_zeeman_dt_{zeeman_dt:.1e}"
        )
        save_dir.mkdir(parents=True, exist_ok=True)

        save_file_json(
            save_dir / f"N_{N}_mot_survivors.json",
            mot_survivor_states,
        )

        summary = {
            "N_initial": N,
            "zeeman_dt": zeeman_dt,
            "mot_dt": MOT_DT,
            "n_zeeman_survivors": n_zeeman_survivors,
            "n_captured": success_count,
            "capture_fraction_total": capture_fraction_total,
            "capture_fraction_from_zeeman_survivors":
                capture_fraction_from_zeeman,
        }

        save_file_json(
            save_dir / f"N_{N}_summary.json",
            summary,
        )