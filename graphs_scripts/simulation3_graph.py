import numpy as np
import matplotlib.pyplot as plt
import scipy.spatial.transform as transform
from utils.file_helpers import read_data_json, read_data_json


def generate_speed_vs_distance(res_list1, res_list2, out_file, N):
    fig, ax = plt.subplots(figsize=(8, 6), layout='constrained')
    for i, res in enumerate(res_list1):
        x_traj = np.array(res["y"])[0, :]
        y_traj = np.array(res["y"])[1, :]
        z_traj = np.array(res["y"])[2, :]
        vx_traj = np.array(res["y"])[3, :]
        vy_traj = np.array(res["y"])[4, :]
        vz_traj = np.array(res["y"])[5, :]
        
        dist_traj = np.sqrt(x_traj**2 + y_traj**2 + z_traj**2)
        speed_traj = np.sqrt(vx_traj**2 + vy_traj**2 + vz_traj**2)
        
        color = plt.cm.viridis(i / len(res_list1))
        ax.plot(dist_traj, speed_traj, color=color, alpha=0.7)
        ax.scatter(dist_traj[0], speed_traj[0], color=color, s=15, marker='x')
        
    for i, res in enumerate(res_list2):
        x_traj = np.array(res["y"])[0, :]
        y_traj = np.array(res["y"])[1, :]
        z_traj = np.array(res["y"])[2, :]
        vx_traj = np.array(res["y"])[3, :]
        vy_traj = np.array(res["y"])[4, :]
        vz_traj = np.array(res["y"])[5, :]
        
        dist_traj = np.sqrt(x_traj**2 + y_traj**2 + z_traj**2)
        speed_traj = np.sqrt(vx_traj**2 + vy_traj**2 + vz_traj**2)
        
        color = plt.cm.viridis(i / len(res_list2))
        ax.plot(dist_traj, speed_traj, color=color, alpha=0.7)
        ax.scatter(dist_traj[0], speed_traj[0], color=color, s=15, marker='x')

    ax.set_title(f"Total Speed vs Distance from Origin [N={N}")
    ax.set_xlabel("Distance from Origin (m)")
    ax.set_ylabel("Total Speed (m/s)")
    ax.set_xlim(ax.get_xlim()[::-1])
    ax.grid(True, alpha=0.3)
    plt.savefig(out_file, dpi=300)
    print(f"✅ Saved Speed Plot: {out_file}")

if __name__ == "__main__":
    zeeman_tarj = read_data_json("junk/simulation_results/zeeman_1000_stoch.json")
    mot_traj = read_data_json("junk/simulation_results/mot_1000_stoch.json")
    generate_speed_vs_distance(res_list1=zeeman_tarj, res_list2=mot_traj, out_file="junk/simulation_results_stoch", N=1000)