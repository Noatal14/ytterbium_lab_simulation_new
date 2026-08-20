import numpy as np
import matplotlib.pyplot as plt
from simulations.thermal_beam import (
    generate_thermal_beam_state,
    microtube_intensity_theta,
    sample_microtube_angles,
)
from config import Geometry, COLLIMATION_ANGLE_DEG

MAX_DEG = COLLIMATION_ANGLE_DEG


def test_small_thermal_beam_is_finite_and_reproducible():
    positions_1, velocities_1, info_1 = generate_thermal_beam_state(N=8, seed=123)
    positions_2, velocities_2, info_2 = generate_thermal_beam_state(N=8, seed=123)

    assert positions_1.shape == (8, 3)
    assert velocities_1.shape == (8, 3)
    assert np.all(np.isfinite(positions_1))
    assert np.all(np.isfinite(velocities_1))
    assert np.array_equal(positions_1, positions_2)
    assert np.array_equal(velocities_1, velocities_2)
    assert info_1 == info_2

def verify_microtube_distribution():
    print("Testing microtube distribution...")
    
    r_tube = Geometry.OVEN_MICROTUBE_RADIUS_M
    L_tube = Geometry.OVEN_MICROTUBE_LENGTH_M
    beta = 2 * r_tube / L_tube
    theta_c = np.arctan(beta)
    
    print(f"Microtube critical angle (theta_c): {np.degrees(theta_c):.2f} degrees")
    
    # 1. Plot the analytical function
    theta_grid = np.linspace(0, np.radians(MAX_DEG), 1000) # Plot up to 5 degrees
    intensity = microtube_intensity_theta(theta_grid, r_tube, L_tube)
    
    # Calculate theta_half (where intensity = 0.5 * max intensity)
    # np.interp expects increasing x. Reverse the arrays since intensity is decreasing.
    # We use np.nanmax(intensity) because if theta=0 throws a warning, it prevents a NaN error.
    theta_half = np.interp(0.5 * np.nanmax(intensity), intensity[::-1], theta_grid[::-1])
    theta_half_mrad = theta_half * 1000.0
    
    # 2. Sample from the distribution to check our sampling math
    N_samples = 10000000
    rng = np.random.default_rng(42)
    # We pass theta_max = 5 degrees just for the histogram comparison
    sampled_theta, _, _ = sample_microtube_angles(N_samples, r_tube, L_tube, rng, theta_max=np.radians(MAX_DEG))
    
    # 3. Create the figure
    fig, ax = plt.subplots(figsize=(8, 5))
    
    # Set font sizes for presentation
    plt.rcParams['font.size'] = 16
    ax.tick_params(axis='both', which='major', labelsize=16)
    ax.plot(np.degrees(theta_grid), intensity, 'r-', lw=2, label='Analytical I(theta)')
    ax.axvline(np.degrees(theta_half), color='k', linestyle=':', alpha=0.7, linewidth=2, label='Divergence Angle $\\theta_{1/2}$')
    ax.axhline(0.5 * np.nanmax(intensity), color='k', linestyle=':', alpha=0.7, linewidth=2)
    
    # Add simplified text annotation
    text_str = f"$\\theta_{{1/2}}$ = {theta_half_mrad:.1f} mrad"
    ax.text(np.degrees(theta_half) + 0.1, intensity[1] * 0.54, text_str, 
            color='k', fontsize=16, verticalalignment='center')
    
    # Plot histogram of sampled data.
    # The analytical I(theta) is intensity. The PDF of theta is I(theta) * sin(theta).
    # Since we sampled theta based on the PDF, if we want to compare the histogram of theta 
    # back to I(theta), we must divide the histogram counts by sin(theta) and normalize.
    
    counts, bins = np.histogram(sampled_theta, bins=1000, density=True)
    bin_centers = (bins[:-1] + bins[1:]) / 2

    
    # Convert PDF back to Intensity: I(theta) ~ PDF / sin(theta)
    empirical_intensity = counts / np.sin(bin_centers)
    # Normalize empirical intensity using the total area (sum) to be perfectly 
    # robust against random noise spikes at the top of the curve.
    scale_factor = np.nansum(intensity) / np.sum(empirical_intensity)
    empirical_intensity *= scale_factor
    
    ax.plot(np.degrees(bin_centers), empirical_intensity, 'b.', alpha=1.0, label='Sampled Data (converted to Intensity)')
    
    ax.set_xlabel('Theta (degrees)', fontsize=18)
    ax.set_ylabel('Normalized Intensity', fontsize=18)
    ax.set_title('Microtube Angular Intensity Distribution', fontsize=22)
    ax.legend(fontsize=20)
    ax.grid(True, alpha=0.5)
    
    plt.tight_layout()
    out_file = "microtube_test_plot.png"
    plt.savefig(out_file, dpi=350)
    print(f"✅ Saved verification plot to {out_file}")
    plt.show()

if __name__ == "__main__":
    verify_microtube_distribution()
