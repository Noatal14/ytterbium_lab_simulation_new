"""Central 2D-MOT mean-force phase portrait, not a full apparatus simulation.

The idealized slice fixes x=z=vx=vz=0, excludes Zeeman fields and gravity,
and uses only the winning 2D-MOT configuration. Deterministic trajectories
solve dy/dt=vy and dvy/dt=Fy(y,vy)/m using the actual force evaluator, not
an interpolated background. Initial y=-25 mm; vy=10,12,...,80 m/s.
Run from the repository root with PYTHONPATH=atomsmltr/src:.
"""
import hashlib
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize, TwoSlopeNorm
from matplotlib.cm import ScalarMappable
import numpy as np
from scipy.integrate import solve_ivp

from lab_setup.config_builder import build_base_config
from atomsmltr.simulation.simulator.simbase import get_force_vec

ROOT = Path(__file__).resolve().parents[1]


def main(stochastic=False):
    source = ROOT/"data/optimization/mot_2d/corrected_zeeman_s0_1p3_20261006/winners.json"
    winner = json.loads(source.read_text())["s0_1p300000"]["parameters"]
    laser = {"s0": winner["s0"], "detuning_gamma": winner["detuning_gamma"], "swap_polarization": False}
    atom, config = build_base_config(include_zeeman=False, include_2d_mot=True,
                                    include_3dmot=False, gravity_enabled=False, zones=[],
                                    _2d_mot_config=laser, magnet_radius=winner["magnet_radius"])

    def force(y, vy):
        state = np.zeros((len(np.atleast_1d(y)), 6))
        state[:, 1], state[:, 4] = y, vy
        return get_force_vec(state, config)[:, 1]

    y_grid = np.linspace(-.025, .005, 301)
    velocity_grid = np.linspace(-10., 80., 451)
    yy, vv = np.meshgrid(y_grid, velocity_grid)
    print("Evaluating force grid", flush=True)
    background = force(yy.ravel(), vv.ravel()).reshape(yy.shape)
    if not np.isfinite(background).all():
        raise ValueError("Non-finite mean-force grid")
    # Physical symmetry and restoring-force sanity checks for the isolated slice.
    test_y, test_v = np.array([-.01, -.005, .003]), np.array([30., 10., -5.])
    np.testing.assert_allclose(force(test_y, test_v), -force(-test_y, -test_v), rtol=1e-8, atol=1e-30)
    if not (force(np.array([-.005, .005]), np.zeros(2))*np.array([-.005, .005]) < 0).all():
        raise ValueError("Mean force is not restoring at zero velocity")
    initial = np.arange(10., 80.1, 2.)
    n = len(initial)
    u0 = np.r_[np.full(n, -.025), initial]

    def rhs(t, u):
        return np.r_[u[n:], force(u[:n], u[n:])/atom.mass]

    if stochastic:
        from utils.RK4StHybridCustom import RK4StHybridCustom
        dt=6.25e-7
        times=np.arange(8001)*dt
        solver=RK4StHybridCustom(config)
        solver.rng=np.random.default_rng(55001)
        state=np.zeros((n,6));state[:,1]=-.025;state[:,4]=initial
        history=np.empty((len(times),n,2));history[0]=state[:,[1,4]]
        print(f"Integrating {n} stochastic projected trajectories",flush=True)
        for step in range(1,len(times)):
            state+=solver._iterate(times[step-1],state,dt)
            # Constrain the other degrees of freedom to the central slice.
            # The y recoil is sampled by the same hybrid kernel as production.
            state[:,[0,2,3,5]]=0.
            if not np.isfinite(state).all():raise ValueError("Non-finite stochastic state")
            history[step]=state[:,[1,4]]
            if step%2000==0:print(f"Step {step}/{len(times)-1}",flush=True)
        solution=SimpleNamespace(t=times,y=np.r_[history[:,:,0].T,history[:,:,1].T])
    else:
        print(f"Integrating {n} mean-force trajectories", flush=True)
        times = np.linspace(0, .02, 20001)
        solution = solve_ivp(rhs, (0., .02), u0, t_eval=times, rtol=1e-7,
                             atol=np.r_[np.full(n, 1e-10), np.full(n, 1e-6)], max_step=2e-5)
        if not solution.success:
            raise RuntimeError(solution.message)
    fig, ax = plt.subplots(figsize=(10.5, 7), layout="constrained")
    limit = float(np.max(np.abs(background)))
    image = ax.pcolormesh(1000*y_grid, velocity_grid, background, shading="auto",
                         cmap="bwr", norm=TwoSlopeNorm(vmin=-limit, vcenter=0., vmax=limit), rasterized=True)
    fig.colorbar(image, ax=ax, location="left", pad=.12, label=r"Mean force $F_y$ (N)")
    cmap, norm = plt.get_cmap("plasma"), Normalize(initial.min(), initial.max())
    for i, v0 in enumerate(initial):
        ax.plot(1000*solution.y[i], solution.y[n+i], color=cmap(norm(v0)), linewidth=1.3)
    fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=ax, pad=.025,
                 label=r"Initial transverse velocity $v_{y,0}$ (m/s)")
    ax.set(xlabel=r"$y$ (mm)", ylabel=r"$v_y$ (m/s)", xlim=(-25, 5), ylim=(-10, 80))
    ax.grid(alpha=.12)
    method = "stochastic recoil trajectories (1D projection)" if stochastic else "deterministic mean-force trajectories"
    fig.supxlabel(r"Central slice: $x=z=v_x=v_z=0$ · "+method+"\n"+
                  rf"$s_0={winner['s0']}$, $\Delta/\Gamma={winner['detuning_gamma']:.6f}$, magnet radius {1000*winner['magnet_radius']:.4f} mm",
                  fontsize=9)
    output = ROOT/"graphs/report_optimization"
    output.mkdir(parents=True, exist_ok=True)
    stem="07_2d_force_phase_portrait"+("_stochastic" if stochastic else "")
    for extension in ("pdf", "png"):
        fig.savefig(output/f"{stem}.{extension}", dpi=220, bbox_inches="tight")
    plt.close(fig)
    data = ROOT/("data/validation/mot_2d/report_force_phase_portrait"+("_stochastic" if stochastic else ""))
    data.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(data/"phase_portrait.npz", y_m=y_grid, vy_m_s=velocity_grid,
                        force_y_N=background, time_s=solution.t, trajectory_y_m=solution.y[:n],
                        trajectory_vy_m_s=solution.y[n:], initial_vy_m_s=initial)
    metadata = {"method": __doc__, "winning_parameters": winner, "mass_kg": atom.mass,
                "winning_record_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "solver": "RK4StHybridCustom._iterate, central-slice projection" if stochastic else "scipy.solve_ivp RK45, direct atomsmltr mean-force evaluation",
                "stochastic":stochastic,"seed":55001 if stochastic else None,
                "dt_s":6.25e-7 if stochastic else None,
                "rtol": None if stochastic else 1e-7, "t_max_s": float(times[-1]), "n_trajectories": n, "force_limit_N": limit}
    (data/"phase_portrait.json").write_text(json.dumps(metadata, indent=2)+"\n")
    print(output/(stem+".pdf"), flush=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stochastic",action="store_true",help="Use production hybrid recoil kernel, projected onto y")
    main(parser.parse_args().stochastic)
