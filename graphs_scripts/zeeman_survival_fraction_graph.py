import numpy as np
import matplotlib.pyplot as plt

N_INITIAL = 50000

# Combined fixed-survivor scan + zoom-in scan
dt_us = np.array([
    5.0,
    7.5,
    10.0,
    12.5,
    15.0,
    20.0,
    25.0,
    30.0,
    40.0,
    60.0,
    80.0,
    100.0,
])

n_survivors = np.array([
    28340,  # 5 us
    28283,  # 7.5 us
    28069,  # 10 us
    27954,  # 12.5 us
    28156,  # 15 us
    28374,  # 20 us
    28143,  # 25 us
    28050,  # 30 us
    28285,  # 40 us
    28281,  # 60 us
    28896,  # 80 us
    29837,  # 100 us
])

survival_fraction = n_survivors / N_INITIAL

# Binomial sampling uncertainty
survival_error = np.sqrt(
    survival_fraction * (1.0 - survival_fraction) / N_INITIAL
)

chosen_dt = 40.0

# Mean of the visually converged region
converged_mask = dt_us <= 60.0
plateau_mean = np.mean(survival_fraction[converged_mask])

fig, ax = plt.subplots(figsize=(8, 5))

ax.errorbar(
    dt_us,
    survival_fraction,
    yerr=survival_error,
    fmt="o",
    capsize=4,
    label="Simulation results",
)

ax.axhline(
    plateau_mean,
    linestyle="--",
    linewidth=1.8,
    label="Mean for $dt \\leq 60\\,\\mu$s",
)

ax.axvline(
    chosen_dt,
    linestyle=":",
    linewidth=2,
    label="Chosen timestep: $40\\,\\mu$s",
)

ax.set_xlabel("Zeeman timestep $dt$ [$\\mu$s]", fontsize=14)
ax.set_ylabel("Zeeman survivor fraction", fontsize=14)
ax.set_title("Zeeman timestep convergence", fontsize=17)

ax.tick_params(axis="both", labelsize=12)
ax.grid(alpha=0.3)
ax.legend(fontsize=11)

plt.tight_layout()
plt.savefig("zeeman_dt_convergence.png", dpi=350)
plt.show()