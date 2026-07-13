import numpy as np
import matplotlib.pyplot as plt
from dt_comparison.consts import F_scale
from scipy import constants as csts
from config import zeeman_configs, Geometry
from atomsmltr.simulation.simulator import RK4St
from config import Geometry
from lab_setup.config_builder import build_zeeman_config
from utils.simulation_helpers import entry_initial_condition
from lab_setup.zones import get_entire_apparatus_zone

def calc(
        vel_range, 
        distance_from_pick,
        distance_from_origin,
        sim
    ):
    for v in range(vel_range[0], vel_range[1], 1):
        r_vec_plus, v_vec_plus = entry_initial_condition(
            v0=v, 
            r0=distance_from_origin, 
            angle_deg=Geometry.ZEEMAN_ARM_ANGLE_DEG,
            pos_offset=(0.0, 0.0, -distance_from_pick)
        )

        F_plus_vec = sim.get_force(np.concatenate((r_vec_plus, v_vec_plus)))
        F_plus = np.linalg.norm(F_plus_vec)
        
        print("vel ", v, "z ", -distance_from_origin, " Normalized F ", F_plus/F_scale)


    #     results.append({
    #         "v": v,
    #         "F_plus": F_plus,
    #         "F_plus_norm": F_plus / F_scale,
    #     })

    # for res in results:
    #     print(
    #         f"v={res['v']:2d} m/s | "
    #         f"F+={res['F_plus']:.3e} N | "
    #         f"F_plus_norm={res['F_plus_norm']:.3f} | "
    #     )

    
    # v_values = [result["v"] for result in results]
    # F_plus_norm_values = [result["F_plus_norm"] for result in results]

    # plt.figure(figsize=(8, 5))

    # plt.plot(
    #     v_values,
    #     F_plus_norm_values,
    #     marker="o",
    #     markersize=3,
    #     linewidth=1,
    # )

    # plt.xlabel("v")
    # plt.ylabel(r"$F_+/F_{\mathrm{scale}}$")
    # plt.title(r"Beam force vs. velocity")
    # plt.grid(True, which="both", alpha=0.3)
    # plt.legend()
    # plt.tight_layout()
    # plt.show()


def calc_f_min_zeeman(
    s0,
    detuning_gamma,
):
    vel_range_1 = [100, 190]
    vel_range_2 = [190, 325]
    mot_vel_range = [1, 50]

    L1 = 0.360
    L2 = 0.310
    L_mot = 0

    radii, positions, tilt_angles = zeeman_configs["80_2"]

    _, config = build_zeeman_config(
        s0_zeeman=s0,
        detuning_gamma_zeeman=detuning_gamma,
        gravity_enabled=False,
        include_mot_lasers=False,
        include_zeeman_field=True,
        include_zeeman_laser=True,
        radii=radii,
        positions=positions,
        tilt_angles=tilt_angles,
        zones=get_entire_apparatus_zone()
    )

    sim = RK4St(config)

    results = []

    calc(
        vel_range=mot_vel_range,
        distance_from_pick=0,
        distance_from_origin=L_mot,
        sim=sim
    )

    # Range 1
    # =======

    # calc(
    #     vel_range=vel_range_1,
    #     distance_from_pick=Geometry.ZEEMAN_ARM_1_RADIUS/2,
    #     distance_from_origin=L1,
    #     sim=sim
    # )

    # Range 2
    # =======

    # calc(
    #     vel_range=vel_range_2,
    #     distance_from_pick=Geometry.ZEEMAN_ARM_2_RADIUS/2,
    #     distance_from_origin=L2,
    #     sim=sim
    # )
    

if __name__ == "__main__":
    # F_min, F_min_norm, threshold_result, results = calc_f_min_zeeman(
    #     detuning_gamma=-1.2,
    #     s0=1.5,
    #     magnet_radius=0.055
    # )

    calc_f_min_zeeman(
        detuning_gamma=-13.75,
        s0=3.0,
    )

    # print("F_min =", F_min)
    # print("F_min / F_scale =", F_min_norm)
    # print("chosen result =", threshold_result)