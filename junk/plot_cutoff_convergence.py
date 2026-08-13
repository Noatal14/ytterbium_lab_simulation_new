import numpy as np
import matplotlib.pyplot as plt

cutoff_angle = np.array([
    0.5, 0.7, 0.8, 0.9, 1.0, 1.1,
    1.2, 1.3, 1.5, 2.0, 3.0, 5.0
])

n_zeeman_survivors = np.array([
    17859, 17648, 16963, 16107, 15441, 15183,
    14677, 14235, 11608, 7757, 4634, 2503
])

n_mot_success = np.array([
    2838, 1574, 1274, 1018, 856, 738,
    637, 566, 458, 292, 182, 109
])

efficiency = n_mot_success / n_zeeman_survivors

# Binomial statistical uncertainty
error = np.sqrt(
    efficiency * (1 - efficiency) / n_zeeman_survivors
)

fig, ax = plt.subplots(figsize=(8, 5))

ax.errorbar(
    cutoff_angle,
    efficiency * 100,
    yerr=error * 100,
    fmt="o-",
    capsize=4,
    label="2D MOT transmission efficiency",
)

ax.axvline(
    1.5,
    linestyle="--",
    linewidth=2,
    label=r"Chosen cutoff: $\theta_{\max}=1.5^\circ$",
)

ax.set_xlabel(r"Thermal-beam cutoff angle $\theta_{\max}$ [deg]", fontsize=14)
ax.set_ylabel("2D MOT transmission efficiency [%]", fontsize=14)
ax.set_title("Thermal-beam cutoff angle convergence", fontsize=17)

ax.tick_params(axis="both", labelsize=12)
ax.grid(alpha=0.3)
ax.legend(fontsize=11)

plt.tight_layout()
plt.savefig("cutoff_angle_convergence.png", dpi=350)
plt.show()