import optuna
from config import zeeman_configs, N_particles
from pathlib import Path
from utils.file_helpers import read_data_json, save_file_json, update_json_file
from split_simulation import zeeman_simulation, mot_simulation

def run_zeeman():
    print(f"Running Zeeman phase simulation...")
    radii, positions, tilt_angles = zeeman_configs["80_2"]

    zeeman_traj, survivors, surv_idx = zeeman_simulation(
        N_particles=N_particles,
        _2d_mot_config={ "s0": 1.4, "detuning_gamma": -1.47 },
        zeeman_config={ "s0": 3.0, "detuning_gamma": -13.75 },
        zeeman_field_config={ "radii": radii, "positions": positions, "tilt_angles": tilt_angles },
        magnet_radius=0.053,
        T_C=400.0,
        stochastic=True
    )

    save_dir = "data"
    save_path = Path(save_dir)

    save_file_json(save_path / "zeeman_survivors_states.json", survivors)

def run_mot(s0, detuning_gamma, magnet_radius):
    path = (
        "data/"
        "zeeman_survivors_states.json"
    )

    survivors = read_data_json(path)

    print(f"Running MOT phase simulation s0={s0}, detuning_gamma={detuning_gamma}, magnet_radius={magnet_radius}...")

    _, success_count, mot_survivor_states = mot_simulation(
        survivor_states=survivors,
        _2d_mot_config={ "s0": s0, "detuning_gamma": detuning_gamma },
        magnet_radius=magnet_radius,
        stochastic=True
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

    update_json_file(save_path / "mot_summary.json", f"s0_{s0}_detuning_gamma_{detuning_gamma}_magnet_radius_{magnet_radius}", data_to_push)

    return success_count


def optimize_mot(
    s0_range,
    detuning_gamma_range,
    magnet_radius_range,
    n_trials=50,
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
    BOUNDS_DETUNING = (-2, -0.6)
    BOUNDS_MAGNET_RADIUS = (0.045, 0.054)
    BOUNDS_S0 = (0.8, 2.0)

    run_zeeman()

    study = optimize_mot(
        s0_range=BOUNDS_S0,
        detuning_gamma_range=BOUNDS_DETUNING,
        magnet_radius_range=BOUNDS_MAGNET_RADIUS,
        n_trials=50
    )