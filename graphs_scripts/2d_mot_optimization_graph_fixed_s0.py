import numpy as np
import matplotlib.pyplot as plt

from scipy.ndimage import gaussian_filter


N_ZEEMAN_SURVIVORS = 28261


def plot_fixed_s0_optimization(
    s0,
    detuning,
    magnet_radius,
    success_count,
    n_zeeman_survivors=N_ZEEMAN_SURVIVORS,
    grid_size=250,
    bandwidth_detuning=0.18,
    bandwidth_radius_mm=0.8,
    density_threshold=0.03,
    save_path=None,
):
    """
    Plot optimization results for a fixed value of s0.

    Parameters
    ----------
    s0 : float
        Fixed saturation parameter.

    detuning : array-like
        Detuning values in units of Gamma.

    magnet_radius : array-like
        Magnet-radius values in meters.

    success_count : array-like
        Number of successfully captured MOT atoms for each trial.

    n_zeeman_survivors : int
        Number of atoms entering the MOT.

    grid_size : int
        Resolution of the interpolation grid.

    bandwidth_detuning : float
        Gaussian-kernel width in detuning units.

    bandwidth_radius_mm : float
        Gaussian-kernel width in mm for magnet radius.

    density_threshold : float
        Regions below this normalized sampling density are nearly transparent.

    save_path : str or None
        If supplied, save the figure to this path.

    Returns
    -------
    fig, ax
        Matplotlib figure and axes.
    """

    # ========================================================
    # Convert inputs
    # ========================================================

    detuning = np.asarray(detuning, dtype=float)
    magnet_radius = np.asarray(magnet_radius, dtype=float)
    success_count = np.asarray(success_count, dtype=float)

    if not (
        len(detuning)
        == len(magnet_radius)
        == len(success_count)
    ):
        raise ValueError(
            "detuning, magnet_radius and success_count "
            "must have the same length."
        )

    radius_mm = 1000.0 * magnet_radius

    efficiency = (
        100.0
        * success_count
        / n_zeeman_survivors
    )

    # ========================================================
    # Build interpolation grid
    # ========================================================

    x_margin = 0.08 * (
        detuning.max() - detuning.min()
    )

    y_margin = 0.10 * (
        radius_mm.max() - radius_mm.min()
    )

    if x_margin == 0:
        x_margin = 0.1

    if y_margin == 0:
        y_margin = 0.5

    x_grid = np.linspace(
        detuning.min() - x_margin,
        detuning.max() + x_margin,
        grid_size,
    )

    y_grid = np.linspace(
        radius_mm.min() - y_margin,
        radius_mm.max() + y_margin,
        grid_size,
    )

    X, Y = np.meshgrid(
        x_grid,
        y_grid,
    )

    # ========================================================
    # Kernel-regression estimate of efficiency
    #
    # Each measured point contributes a Gaussian kernel.
    #
    # numerator   = sum(w_i * eta_i)
    # denominator = sum(w_i)
    #
    # eta_estimated = numerator / denominator
    #
    # The denominator also acts as a local sampling-density
    # estimate.
    # ========================================================

    weighted_efficiency = np.zeros_like(
        X,
        dtype=float,
    )

    density = np.zeros_like(
        X,
        dtype=float,
    )

    for x_i, y_i, eta_i in zip(
        detuning,
        radius_mm,
        efficiency,
    ):

        distance_squared = (
            ((X - x_i) / bandwidth_detuning) ** 2
            +
            ((Y - y_i) / bandwidth_radius_mm) ** 2
        )

        weights = np.exp(
            -0.5 * distance_squared
        )

        density += weights

        weighted_efficiency += (
            weights * eta_i
        )

    # Avoid division by zero
    efficiency_surface = (
        weighted_efficiency
        / np.maximum(density, 1e-12)
    )

    # Small smoothing only for visual appearance
    efficiency_surface = gaussian_filter(
        efficiency_surface,
        sigma=1.0,
    )

    density = gaussian_filter(
        density,
        sigma=1.0,
    )

    # ========================================================
    # Normalize density to [0, 1]
    # ========================================================

    density_normalized = (
        density / density.max()
    )

    # Convert density into alpha:
    #
    # low density  -> almost white
    # high density -> strong background color
    #
    alpha = (
        density_normalized
        - density_threshold
    ) / (
        1.0 - density_threshold
    )

    alpha = np.clip(
        alpha,
        0.0,
        1.0,
    )

    # Don't let the background overpower actual points
    alpha *= 0.70

    # ========================================================
    # Shared color normalization
    # ========================================================

    vmin = efficiency.min()
    vmax = efficiency.max()

    cmap = plt.get_cmap(
        "coolwarm"
    )

    norm = plt.Normalize(
        vmin=vmin,
        vmax=vmax,
    )

    # Convert interpolated values to RGBA
    background_rgba = cmap(
        norm(efficiency_surface)
    )

    # Apply sampling-density-dependent transparency
    background_rgba[..., 3] = alpha

    # ========================================================
    # Plot
    # ========================================================

    fig, ax = plt.subplots(
        figsize=(10, 7)
    )

    # Background:
    # color = predicted efficiency
    # opacity = local sampling density
    ax.imshow(
        background_rgba,
        origin="lower",
        extent=[
            x_grid.min(),
            x_grid.max(),
            y_grid.min(),
            y_grid.max(),
        ],
        aspect="auto",
        interpolation="bilinear",
    )

    # Optional sampling-density contours
    density_levels = [
        0.15,
        0.30,
        0.50,
        0.70,
    ]

    ax.contour(
        X,
        Y,
        density_normalized,
        levels=density_levels,
        linewidths=0.8,
        alpha=0.30,
    )

    # Actual Optuna trials
    scatter = ax.scatter(
        detuning,
        radius_mm,
        c=efficiency,
        cmap=cmap,
        norm=norm,
        s=115,
        edgecolors="black",
        linewidths=1.1,
        zorder=3,
    )

    # ========================================================
    # Annotate each point with capture efficiency
    # ========================================================

    for x, y, eta in zip(
        detuning,
        radius_mm,
        efficiency,
    ):
        ax.annotate(
            f"{eta:.2f}%",
            (x, y),
            xytext=(6, 6),
            textcoords="offset points",
            fontsize=8,
            zorder=4,
        )

    # ========================================================
    # Mark best trial
    # ========================================================

    best_idx = np.argmax(
        efficiency
    )

    ax.scatter(
        detuning[best_idx],
        radius_mm[best_idx],
        marker="*",
        s=330,
        facecolors="none",
        edgecolors="black",
        linewidths=1.8,
        zorder=5,
        label=(
            f"Best trial: {efficiency[best_idx]:.2f}%\n"
            f"$\\Delta/\\Gamma$ = {detuning[best_idx]:.3f}\n"
            f"Magnet radius = {radius_mm[best_idx]:.2f} mm"
        ),
    )

    # ========================================================
    # Colorbar
    # ========================================================

    cbar = fig.colorbar(
        scatter,
        ax=ax,
        pad=0.02,
    )

    cbar.set_label(
        "MOT capture efficiency (%)"
    )

    # ========================================================
    # Labels
    # ========================================================

    ax.set_xlabel(
        r"Detuning $\Delta/\Gamma$"
    )

    ax.set_ylabel(
        "Magnet radius (mm)"
    )

    ax.set_title(
        rf"2D MOT optimization — fixed $s_0={s0}$"
    )

    ax.grid(
        alpha=0.18
    )

    ax.legend()

    # Explanation inside figure
    ax.text(
        0.02,
        0.02,
        (
            "Background color: locally estimated capture efficiency\n"
            "Background opacity: Optuna sampling density"
        ),
        transform=ax.transAxes,
        fontsize=9,
        verticalalignment="bottom",
        bbox=dict(
            boxstyle="round",
            facecolor="white",
            alpha=0.8,
        ),
    )

    plt.tight_layout()

    # ========================================================
    # Save
    # ========================================================

    if save_path is not None:
        fig.savefig(
            save_path,
            dpi=300,
            bbox_inches="tight",
        )

    return fig, ax


# ============================================================
# Example
# ============================================================

if __name__ == "__main__":
    s0_values = [1.1, 1.2, 1.3, 1.4, 1.5, 1.6]

    detuning_values = [
        np.array([
            -1.47564383, -0.97520848, -1.78157390, -1.91868294,
            -1.15843898, -1.97118171, -0.83458030, -1.74544505,
            -1.57406086, -1.39527697, -1.14385283, -0.90630934,
            -0.63422548, -1.13446104, -1.23341846, -1.18503975,
            -1.29398597, -1.04787872, -0.74148417, -1.31410519,
            -1.54251287, -1.13534201, -1.10667345, -1.04610462,
            -1.05566818, -0.83695229, -0.99504746, -1.30408045,
            -0.91110929, -1.38459490, -0.71528601, -1.21048807,
            -1.03314437, -1.41594271, -1.20821270, -1.22585142,
            -0.93451471, -1.52221513, -1.67253958, -1.25342453,
            -1.37182448,
        ]),

        np.array([
            -1.47564383, -0.97520848, -1.78157390, -1.91868294,
            -1.15843898, -1.97118171, -0.83458030, -1.74544505,
            -1.57406086, -1.39527697, -1.14385283, -0.90630934,
            -0.63422548, -1.13446104, -1.23341846, -1.18503975,
            -1.07321170, -1.33196999, -0.74148417, -1.02019437,
            -1.27655470, -1.07001122, -1.12129988, -0.90914410,
            -1.44000216, -0.77961566, -1.01572947, -1.03647868,
            -0.66693521, -1.60315064, -0.92197831, -1.09983195,
            -1.30777730, -0.97726317, -1.20821270, -1.22285610,
            -1.34578260, -1.52221513, -0.84846879, -0.98994201,
        ]),

        np.array([
            -1.47564383, -0.97520848, -1.78157390, -1.91868294,
            -1.15843898, -1.97118171, -0.83458030, -1.74544505,
            -1.57406086, -1.39527697, -1.14385283, -0.90630934,
            -0.63422548, -1.13446104, -1.23341846, -1.18503975,
            -1.07321170, -1.33196999, -0.74148417, -1.02019437,
            -1.27655470, -1.07001122, -1.12129988, -0.90914410,
            -1.08857788, -1.42347070, -0.82369079, -1.56287109,
            -1.29374090, -1.11328636, -1.53192948, -1.02472178,
            -0.96238553, -1.07990492, -1.21101514, -0.97446383,
            -1.37222225, -0.83550166, -1.05120238, -1.16644665,
            -1.25067231,
        ]),

        np.array([
            -1.47564383, -0.97520848, -1.78157390, -1.91868294,
            -1.15843898, -1.97118171, -0.83458030, -1.74544505,
            -1.57406086, -1.39527697, -1.14385283, -0.90630934,
            -0.63422548, -1.13446104, -1.23341846, -1.18503975,
            -1.07321170, -0.71367744, -1.02497717, -1.33784858,
            -0.78301953, -1.07001122, -1.27486431, -1.08429981,
            -0.90310248, -1.05369363, -1.45596057, -1.30408045,
            -1.09718071, -1.55811344, -0.97522381, -1.16128011,
            -0.94627831, -1.18860753, -1.36758994, -1.02004112,
            -0.84299128, -1.01168568, -1.23943015, -1.24851636,
        ]),

        np.array([
            -1.47564383, -0.97520848, -1.78157390, -1.91868294,
            -1.15843898, -1.97118171, -0.83458030, -1.74544505,
            -1.57406086, -1.39527697, -1.14385283, -0.90630934,
            -0.63422548, -1.13446104, -1.23341846, -1.18503975,
            -1.07321170, -0.71367744, -1.02497717, -1.33784858,
            -0.78301953, -1.07001122, -1.27486431, -1.08429981,
            -0.90310248, -1.05369363, -1.45596057, -1.30408045,
            -1.09718071, -1.55811344, -0.97522381, -1.30307832,
            -1.40304690, -1.20308830, -0.92653184, -1.11349623,
            -0.99162373, -1.11757335, -0.82464502,
        ]),

        np.array([
            -1.47564383, -0.97520848, -1.78157390, -1.91868294,
            -1.15843898, -1.97118171, -0.83458030, -1.74544505,
            -1.57406086, -1.39527697, -1.14385283, -0.90630934,
            -0.63422548, -1.13446104, -1.23341846, -1.18503975,
            -1.07321170, -0.71367744, -1.02497717, -1.33784858,
            -0.78301953, -1.07001122, -1.27486431, -1.08429981,
            -0.90310248, -1.05369363, -1.45596057, -1.30408045,
            -1.09718071, -1.55811344, -0.97522381, -1.30307832,
            -1.40205715, -1.20209822, -0.92653184, -1.11349623,
            -0.99162373, -1.11757335, -0.82464502, -1.22836724,
        ]),
    ]

    magnet_radius_values = [
        np.array([
            0.05355643, 0.05038793, 0.04640395, 0.05279559,
            0.05137265, 0.05372919, 0.04691105, 0.04665064,
            0.04972281, 0.04762106, 0.04505397, 0.05075818,
            0.05104297, 0.04925993, 0.04855572, 0.05198147,
            0.05178775, 0.05207467, 0.05221436, 0.05151815,
            0.05291450, 0.04946437, 0.04981236, 0.05004528,
            0.04853708, 0.05023921, 0.04851178, 0.05116954,
            0.05013615, 0.05291814, 0.04930861, 0.05080227,
            0.05076878, 0.04991052, 0.05057231, 0.05048981,
            0.05141352, 0.05245009, 0.05339907, 0.05085087,
            0.04807395,
        ]),

        np.array([
            0.05355643, 0.05038793, 0.04640395, 0.05279559,
            0.05137265, 0.05372919, 0.04691105, 0.04665064,
            0.04972281, 0.04762106, 0.04505397, 0.05075818,
            0.05104297, 0.04925993, 0.04855572, 0.05198147,
            0.04918801, 0.05179182, 0.04897335, 0.05171312,
            0.04804775, 0.04957681, 0.04996342, 0.05003925,
            0.05124040, 0.05252162, 0.04976967, 0.04998374,
            0.04829902, 0.04936526, 0.05043697, 0.05304487,
            0.05053731, 0.04981404, 0.05104592, 0.04887591,
            0.04739306, 0.05075522, 0.05219135, 0.05026529,
        ]),

        np.array([
            0.05355643, 0.05038793, 0.04640395, 0.05279559,
            0.05137265, 0.05372919, 0.04691105, 0.04665064,
            0.04972281, 0.04762106, 0.04505397, 0.05075818,
            0.05104297, 0.04925993, 0.04855572, 0.05198147,
            0.04918801, 0.05179182, 0.04897335, 0.05171312,
            0.04804775, 0.04957681, 0.04996342, 0.04977549,
            0.04989231, 0.05037051, 0.04817849, 0.05017721,
            0.04891947, 0.05280924, 0.04733579, 0.04966348,
            0.04959547, 0.05037766, 0.04851223, 0.05101900,
            0.04926468, 0.05245009, 0.05063398, 0.04988415,
            0.04860334,
        ]),

        np.array([
            0.05355643, 0.05038793, 0.04640395, 0.05279559,
            0.05137265, 0.05372919, 0.04691105, 0.04665064,
            0.04972281, 0.04762106, 0.04505397, 0.05075818,
            0.05104297, 0.04925993, 0.04855572, 0.05198147,
            0.04918801, 0.04941074, 0.04883101, 0.04801749,
            0.04975001, 0.05140365, 0.05244655, 0.04903557,
            0.04898896, 0.04783402, 0.05014893, 0.04915264,
            0.04815971, 0.04737440, 0.04599477, 0.05016502,
            0.05023914, 0.04851374, 0.04971540, 0.05049075,
            0.05057512, 0.05105012, 0.05177000, 0.05324199,
        ]),

        np.array([
            0.05355643, 0.05038793, 0.04640395, 0.05279559,
            0.05137265, 0.05372919, 0.04691105, 0.04665064,
            0.04972281, 0.04762106, 0.04505397, 0.05075818,
            0.05104297, 0.04925993, 0.04855572, 0.05198147,
            0.04918801, 0.04941074, 0.04883101, 0.04801749,
            0.04975001, 0.05140365, 0.05244655, 0.04903557,
            0.04898896, 0.04783402, 0.05014893, 0.04915264,
            0.04815971, 0.04737440, 0.04599477, 0.04916525,
            0.05023914, 0.04845103, 0.04971540, 0.05049075,
            0.05057512, 0.05014837, 0.05311912,
        ]),

        np.array([
            0.05355643, 0.05038793, 0.04640395, 0.05279559,
            0.05137265, 0.05372919, 0.04691105, 0.04665064,
            0.04972281, 0.04762106, 0.04505397, 0.05075818,
            0.05104297, 0.04925993, 0.04855572, 0.05198147,
            0.04918801, 0.04941074, 0.04883101, 0.04801749,
            0.04975001, 0.05140365, 0.05244655, 0.04903557,
            0.04898896, 0.04783402, 0.05014893, 0.04915264,
            0.04815971, 0.04737440, 0.04599477, 0.04916525,
            0.05023914, 0.04845103, 0.04971540, 0.05049075,
            0.05057512, 0.05014837, 0.05311912, 0.05159839,
        ]),
    ]

    success_count_values = [
        np.array([
            418, 581, 64, 9, 611, 1, 451, 82, 293, 375,
            389, 559, 468, 583, 507, 596, 581, 572, 496, 567,
            336, 594, 599, 606, 544, 525, 537, 573, 563, 517,
            491, 600, 593, 443, 605, 599, 559, 377, 140, 587,
            395,
        ]),

        np.array([
            472, 605, 92, 33, 622, 3, 476, 111, 345, 418,
            413, 579, 492, 622, 555, 605, 615, 608, 510, 587,
            505, 633, 642, 577, 521, 520, 629, 619, 476, 305,
            591, 572, 619, 606, 646, 575, 432, 430, 542, 614,
        ]),

        np.array([
            516, 618, 122, 58, 637, 13, 491, 145, 405, 451,
            431, 590, 510, 657, 576, 631, 634, 616, 515, 597,
            531, 652, 661, 595, 654, 578, 541, 426, 583, 581,
            352, 636, 610, 643, 582, 599, 569, 546, 634, 650,
            574,
        ]),

        np.array([
            549, 628, 156, 74, 641, 33, 513, 186, 454, 494,
            448, 591, 530, 663, 606, 626, 654, 548, 639, 546,
            564, 629, 638, 645, 602, 589, 586, 626, 611, 378,
            480, 693, 616, 617, 612, 647, 574, 624, 655, 607,
        ]),

        np.array([
            578, 637, 192, 111, 648, 53, 526, 236, 500, 528,
            464, 604, 548, 682, 641, 627, 679, 553, 648, 575,
            578, 635, 639, 673, 605, 608, 609, 657, 639, 406,
            507, 657, 651, 640, 621, 683, 645, 689, 572,
        ]),

        np.array([
            597, 646, 244, 160, 656, 82, 529, 286, 530, 559,
            475, 615, 556, 699, 653, 641, 695, 568, 656, 602,
            584, 645, 645, 692, 608, 630, 649, 675, 656, 436,
            510, 676, 673, 659, 619, 687, 654, 699, 585, 651,
        ]),
    ]

    for s0, detuning, magnet_radius, success_count in zip(
        s0_values,
        detuning_values,
        magnet_radius_values,
        success_count_values,
    ):
        fig, ax = plot_fixed_s0_optimization(
            s0=s0,
            detuning=detuning,
            magnet_radius=magnet_radius,
            success_count=success_count,
        )

        plt.show()

        save_path = f"graphs/fixed_s0_optimization_{s0:.1f}.png"

        fig.savefig(
            save_path,
            dpi=300,
            bbox_inches="tight",
        )