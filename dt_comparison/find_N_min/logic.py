import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import poisson, norm
from scipy import constants as csts

from config import BLUE_TRANSITION, YB171_MASS_KG


def coupled_poisson_gaussian_eta(N, n_samples=100_000, seed=0):
    rng = np.random.default_rng(seed)

    k = 2.0 * np.pi / BLUE_TRANSITION.wavelength
    v_rec = csts.hbar * k / YB171_MASS_KG

    # -------------------------
    # 1. Absorption fluctuation
    # -------------------------
    U_abs = rng.uniform(size=n_samples)

    K_abs_pois = poisson.ppf(U_abs, mu=N)
    K_abs_gauss = norm.ppf(U_abs, loc=N, scale=np.sqrt(N))

    dN_abs_pois = K_abs_pois - N
    dN_abs_gauss = K_abs_gauss - N

    dv_abs_pois = v_rec * dN_abs_pois[:, None]
    dv_abs_gauss = v_rec * dN_abs_gauss[:, None]

    # -------------------------
    # Total stochastic kick
    # -------------------------
    dv_pois = dv_abs_pois
    dv_gauss = dv_abs_gauss

    diff = np.abs(dv_pois - dv_gauss)
    mean_diff = np.mean(diff)

    dv_det = v_rec * N
    eta = mean_diff / dv_det

    return dv_det, mean_diff, eta


if __name__ == "__main__":
    N_values = list(range(1, 51, 1))
    print('N_values ', N_values)

    etas = []
    for N in N_values:
        dv_det, mean_diff, eta = coupled_poisson_gaussian_eta(
            N,
            n_samples=100_000,
            seed=0,
        )
        etas.append(eta)

        print(
            f"N={N:.1f}, "
            f"dv_det={dv_det:.3e} m/s, "
            f"mean_diff={mean_diff:.3e} m/s, "
            f"eta={eta:.4f} ({100 * eta:.2f}%)"
        )

    etas = np.array(etas)

    plt.figure(figsize=(8, 5))
    plt.plot(N_values, etas, marker="o", markersize=3, linewidth=1)

    plt.axhline(0.01, linestyle="--", label="1%")
    plt.axhline(0.02, linestyle="--", label="2%")
    plt.axhline(0.05, linestyle="--", label="5%")

    plt.xlabel("N")
    plt.ylabel(r"$\eta(N)$")
    plt.title("Poisson vs Gaussian stochastic kick error")
    plt.grid(True, which="both", alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.show()