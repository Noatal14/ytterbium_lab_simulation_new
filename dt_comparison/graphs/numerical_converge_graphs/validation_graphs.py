import json
import sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from scipy import constants as csts
from scipy.optimize import curve_fit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import YB171_MASS_KG, K_B


def compute_mean_distance_and_error(summary_json_path: str):
    p = Path(summary_json_path)
    data = json.loads(p.read_text())

    dts = []
    mean_ds = []
    mean_errs = []

    for row in data.get("summary_rows", []):
        dt = row.get("dt")
        if dt is None:
            continue

        stoch = row.get("stochastic_results") or {}
        det = row.get("deterministic_results") or {}

        # Need mean positions and stds from stochastic, and deterministic positions
        mx = stoch.get("mean_x_position")
        my = stoch.get("mean_y_position")
        mz = stoch.get("mean_z_position")
        sx = stoch.get("std_x_position")
        sy = stoch.get("std_y_position")
        sz = stoch.get("std_z_position")

        dx = det.get("position_x")
        dy = det.get("position_y")
        dz = det.get("position_z")

        if not (mx and my and mz and dx and dy and dz and sx and sy and sz):
            # skip rows without full info
            continue

        # align lengths
        n = min(len(mx), len(my), len(mz), len(dx), len(dy), len(dz))
        mx = np.asarray(mx[:n], dtype=float)
        my = np.asarray(my[:n], dtype=float)
        mz = np.asarray(mz[:n], dtype=float)
        dx = np.asarray(dx[:n], dtype=float)
        dy = np.asarray(dy[:n], dtype=float)
        dz = np.asarray(dz[:n], dtype=float)
        sx = np.asarray(sx[:n], dtype=float)
        sy = np.asarray(sy[:n], dtype=float)
        sz = np.asarray(sz[:n], dtype=float)

        # differences (stoch - det)
        diff = np.vstack((mx - dx, my - dy, mz - dz)).T
        d_i = np.linalg.norm(diff, axis=1)  # distances per timepoint

        # propagate stds to distance uncertainty per timepoint
        # sigma_d^2 = sum( ( (diff_comp / d) ** 2 ) * sigma_comp^2 )
        # handle d==0 safely
        eps = 1e-20
        d_safe = np.where(d_i <= eps, eps, d_i)
        frac_x = (diff[:, 0] / d_safe) ** 2
        frac_y = (diff[:, 1] / d_safe) ** 2
        frac_z = (diff[:, 2] / d_safe) ** 2
        sigma_d_i = np.sqrt(frac_x * sx ** 2 + frac_y * sy ** 2 + frac_z * sz ** 2)

        # if d was effectively zero, fall back to combined std magnitude
        zero_mask = d_i <= eps
        if np.any(zero_mask):
            sigma_d_i[zero_mask] = np.sqrt(sx[zero_mask] ** 2 + sy[zero_mask] ** 2 + sz[zero_mask] ** 2)

        # mean distance and propagated error on the mean
        mean_d = float(np.mean(d_i))
        # assuming independent timepoint uncertainties, error on mean = sqrt(sum var)/N
        sigma_mean = float(np.sqrt(np.sum(sigma_d_i ** 2)) / max(1, len(sigma_d_i)))

        dts.append(float(dt))
        mean_ds.append(mean_d)
        mean_errs.append(sigma_mean)

    # sort by dt
    if not dts:
        raise RuntimeError(f"No valid rows found in {summary_json_path}")

    order = np.argsort(dts)
    return np.array(dts)[order], np.array(mean_ds)[order], np.array(mean_errs)[order]


def plot_mean_distance_vs_dt(summary_json_path: str, out_path: str = "graphs/mean_distance_vs_dt.png"):
    dts, mean_ds, mean_errs = compute_mean_distance_and_error(summary_json_path)

    plt.figure(figsize=(6, 4))
    plt.errorbar(dts, mean_ds, yerr=mean_errs, fmt="o-", capsize=4)
    plt.xscale("log")
    plt.xlabel("dt (s)")
    plt.ylabel("Mean distance |stoch - det| (m)")
    plt.title("Mean distance from deterministic trajectory vs dt")
    plt.grid(True, which="both", alpha=0.3)
    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(out_p)
    print(f"Saved plot to {out_p}")


if __name__ == "__main__":
    default_json = Path("dt_comparison/data/summary_v35r002.json")
    if not default_json.exists():
        raise SystemExit(f"Summary JSON not found at {default_json}. Please provide path.")
    # produce all validation plots
    plot_mean_distance_vs_dt(str(default_json), out_path="graphs/mean_distance_vs_dt.png")
    # Final position vs dt
    def compute_mean_final_position_and_error(summary_json_path: str):
        p = Path(summary_json_path)
        data = json.loads(p.read_text())

        dts = []
        final_rs = []
        final_errs = []

        for row in data.get("summary_rows", []):
            dt = row.get("dt")
            if dt is None:
                continue
            stoch = row.get("stochastic_results") or {}
            mx = stoch.get("mean_x_position")
            my = stoch.get("mean_y_position")
            mz = stoch.get("mean_z_position")
            sx = stoch.get("std_x_position")
            sy = stoch.get("std_y_position")
            sz = stoch.get("std_z_position")

            if not (mx and my and mz and sx and sy and sz):
                continue

            x = float(mx[-1])
            y = float(my[-1])
            z = float(mz[-1])
            sxv = float(sx[-1])
            syv = float(sy[-1])
            szv = float(sz[-1])

            r = np.sqrt(x * x + y * y + z * z)
            # propagate
            eps = 1e-20
            r_safe = r if r > eps else eps
            var_r = (x / r_safe) ** 2 * sxv ** 2 + (y / r_safe) ** 2 * syv ** 2 + (z / r_safe) ** 2 * szv ** 2
            if r <= eps:
                var_r = sxv ** 2 + syv ** 2 + szv ** 2

            dts.append(float(dt))
            final_rs.append(float(r))
            final_errs.append(float(np.sqrt(var_r)))

        if not dts:
            raise RuntimeError(f"No valid rows found in {summary_json_path}")
        order = np.argsort(dts)
        return np.array(dts)[order], np.array(final_rs)[order], np.array(final_errs)[order]

    def plot_mean_final_position_vs_dt(summary_json_path: str, out_path: str = "graphs/mean_final_position_vs_dt.png"):
        dts, rs, errs = compute_mean_final_position_and_error(summary_json_path)
        plt.figure(figsize=(6, 4))
        plt.errorbar(dts, rs, yerr=errs, fmt="o-", capsize=4)
        plt.xscale("log")
        plt.xlabel("dt (s)")
        plt.ylabel("Mean final position magnitude |r_final| (m)")
        plt.title("Mean final position magnitude vs dt")
        plt.grid(True, which="both", alpha=0.3)
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        plt.tight_layout()
        plt.savefig(out_p)
        print(f"Saved plot to {out_p}")

    plot_mean_final_position_vs_dt(str(default_json), out_path="graphs/mean_final_position_vs_dt.png")

    # Final velocity vs dt
    def compute_mean_final_velocity_and_error(summary_json_path: str):
        p = Path(summary_json_path)
        data = json.loads(p.read_text())

        dts = []
        final_vs = []
        final_errs = []

        for row in data.get("summary_rows", []):
            dt = row.get("dt")
            if dt is None:
                continue
            stoch = row.get("stochastic_results") or {}
            mvx = stoch.get("mean_x_velocity")
            mvy = stoch.get("mean_y_velocity")
            mvz = stoch.get("mean_z_velocity")
            svx = stoch.get("std_x_velocity")
            svy = stoch.get("std_y_velocity")
            svz = stoch.get("std_z_velocity")

            if not (mvx and mvy and mvz and svx and svy and svz):
                continue

            vx = float(mvx[-1])
            vy = float(mvy[-1])
            vz = float(mvz[-1])
            svxv = float(svx[-1])
            svyv = float(svy[-1])
            svzv = float(svz[-1])

            v = np.sqrt(vx * vx + vy * vy + vz * vz)
            eps = 1e-20
            v_safe = v if v > eps else eps
            # Propagate ensemble standard deviations of velocity components to |v_final|.
            var_v = (vx / v_safe) ** 2 * svxv ** 2 + (vy / v_safe) ** 2 * svyv ** 2 + (vz / v_safe) ** 2 * svzv ** 2
            if v <= eps:
                var_v = svxv ** 2 + svyv ** 2 + svzv ** 2

            dts.append(float(dt))
            final_vs.append(float(v))
            final_errs.append(float(np.sqrt(var_v)))

        if not dts:
            raise RuntimeError(f"No valid rows found in {summary_json_path}")
        order = np.argsort(dts)
        return np.array(dts)[order], np.array(final_vs)[order], np.array(final_errs)[order]

    def plot_mean_final_velocity_vs_dt(summary_json_path: str, out_path: str = "graphs/mean_final_velocity_vs_dt.png"):
        dts, vs, errs = compute_mean_final_velocity_and_error(summary_json_path)
        plt.figure(figsize=(6, 4))
        plt.errorbar(dts, vs, yerr=errs, fmt="o-", capsize=4)
        plt.axvline(7e-6, color="gray", linestyle="--", linewidth=1)
        plt.text(7e-6, np.max(vs) if len(vs) else 0.0, "Chosen timestep", rotation=90, verticalalignment="bottom", horizontalalignment="left", color="gray")
        plt.xscale("log")
        plt.xlabel("dt (s)")
        plt.ylabel("Mean final velocity magnitude |v_final| (m/s)")
        plt.title("Mean final velocity magnitude vs dt")
        plt.grid(True, which="both", alpha=0.3)
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        plt.tight_layout()
        plt.savefig(out_p)
        print(f"Saved plot to {out_p}")

    plot_mean_final_velocity_vs_dt(str(default_json), out_path="graphs/mean_final_velocity_vs_dt.png")

    def compute_mean_final_transverse_velocity_and_error(summary_json_path: str):
        p = Path(summary_json_path)
        data = json.loads(p.read_text())

        dts = []
        final_vts = []
        final_errs = []

        for row in data.get("summary_rows", []):
            dt = row.get("dt")
            if dt is None:
                continue
            stoch = row.get("stochastic_results") or {}
            mvx = stoch.get("mean_x_velocity")
            mvy = stoch.get("mean_y_velocity")
            svx = stoch.get("std_x_velocity")
            svy = stoch.get("std_y_velocity")

            if not (mvx and mvy and svx and svy):
                continue

            vx = float(mvx[-1])
            vy = float(mvy[-1])
            svxv = float(svx[-1])
            svyv = float(svy[-1])

            vt = np.sqrt(vx * vx + vy * vy)
            eps = 1e-20
            vt_safe = vt if vt > eps else eps
            var_vt = (vx / vt_safe) ** 2 * svxv ** 2 + (vy / vt_safe) ** 2 * svyv ** 2
            if vt <= eps:
                var_vt = svxv ** 2 + svyv ** 2

            dts.append(float(dt))
            final_vts.append(float(vt))
            final_errs.append(float(np.sqrt(var_vt)))

        if not dts:
            raise RuntimeError(f"No valid rows found in {summary_json_path}")
        order = np.argsort(dts)
        return np.array(dts)[order], np.array(final_vts)[order], np.array(final_errs)[order]

    def plot_mean_final_transverse_velocity_vs_dt(summary_json_path: str, out_path: str = "graphs/mean_final_transverse_velocity_vs_dt.png"):
        dts, vts, errs = compute_mean_final_transverse_velocity_and_error(summary_json_path)
        plt.figure(figsize=(6, 4))
        plt.errorbar(dts, vts, yerr=errs, fmt="o-", capsize=4)
        plt.axvline(7e-6, color="gray", linestyle="--", linewidth=1)
        plt.text(7e-6, np.max(vts) if len(vts) else 0.0, "Chosen timestep", rotation=90, verticalalignment="bottom", horizontalalignment="left", color="gray")
        plt.xscale("log")
        plt.xlabel("dt (s)")
        plt.ylabel("Mean final transverse velocity magnitude v_transverse (m/s)")
        plt.title("Mean final transverse velocity magnitude vs dt")
        plt.grid(True, which="both", alpha=0.3)
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        plt.tight_layout()
        plt.savefig(out_p)
        print(f"Saved plot to {out_p}")

    plot_mean_final_transverse_velocity_vs_dt(str(default_json), out_path="graphs/mean_final_transverse_velocity_vs_dt.png")

    def compute_final_transverse_velocity_spread(summary_json_path: str, n_seeds: int = 5000):
        p = Path(summary_json_path)
        data = json.loads(p.read_text())

        dts = []
        sigma_vx = []
        sigma_vy = []
        sigma_v_perp = []
        sigma_v_perp_err = []

        for row in data.get("summary_rows", []):
            dt = row.get("dt")
            if dt is None:
                continue
            stoch = row.get("stochastic_results") or {}
            svx = stoch.get("std_x_velocity")
            svy = stoch.get("std_y_velocity")
            if not (svx and svy):
                continue

            sigma_x = float(svx[-1])
            sigma_y = float(svy[-1])

            sigma_perp = np.sqrt(sigma_x ** 2 + sigma_y ** 2)
            sem_x = sigma_x / np.sqrt(2 * (n_seeds - 1))
            sem_y = sigma_y / np.sqrt(2 * (n_seeds - 1))
            if sigma_perp > 0:
                sigma_perp_err = np.sqrt((sigma_x / sigma_perp * sem_x) ** 2 + (sigma_y / sigma_perp * sem_y) ** 2)
            else:
                sigma_perp_err = np.sqrt(sem_x ** 2 + sem_y ** 2)

            dts.append(float(dt))
            sigma_vx.append(sigma_x)
            sigma_vy.append(sigma_y)
            sigma_v_perp.append(sigma_perp)
            sigma_v_perp_err.append(sigma_perp_err)

        if not dts:
            raise RuntimeError(f"No valid rows found in {summary_json_path}")

        order = np.argsort(dts)
        return (
            np.array(dts)[order],
            np.array(sigma_vx)[order],
            np.array(sigma_vy)[order],
            np.array(sigma_v_perp)[order],
            np.array(sigma_v_perp_err)[order],
        )

    def plot_final_transverse_velocity_spread_vs_dt(summary_json_path: str, out_path: str = "graphs/final_transverse_velocity_spread_vs_dt.png"):
        dts, sigma_vx_arr, sigma_vy_arr, sigma_v_perp_arr, sigma_v_perp_err_arr = compute_final_transverse_velocity_spread(summary_json_path)

        # Keep only 2e-6, 7e-6, 1e-5, and all dt > 1e-5.
        keep_mask = (
            np.isclose(dts, 2e-6)
            | np.isclose(dts, 7e-6)
            | np.isclose(dts, 1e-5)
            | (dts > 1e-5)
        )
        dts = dts[keep_mask]
        sigma_vx_arr = sigma_vx_arr[keep_mask]
        sigma_vy_arr = sigma_vy_arr[keep_mask]
        sigma_v_perp_arr = sigma_v_perp_arr[keep_mask]
        sigma_v_perp_err_arr = sigma_v_perp_err_arr[keep_mask]

        fit_ranges = [
            (dts, ""),
        ]

        dt_chosen = 7e-6
        idxs = np.where(np.isclose(dts, dt_chosen))[0]
        if len(idxs) > 0:
            sigma_v_perp_chosen = float(sigma_v_perp_arr[int(idxs[0])])
        else:
            sigma_v_perp_chosen = float(np.interp(dt_chosen, dts, sigma_v_perp_arr))

        fit_results = []
        dt_fit = np.linspace(dts.min(), dts.max(), 200)

        for dt_subset, label in fit_ranges:
            if len(dt_subset) < 2:
                continue
            mask = np.isin(dts, dt_subset)
            sigma_subset = sigma_v_perp_arr[mask]
            coeffs = np.polyfit(dt_subset, sigma_subset, 1)
            A = float(coeffs[0])
            C = float(coeffs[1])
            sigma_at_chosen = C + A * dt_chosen
            abs_diff = abs(sigma_v_perp_chosen - C)
            rel_diff = 100.0 * abs_diff / abs(C) if C != 0 else np.nan
            fit_results.append((label, C, A, sigma_at_chosen, abs_diff, rel_diff))

        plt.figure(figsize=(6, 4))
        plt.errorbar(dts, sigma_v_perp_arr, yerr=sigma_v_perp_err_arr, fmt="o", capsize=4, label="data")

        for dt_subset, label in fit_ranges:
            if len(dt_subset) < 2:
                continue
            mask = np.isin(dts, dt_subset)
            sigma_subset = sigma_v_perp_arr[mask]
            coeffs = np.polyfit(dt_subset, sigma_subset, 1)
            A = float(coeffs[0])
            C = float(coeffs[1])
            sigma_fit = C + A * dt_fit
            plt.plot(dt_fit, sigma_fit, color="C1", linestyle="-", linewidth=1.75, label=f"linear fit {label}")
            plt.axhline(C, color="C1", linestyle=":", linewidth=1, alpha=0.7)
            plt.text(dts.min(), C + 0.005, f"C = {C:.6f}", color="black", fontweight="bold", verticalalignment="bottom", horizontalalignment="left", fontsize=8)

        plt.axvline(dt_chosen, color="gray", linestyle="--", linewidth=1.25)
        plt.text(dt_chosen, np.max(sigma_v_perp_arr), "Chosen timestep", rotation=90, verticalalignment="bottom", horizontalalignment="left", color="gray")
        plt.xlabel("dt (s)")
        plt.ylabel(r"Final transverse velocity spread $\sigma_{v_\perp}$ (m/s)")
        plt.title("Final transverse velocity spread vs dt")
        plt.grid(True, which="both", alpha=0.3)
        plt.legend(loc="best")
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        plt.tight_layout()
        plt.savefig(out_p)
        print(f"Saved plot to {out_p}")

        print("\ndt, std_x_velocity[-1], std_y_velocity[-1], sigma_v_perp, uncertainty(sigma_v_perp)")
        for dt, sx, sy, svp, svp_err in zip(dts, sigma_vx_arr, sigma_vy_arr, sigma_v_perp_arr, sigma_v_perp_err_arr):
            print(f"{dt:.6e}, {sx:.6e}, {sy:.6e}, {svp:.6e}, {svp_err:.6e}")

        print("\nLinear fit summary for sigma_v_perp(dt) = C + A * dt")
        for label, C, A, sigma_at_chosen, abs_diff, rel_diff in fit_results:
            print(f"Fit range: {label}")
            print(f"  C = {C:.6f}")
            print(f"  A = {A:.6e}")
            print(f"  sigma_v_perp(7e-6) = {sigma_v_perp_chosen:.6f}")
            print(f"  |sigma_v_perp(7e-6) - C| = {abs_diff:.6f}")
            print(f"  relative difference = {rel_diff:.4f}%")

        return C, A

    def plot_final_transverse_velocity_spread_zoomed(summary_json_path: str, out_path: str = "graphs/final_transverse_velocity_spread_zoomed.png"):
        dts, sigma_vx_arr, sigma_vy_arr, sigma_v_perp_arr, sigma_v_perp_err_arr = compute_final_transverse_velocity_spread(summary_json_path)
        dt_limit = 1e-5
        dt_chosen = 7e-6
        mask = dts <= dt_limit
        dts_zoom = dts[mask]
        sigma_zoom = sigma_v_perp_arr[mask]
        sigma_err_zoom = sigma_v_perp_err_arr[mask]

        if len(dts_zoom) < 2:
            raise RuntimeError("Not enough dt<=1e-5 points for zoomed plot")

        plt.figure(figsize=(6, 4))
        plt.errorbar(dts_zoom, sigma_zoom, yerr=sigma_err_zoom, fmt="o", capsize=4)
        plt.axvline(dt_chosen, color="gray", linestyle="--", linewidth=1.25)
        plt.text(dt_chosen, np.max(sigma_zoom), "Chosen timestep", rotation=90, verticalalignment="bottom", horizontalalignment="left", color="gray")
        plt.xlabel("dt (s)")
        plt.ylabel(r"Final transverse velocity spread $\sigma_{v_\perp}$ (m/s)")
        plt.title("Zoomed final transverse velocity spread vs dt")
        plt.grid(True, which="both", alpha=0.3)
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        plt.tight_layout()
        plt.savefig(out_p)
        print(f"Saved plot to {out_p}")
        return None

    def plot_final_transverse_velocity_spread_relative_deviation(summary_json_path: str, out_path: str = "graphs/final_transverse_velocity_spread_relative_deviation.png"):
        dts, sigma_vx_arr, sigma_vy_arr, sigma_v_perp_arr, sigma_v_perp_err_arr = compute_final_transverse_velocity_spread(summary_json_path)
        dt_limit = 1e-5
        dt_chosen = 7e-6
        mask = dts <= dt_limit
        dts_zoom = dts[mask]
        sigma_zoom = sigma_v_perp_arr[mask]
        sigma_err_zoom = sigma_v_perp_err_arr[mask]

        if len(dts_zoom) < 2:
            raise RuntimeError("Not enough dt<=1e-5 points for relative deviation plot")

        coeffs = np.polyfit(dts_zoom, sigma_zoom, 1)
        C_local = float(coeffs[1])
        rel_dev = 100.0 * (sigma_zoom - C_local) / C_local

        plt.figure(figsize=(6, 4))
        plt.plot(dts_zoom, rel_dev, "o-", color="C0", label="relative deviation")
        plt.axvline(dt_chosen, color="gray", linestyle="--", linewidth=1.25)
        plt.text(dt_chosen, np.max(rel_dev), "Chosen timestep", rotation=90, verticalalignment="bottom", horizontalalignment="left", color="gray")
        plt.axhline(0.0, color="black", linestyle="--", linewidth=1)
        plt.axhline(2.0, color="gray", linestyle=":", linewidth=1, alpha=0.7)
        plt.axhline(-2.0, color="gray", linestyle=":", linewidth=1, alpha=0.7)
        plt.xlabel("dt (s)")
        plt.ylabel("Deviation from dt -> 0 extrapolation (%)")
        plt.title("Relative deviation of sigma_v_perp from dt -> 0 extrapolation")
        plt.grid(True, which="both", alpha=0.3)
        plt.legend(loc="best")
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        plt.tight_layout()
        plt.savefig(out_p)
        print(f"Saved plot to {out_p}")

        print("\nZoomed dt<=1e-5 table:")
        print("dt (s), sigma_v_perp (m/s), uncertainty (m/s), relative deviation (%)")
        for dt, sigma_val, sigma_err, dev in zip(dts_zoom, sigma_zoom, sigma_err_zoom, rel_dev):
            print(f"{dt:.6e}, {sigma_val:.6f}, {sigma_err:.6f}, {dev:.4f}")

    plot_final_transverse_velocity_spread_vs_dt(str(default_json), out_path="graphs/final_transverse_velocity_spread_vs_dt.png")
    plot_final_transverse_velocity_spread_zoomed(str(default_json), out_path="graphs/final_transverse_velocity_spread_zoomed.png")
    plot_final_transverse_velocity_spread_relative_deviation(str(default_json), out_path="graphs/final_transverse_velocity_spread_relative_deviation.png")

    def compute_exit_transverse_temperature(summary_json_path: str, n_seeds: int = 5000):
        p = Path(summary_json_path)
        data = json.loads(p.read_text())

        dts = []
        sigma_vx = []
        sigma_vy = []
        temps_mK = []
        temp_errs_mK = []

        for row in data.get("summary_rows", []):
            dt = row.get("dt")
            if dt is None:
                continue

            stoch = row.get("stochastic_results") or {}
            svx = stoch.get("std_x_velocity")
            svy = stoch.get("std_y_velocity")
            if not (svx and svy):
                continue

            sigma_x = float(svx[-1])
            sigma_y = float(svy[-1])

            # Temperature from transverse velocity variance
            T_perp = (YB171_MASS_KG / (2 * K_B)) * (sigma_x ** 2 + sigma_y ** 2)
            T_perp_mK = T_perp * 1e3

            sem_sigma_x = sigma_x / np.sqrt(2 * (n_seeds - 1))
            sem_sigma_y = sigma_y / np.sqrt(2 * (n_seeds - 1))
            sigma_T = (YB171_MASS_KG / K_B) * np.sqrt((sigma_x * sem_sigma_x) ** 2 + (sigma_y * sem_sigma_y) ** 2)
            sigma_T_mK = sigma_T * 1e3

            dts.append(float(dt))
            sigma_vx.append(sigma_x)
            sigma_vy.append(sigma_y)
            temps_mK.append(T_perp_mK)
            temp_errs_mK.append(sigma_T_mK)

        if not dts:
            raise RuntimeError(f"No valid rows found in {summary_json_path}")

        order = np.argsort(dts)
        return (
            np.array(dts)[order],
            np.array(sigma_vx)[order],
            np.array(sigma_vy)[order],
            np.array(temps_mK)[order],
            np.array(temp_errs_mK)[order],
        )

    def fit_power_law_offset(dt_values, temps, temp_errs):
        def model(dt, C, A, p):
            return C + A * dt ** p

        # initial guess: C from smallest temp, A from range scale, p ~ 1
        guess = [temps.min(), max(1e-4, temps.max() - temps.min()), 1.0]
        bounds = ([0.0, 0.0, 0.0], [np.inf, np.inf, 5.0])
        popt, pcov = curve_fit(
            model,
            dt_values,
            temps,
            sigma=temp_errs,
            absolute_sigma=True,
            p0=guess,
            bounds=bounds,
            maxfev=20000,
        )
        perr = np.sqrt(np.diag(pcov))
        return popt, perr, model

    def plot_exit_transverse_temperature(summary_json_path: str, out_path: str = "graphs/exit_transverse_temperature_vs_dt.png"):
        dts, sigma_vx_arr, sigma_vy_arr, temps_mK, temp_errs_mK = compute_exit_transverse_temperature(summary_json_path)
        popt, perr, model = fit_power_law_offset(dts, temps_mK, temp_errs_mK)

        C, A, p = popt
        dC, dA, dp = perr

        dt_fit = np.linspace(dts.min(), dts.max(), 200)
        temp_fit = model(dt_fit, *popt)

        plt.figure(figsize=(6, 4))
        plt.errorbar(dts, temps_mK, yerr=temp_errs_mK, fmt="o", capsize=4, label="data")
        plt.plot(dt_fit, temp_fit, "-", color="C1", label=f"fit: C={C:.3f}±{dC:.3f} mK, A={A:.3g}, p={p:.3f}")
        plt.axvline(7e-6, color="gray", linestyle="--", linewidth=1)
        plt.text(7e-6, temps_mK.max() if len(temps_mK) else 0.0, "Chosen timestep", rotation=90, verticalalignment="bottom", horizontalalignment="left", color="gray")
        plt.axhline(C, color="gray", linestyle=":", linewidth=1)
        plt.text(dts.min(), C, "dt -> 0 extrapolation", verticalalignment="bottom", color="gray")
        plt.xlabel("dt (s)")
        plt.ylabel("Exit transverse temperature T_perp (mK)")
        plt.title("Exit transverse temperature vs dt")
        plt.grid(True, which="both", alpha=0.3)
        plt.legend(loc="best")
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        plt.tight_layout()
        plt.savefig(out_p)
        print(f"Saved plot to {out_p}")

        print("\nExit transverse temperature summary:")
        print("dt (s), sigma_vx_final (m/s), sigma_vy_final (m/s), T_perp_mK, T_perp_error_mK")
        for dt, sigma_x, sigma_y, T_mK, err_mK in zip(dts, sigma_vx_arr, sigma_vy_arr, temps_mK, temp_errs_mK):
            print(f"{dt:.6e}, {sigma_x:.6e}, {sigma_y:.6e}, {T_mK:.6f}, {err_mK:.6f}")

        print("\nFit results:")
        print(f"C = {C:.6f} ± {dC:.6f} mK")
        print(f"A = {A:.6g}")
        print(f"p = {p:.6f}")

        # check dt = 7e-6 if available
        if 7e-6 in dts:
            idx = int(np.where(dts == 7e-6)[0][0])
            T_7e6 = temps_mK[idx]
            err_7e6 = temp_errs_mK[idx]
            delta = T_7e6 - C
            combined_unc = np.sqrt(err_7e6 ** 2 + dC ** 2)
            print(f"T_perp(7e-6) = {T_7e6:.6f} mK ± {err_7e6:.6f} mK")
            print(f"T_perp(7e-6) - C = {delta:.6f} mK")
            print(f"Difference in combined uncertainty = {delta / combined_unc:.3f} sigma")
        else:
            print("dt = 7e-6 not present in the data; unable to compute exact comparison.")

    plot_exit_transverse_temperature(str(default_json), out_path="graphs/exit_transverse_temperature_vs_dt.png")

    # Repeat analysis for v15r002 summary if present
    alt_json = Path("dt_comparison/data/summary_v15r002.json")
    if alt_json.exists():
        plot_mean_final_position_vs_dt(str(alt_json), out_path="graphs/mean_final_position_vs_dt_v15r002.png")
        plot_mean_final_velocity_vs_dt(str(alt_json), out_path="graphs/mean_final_velocity_vs_dt_v15r002.png")
        print(f"Also saved v15r002 plots to graphs/mean_final_*_v15r002.png")
    # v50r002 summary (if present)
    alt_json2 = Path("dt_comparison/data/summary_v50r002.json")
    if alt_json2.exists():
        plot_mean_final_position_vs_dt(str(alt_json2), out_path="graphs/mean_final_position_vs_dt_v50r002.png")
        plot_mean_final_velocity_vs_dt(str(alt_json2), out_path="graphs/mean_final_velocity_vs_dt_v50r002.png")
        print(f"Also saved v50r002 plots to graphs/mean_final_*_v50r002.png")

    # Sigma (mean std) plots: position & velocity
    def compute_mean_sigma_summary(summary_json_path: str):
        p = Path(summary_json_path)
        data = json.loads(p.read_text())

        dts = []
        sigma_r_means = []
        sigma_v_means = []

        for row in data.get("summary_rows", []):
            dt = row.get("dt")
            if dt is None:
                continue
            stoch = row.get("stochastic_results") or {}
            sx = stoch.get("std_x_position")
            sy = stoch.get("std_y_position")
            sz = stoch.get("std_z_position")
            svx = stoch.get("std_x_velocity")
            svy = stoch.get("std_y_velocity")
            svz = stoch.get("std_z_velocity")

            if not (sx and sy and sz and svx and svy and svz):
                continue

            # align lengths
            n_pos = min(len(sx), len(sy), len(sz))
            n_vel = min(len(svx), len(svy), len(svz))

            sx_arr = np.asarray(sx[:n_pos], dtype=float)
            sy_arr = np.asarray(sy[:n_pos], dtype=float)
            sz_arr = np.asarray(sz[:n_pos], dtype=float)

            svx_arr = np.asarray(svx[:n_vel], dtype=float)
            svy_arr = np.asarray(svy[:n_vel], dtype=float)
            svz_arr = np.asarray(svz[:n_vel], dtype=float)

            sigma_r_t = np.sqrt(sx_arr ** 2 + sy_arr ** 2 + sz_arr ** 2)
            sigma_v_t = np.sqrt(svx_arr ** 2 + svy_arr ** 2 + svz_arr ** 2)

            sigma_r_mean = float(np.mean(sigma_r_t))
            sigma_v_mean = float(np.mean(sigma_v_t))

            dts.append(float(dt))
            sigma_r_means.append(sigma_r_mean)
            sigma_v_means.append(sigma_v_mean)

        if not dts:
            raise RuntimeError(f"No valid rows found in {summary_json_path}")
        order = np.argsort(dts)
        return np.array(dts)[order], np.array(sigma_r_means)[order], np.array(sigma_v_means)[order]

    def plot_sigma_vs_dt(summary_json_path: str, out_path_r: str = "graphs/sigma_position_vs_dt.png", out_path_v: str = "graphs/sigma_velocity_vs_dt.png"):
        dts, sigma_rs, sigma_vs = compute_mean_sigma_summary(summary_json_path)

        plt.figure(figsize=(6, 4))
        plt.plot([], [])  # ensure fresh figure
        plt.errorbar(dts, sigma_rs, yerr=None, fmt="o-", capsize=4)
        plt.xscale("log")
        plt.xlabel("dt (s)")
        plt.ylabel("Mean position std (m)")
        plt.title("Mean position std (sigma_r_mean) vs dt")
        plt.grid(True, which="both", alpha=0.3)
        out_pr = Path(out_path_r)
        out_pr.parent.mkdir(parents=True, exist_ok=True)
        plt.tight_layout()
        plt.savefig(out_pr)
        print(f"Saved plot to {out_pr}")

        plt.figure(figsize=(6, 4))
        plt.errorbar(dts, sigma_vs, yerr=None, fmt="o-", capsize=4)
        plt.xscale("log")
        plt.xlabel("dt (s)")
        plt.ylabel("Mean velocity std (m/s)")
        plt.title("Mean velocity std (sigma_v_mean) vs dt")
        plt.grid(True, which="both", alpha=0.3)
        out_pv = Path(out_path_v)
        out_pv.parent.mkdir(parents=True, exist_ok=True)
        plt.tight_layout()
        plt.savefig(out_pv)
        print(f"Saved plot to {out_pv}")

    # generate for default and alternatives
    plot_sigma_vs_dt(str(default_json), out_path_r="graphs/sigma_position_vs_dt.png", out_path_v="graphs/sigma_velocity_vs_dt.png")
    if alt_json.exists():
        plot_sigma_vs_dt(str(alt_json), out_path_r="graphs/sigma_position_vs_dt_v15r002.png", out_path_v="graphs/sigma_velocity_vs_dt_v15r002.png")
    if alt_json2.exists():
        plot_sigma_vs_dt(str(alt_json2), out_path_r="graphs/sigma_position_vs_dt_v50r002.png", out_path_v="graphs/sigma_velocity_vs_dt_v50r002.png")

    # Relative change in mean velocity spread vs dt (normalized to smallest dt or dt_ref)
    def compute_relative_change_sigma_v(summary_json_path: str, dt_ref: float = 1e-6):
        dts, sigma_rs, sigma_vs = compute_mean_sigma_summary(summary_json_path)

        # choose reference index: prefer exact match to dt_ref, otherwise smallest available dt
        idxs = np.where(np.isclose(dts, float(dt_ref)))[0]
        if len(idxs) == 0:
            # fallback to smallest dt (dts sorted ascending)
            ref_idx = 0
        else:
            ref_idx = int(idxs[0])

        sigma_ref = float(sigma_vs[ref_idx])
        if sigma_ref == 0:
            raise RuntimeError(f"Reference sigma_v at dt={dt_ref} is zero; cannot normalize")

        rel_percent = 100.0 * (sigma_vs - sigma_ref) / sigma_ref
        return dts, rel_percent

    def plot_relative_change_sigma_v_vs_dt(summary_json_path: str, dt_ref: float = 1e-6, out_path: str = "graphs/relative_change_sigma_v_vs_dt.png"):
        dts, rel_percent = compute_relative_change_sigma_v(summary_json_path, dt_ref=dt_ref)

        plt.figure(figsize=(6, 4))
        plt.plot(dts, rel_percent, "o-", markersize=6)
        plt.xscale("log")
        plt.xlabel("dt (s)")
        plt.ylabel("Relative change in mean velocity spread (%)")
        plt.title("Relative change in mean velocity spread vs dt")
        plt.grid(True, which="both", alpha=0.3)
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        plt.tight_layout()
        plt.savefig(out_p)
        print(f"Saved plot to {out_p}")

    # generate relative-change plot for default (v35r002)
    plot_relative_change_sigma_v_vs_dt(str(default_json), dt_ref=1e-6, out_path="graphs/relative_change_sigma_v_vs_dt_v35r002.png")
