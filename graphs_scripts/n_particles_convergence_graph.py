import numpy as np
import matplotlib.pyplot as plt


# ============================================================
# N-particles convergence data
# ============================================================

N_initial = np.array([
    1000,
    2500,
    5000,
    10000,
    20000,
    30000,
    50000,
    75000,
    100000,
])

N_zeeman_survivors = np.array([
    577,
    1408,
    2831,
    5629,
    11290,
    16967,
    28261,
    42214,
    56528,
])

N_mot_success = np.array([
    9,
    23,
    55,
    116,
    228,
    322,
    579,
    840,
    1057,
])


# ============================================================
# MOT capture efficiency conditioned on Zeeman survival
# ============================================================

efficiency = N_mot_success / N_zeeman_survivors

# Binomial statistical uncertainty:
# sigma_p = sqrt[p(1-p)/N]
efficiency_err = np.sqrt(
    efficiency * (1 - efficiency)
    / N_zeeman_survivors
)


# ============================================================
# Plot
# ============================================================

fig, ax = plt.subplots(figsize=(8, 5))

ax.errorbar(
    N_initial,
    100 * efficiency,
    yerr=100 * efficiency_err,
    fmt="o",
    capsize=4,
)

# Production choice
ax.axvline(
    50000,
    linestyle="--",
    label=r"selected $N = 50{,}000$",
)

ax.set_xlabel(r"Number of initial simulated atoms $N$")
ax.set_ylabel(
    r"MOT capture efficiency "
    r"$N_{\mathrm{MOT}}/N_{\mathrm{Zeeman}}$ (%)"
)

ax.set_title("Particle-number convergence")

ax.grid(alpha=0.25)
ax.legend()

plt.tight_layout()
plt.show()