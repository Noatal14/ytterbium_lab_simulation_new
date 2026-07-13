"""
Validation graphs for dt convergence analysis.
"""

import json
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import linregress


def plot_final_transverse_velocity_spread_vs_dt(summary_json_path):
    """
    Create a graph of final transverse velocity spread vs dt.
    
    Plots sigma_v_perp = sqrt(std_x_velocity[-1]^2 + std_y_velocity[-1]^2)
    against dt, with a linear fit and extrapolated intercept C.
    
    Parameters
    ----------
    summary_json_path : str
        Path to the summary JSON file (e.g., "summary_v35r002.json")
    """
    # Load data
    p = Path(summary_json_path)
    data = json.loads(p.read_text())
    
    # Extract data
    dts = []
    sigma_vx_arr = []
    sigma_vy_arr = []
    sigma_v_perp_arr = []
    sigma_v_perp_err_arr = []
    
    for row in data.get("summary_rows", []):
        dt = row.get("dt")
        if dt is None:
            continue
        
        stoch = row.get("stochastic_results", {})
        std_x = stoch.get("std_x_velocity", [])
        std_y = stoch.get("std_y_velocity", [])
        
        if not std_x or not std_y:
            continue
        
        sigma_vx = float(std_x[-1])
        sigma_vy = float(std_y[-1])
        sigma_vx_arr.append(sigma_vx)
        sigma_vy_arr.append(sigma_vy)
        
        # Compute final transverse velocity spread
        sigma_v_perp = np.sqrt(sigma_vx**2 + sigma_vy**2)
        sigma_v_perp_arr.append(sigma_v_perp)
        
        # Error propagation
        err_sq = (sigma_vx / sigma_v_perp * 0.001)**2 + (sigma_vy / sigma_v_perp * 0.001)**2
        err = np.sqrt(err_sq)
        sigma_v_perp_err_arr.append(err)
        
        dts.append(dt)
    
    dts = np.array(dts)
    sigma_v_perp_arr = np.array(sigma_v_perp_arr)
    sigma_v_perp_err_arr = np.array(sigma_v_perp_err_arr)
    
    # Sort by dt
    sort_idx = np.argsort(dts)
    dts = dts[sort_idx]
    sigma_v_perp_arr = sigma_v_perp_arr[sort_idx]
    sigma_v_perp_err_arr = sigma_v_perp_err_arr[sort_idx]
    
    # Perform linear fit
    coeffs = np.polyfit(dts, sigma_v_perp_arr, 1)
    A = float(coeffs[0])
    C = float(coeffs[1])
    
    # Create plot
    plt.figure(figsize=(6, 4))
    plt.errorbar(dts, sigma_v_perp_arr, yerr=sigma_v_perp_err_arr, fmt="o", capsize=4, label="data")
    
    # Plot fit line
    dt_fit = np.linspace(dts.min(), dts.max(), 200)
    sigma_fit = C + A * dt_fit
    plt.plot(dt_fit, sigma_fit, color="C1", linestyle="-", linewidth=1.75, label=f"linear fit")
    
    # Add intercept line and annotation
    plt.axhline(C, color="C1", linestyle=":", linewidth=1, alpha=0.7)
    plt.text(dts.min(), C + 0.005, f"C = {C:.6f}", color="black", fontweight="bold", 
             verticalalignment="bottom", horizontalalignment="left", fontsize=8)
    
    # Add chosen timestep marker
    dt_chosen = 7e-6
    plt.axvline(dt_chosen, color="gray", linestyle="--", linewidth=1.25)
    plt.text(dt_chosen, np.max(sigma_v_perp_arr), "Chosen timestep", rotation=90, 
             verticalalignment="bottom", horizontalalignment="left", color="gray")
    
    plt.xlabel("dt (s)")
    plt.ylabel(r"Final transverse velocity spread $\sigma_{v_\perp}$ (m/s)")
    plt.title("Final transverse velocity spread vs dt")
    plt.grid(True, which="both", alpha=0.3)
    plt.legend(loc="best")
    plt.tight_layout()
    
    # Save figure
    out_path = Path(summary_json_path).parent / f"{Path(summary_json_path).stem}_spread_vs_dt.png"
    plt.savefig(out_path, dpi=150)
    print(f"Saved plot to {out_path}")
    
    # Print fit results
    print(f"\nFinal transverse velocity spread convergence:")
    print(f"  C (extrapolated dt=0) = {C:.6f}")
    print(f"  A (slope) = {A:.6e}")
    print(f"  sigma_v_perp(7e-6) = {C + A * 7e-6:.6f}")
    
    return out_path


if __name__ == "__main__":
    # Example usage
    plot_final_transverse_velocity_spread_vs_dt("dt_comparison/data/zeeman_v_250_r000_2.json")
