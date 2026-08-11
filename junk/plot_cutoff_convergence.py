import numpy as np
import matplotlib.pyplot as plt


# High-statistics cutoff scan
angles_deg = np.array([
    0.5, 0.7, 0.8, 0.9, 1.0, 1.1,
    1.2, 1.3, 1.5, 2.0, 3.0, 5.0
])

n_zeeman = np.array([
    11392, 11241, 10872, 10304, 9503, 8741,
    8165, 7499, 6301, 4285, 2599, 1428
])

n_mot_success = np.array([
    2898, 1604, 1289, 1052, 877, 756,
    656, 564, 465, 322, 192, 111
])


# Conditional transmission:
# P(MOT/DPS success | Zeeman survivor)
efficiency = n_mot_success / n_zeeman

# Binomial standard error
efficiency_err = np.sqrt(
    efficiency * (1.0 - efficiency) / n_zeeman
)


# Convert to percent for plotting
efficiency_percent = 100.0 * efficiency
efficiency_err_percent = 100.0 * efficiency_err


# Selected cutoff
selected_cutoff = 1.5


fig, ax = plt.subplots(figsize=(9, 6))

ax.errorbar(
    angles_deg,
    efficiency_percent,
    yerr=efficiency_err_percent,
    fmt="o-",
    capsize=4,
    linewidth=1.5,
    markersize=6,
    label=r"$\eta_{\mathrm{MOT|ZS}}$",
)

# Mark selected cutoff
ax.axvline(
    selected_cutoff,
    linestyle="--",
    linewidth=1.5,
    label=r"Selected cutoff: $1.5^\circ$",
)

ax.set_xlabel(r"Angular cutoff $\theta_{\mathrm{cutoff}}$ [deg]", fontsize=12)
ax.set_ylabel(
    r"$\eta_{\mathrm{MOT|ZS}}$ [%]",
    fontsize=12,
)

ax.set_title(
    "Thermal-Beam Angular Cutoff Convergence",
    fontsize=15,
)

ax.grid(alpha=0.25)
ax.legend()

plt.tight_layout()

plt.savefig(
    "thermal_beam_cutoff_convergence.png",
    dpi=300,
    bbox_inches="tight",
)

plt.show()