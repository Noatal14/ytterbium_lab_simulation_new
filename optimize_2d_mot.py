import argparse
import optuna
from config import (
    N_particles,
    zeeman_field_config,
    zeeman_laser_config,
    _2d_mot_laser_config,
    _2d_mot_magnet_radius,
)
from pathlib import Path
from utils.file_helpers import (
    read_data_json,
    save_file_json,
    update_json_file,
)
from split_simulation import zeeman_simulation, mot_simulation


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--npools",
        type=int,
        default=8,
        help="Number of worker processes",
    )

    return parser.parse_args()


def run_zeeman(npools=8):
    print("Running Zeeman phase simulation...")

    _, survivors, _ = zeeman_simulation(
        N_particles=N_particles,
        _2d_mot_config=_2d_mot_laser_config,
        zeeman_config=zeeman_laser_config,
        zeeman_field_config=zeeman_field_config,
        magnet_radius=_2d_mot_magnet_radius,
        stochastic=True,
        npools=npools,
    )

    save_dir = "data"
    save_path = Path(save_dir)

    save_file_json(
        save_path / "zeeman_survivors_states.json",
        survivors,
    )


def run_mot(s0, detuning_gamma, magnet_radius, npools=8):
    path = "data/zeeman_survivors_states.json"

    survivors = read_data_json(path)

    print(
        f"Running MOT phase simulation "
        f"s0={s0}, "
        f"detuning_gamma={detuning_gamma}, "
        f"magnet_radius={magnet_radius}..."
    )

    _, success_count, mot_survivor_states = mot_simulation(
        survivor_states=survivors,
        _2d_mot_config={
            "s0": s0,
            "detuning_gamma": detuning_gamma,
        },
        magnet_radius=magnet_radius,
        stochastic=True,
        npools=npools,
    )

    print(f"Success count: {success_count}")

    data_to_push = {
        "s0": s0,
        "detuning_gamma": detuning_gamma,
        "magnet_radius": magnet_radius,
        "success_count": success_count,
    }

    save_dir = "data"
    save_path = Path(save_dir)

    update_json_file(
        save_path / "mot_summary.json",
        f"s0_{s0}_detuning_gamma_{detuning_gamma}_magnet_radius_{magnet_radius}",
        data_to_push,
    )

    return success_count


def optimize_mot(
    s0_range,
    detuning_gamma_range,
    magnet_radius_range,
    n_trials=50,
    npools=8,
):
    def objective(trial):
        s0 = trial.suggest_float(
            "s0",
            *s0_range,
        )

        detuning_gamma = trial.suggest_float(
            "detuning_gamma",
            *detuning_gamma_range,
        )

        magnet_radius = trial.suggest_float(
            "magnet_radius",
            *magnet_radius_range,
        )

        success_count = run_mot(
            s0=s0,
            detuning_gamma=detuning_gamma,
            magnet_radius=magnet_radius,
            npools=npools,
        )

        return success_count

    study = optuna.create_study(
        study_name="mot_optimization",
        storage="sqlite:///mot_optimization.db",
        direction="maximize",
        load_if_exists=True,
    )

    study.optimize(
        objective,
        n_trials=n_trials,
    )

    print("\n==============================")
    print("MOT optimization finished")
    print("==============================")

    print(f"Best success count: {study.best_value}")

    print("\nBest parameters:")
    print(f"s0             = {study.best_params['s0']}")
    print(f"detuning_gamma = {study.best_params['detuning_gamma']}")
    print(f"magnet_radius  = {study.best_params['magnet_radius']}")

    return study


if __name__ == "__main__":
    args = parse_args()

    BOUNDS_DETUNING = (-2, -0.6)
    BOUNDS_MAGNET_RADIUS = (0.045, 0.054)
    BOUNDS_S0 = (0.8, 2.0)

    run_zeeman(
        npools=args.npools,
    )

    study = optimize_mot(
        s0_range=BOUNDS_S0,
        detuning_gamma_range=BOUNDS_DETUNING,
        magnet_radius_range=BOUNDS_MAGNET_RADIUS,
        n_trials=50,
        npools=args.npools,
    )