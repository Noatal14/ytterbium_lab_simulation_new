import numpy as np
import matplotlib.pyplot as plt


# ============================================================
# Data from MOT timestep convergence scan
# ============================================================

dt_us = np.array([
    100, 80, 60, 50, 40, 35, 30, 25, 20, 15, 10, 8
], dtype=float)

n_success = np.array([
    414, 437, 496, 518, 544, 557,
    540, 532, 545, 580, 562, 596
])

n_total = 28285

efficiency = n_success / n_total

# Binomial statistical uncertainty
efficiency_err = np.sqrt(
    efficiency * (1 - efficiency) / n_total
)


# ============================================================
# Plot
# ============================================================

fig, ax = plt.subplots(figsize=(8, 5))

ax.errorbar(
    dt_us,
    100 * efficiency,
    yerr=100 * efficiency_err,
    fmt="o",
    capsize=4,
    label="simulation",
)

ax.set_xlabel(r"$dt_{\mathrm{MOT}}\;(\mu\mathrm{s})$")
ax.set_ylabel("2D MOT capture efficiency (%)")

ax.set_title("2D MOT Capture Efficiency vs Timestep")

ax.grid(alpha=0.25)
ax.legend()

plt.tight_layout()
plt.show()