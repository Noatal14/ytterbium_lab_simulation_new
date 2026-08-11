import numpy as np
import matplotlib.pyplot as plt

if __name__ == "__main__":
    dt_us = np.array([100, 80, 60, 40, 30, 25, 20, 10])

    zeeman_survivors = np.array([
        46062,
        44993,
        44797,
        44253,
        44126,
        43955,
        43959,
        43914,
    ])

    N_initial = 50000

    survival_fraction = zeeman_survivors / N_initial
    survival_percent = 100 * survival_fraction


    # Sort by increasing dt for plotting
    order = np.argsort(dt_us)

    dt_us = dt_us[order]
    zeeman_survivors = zeeman_survivors[order]
    survival_percent = survival_percent[order]


    fig, ax = plt.subplots(figsize=(7, 4.5))

    ax.plot(
        dt_us,
        survival_percent,
        marker="o",
        linewidth=1.8,
    )

    ax.axvline(
        15.9,
        linestyle="--",
        linewidth=1.5,
        label=r"Gaussian lower bound: $15.9\,\mu$s",
    )

    ax.legend()

    p = zeeman_survivors / N_initial
    sigma_p = np.sqrt(p * (1 - p) / N_initial)

    ax.errorbar(
        dt_us,
        100 * p,
        yerr=100 * sigma_p,
        marker="o",
        capsize=3,
    )

    ax.set_xlabel(r"Zeeman timestep $dt_Z$ [$\mu$s]")
    ax.set_ylabel("Zeeman survival fraction [%]")

    ax.grid(alpha=0.3)

    fig.tight_layout()
    plt.show()