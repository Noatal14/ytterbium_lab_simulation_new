import numpy as np
import matplotlib.pyplot as plt
from scipy import constants as csts
from dt_comparison.consts import F_scale

if __name__ == "__main__":
    # -----------------------------
    # Constants
    # -----------------------------
    wavelength = 399e-9
    k = 2 * np.pi / wavelength

    F_scale = 3.141895058426422e-20  # N

    N_min = 15
    F_min_norm = 0.11
    F_min = F_min_norm * F_scale

    dt_opt = 7.232e-6
    dt_small = 0.6 * dt_opt
    dt_large = 1.4 * dt_opt

    # x-axis in normalized force units
    F_norm = np.linspace(0, 1.0, 1000)
    F = F_norm * F_scale

    # -----------------------------
    # Plot
    # -----------------------------
    plt.figure(figsize=(8, 5.5))

    # Softer colored regions
    plt.fill_between([0, F_min_norm], 0, N_min,
                    color="#F9E79F", alpha=0.25, zorder=1,
                    label="Negligible force")

    plt.fill_between([0, F_min_norm], N_min, 100,
                    color="#AED6F1", alpha=0.25, zorder=1,
                    label="Conservative")

    plt.fill_between([F_min_norm, 1.0], 0, N_min,
                    color="#F5B7B1", alpha=0.25, zorder=1,
                    label="Undesired region")

    plt.fill_between([F_min_norm, 1.0], N_min, 100,
                    color="#ABEBC6", alpha=0.25, zorder=1,
                    label="Desired region")

    # dt lines — thinner
    for dt, linestyle, linewidth, color, label in [
        (dt_small, "--", 2.0, "0.45", r"$dt<dt_{\rm opt}$"),
        (dt_opt, "-", 2.8, "black", r"$dt=dt_{\rm opt}$"),
        (dt_large, "--", 2.0, "0.45", r"$dt>dt_{\rm opt}$"),
    ]:
        N = F * dt / (csts.hbar * k)
        plt.plot(F_norm, N, linestyle=linestyle, linewidth=linewidth,
                color=color, label=label, zorder=20)

    # Threshold lines — softer
    plt.axvline(F_min_norm, color="black", linestyle=":", linewidth=1.7, zorder=10)
    plt.axhline(N_min, color="black", linestyle=":", linewidth=1.7, zorder=10)

    plt.scatter(F_min_norm, N_min, color="black", s=65, zorder=30)

    plt.text(
        F_min_norm + 0.005,
        N_min + 0.6,
        r"$(F_{\min},N_{\min})$",
        fontsize=11,
        zorder=30,
    )

    plt.xlabel(r"$F/F_{\mathrm{scale}}$", fontsize=13)
    plt.ylabel(r"$N$", fontsize=13)
    plt.title("Selecting the optimal simulation timestep", fontsize=16)

    plt.xlim(0, 1.0)
    plt.ylim(0, 100)
    plt.grid(alpha=0.18)

    # Legend outside
    plt.legend(
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        fontsize=10,
        frameon=True,
    )

    plt.tight_layout()
    plt.show()