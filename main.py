import numpy as np
import matplotlib.pyplot as plt

from config_builder.config_builder import build_base_config
from utils.kinematics import generate_single_atom_state
from atomsmltr.simulation.simulator import ScipyIVP_3D


def run_experiment_A(config, v_in=50.0, z_offset_range=(-0.02, 0.02), y_offset_range=(-0.01, 0.01), N_particles=25):
    """
    Experiment A: Spatial Offset Sweep & Force Heatmap.
    Sweeps initial atom coordinate offsets in the ZY plane at a constant incoming velocity.
    """
    print(f"\n--- Running Experiment A: Spatial Sweep (N={N_particles}) ---")

    # 1. Generate u0_list (Initial States)
    # We will evenly sample the given range
    z_offs = np.linspace(z_offset_range[0], z_offset_range[1], int(np.sqrt(N_particles)))
    y_offs = np.linspace(y_offset_range[0], y_offset_range[1], int(np.sqrt(N_particles)))

    u0_list = []
    positions_to_plot = []

    for dy in y_offs:
        for dz in z_offs:
            # Our kinematics definition: pos_offset=(dx, dy_trans, dz_long)
            # We want a literal Cartesian shift here, but generate_single_atom_state uses a beam-local frame.
            # For a simple spatial sweep keeping the default 25-deg trajectory aimed at the origin,
            # let's map dy to dy_trans, and dz to dz_long.
            pos_offset = (0.0, dy, dz)
            r0, v0 = generate_single_atom_state(v0=v_in, r0=0.10, angle_deg=25.0, pos_offset=pos_offset)
            # Combine position and velocity into the 6D state vector expected by atomsmltr
            u0 = np.concatenate((r0, v0))
            u0_list.append(u0)
            positions_to_plot.append(r0)

    # 2. Setup Simulation
    # Time array: 50m/s over 15cm is ~3ms. We will simulate for 10ms.
    time_points = np.linspace(0, 10e-3, 500)

    sim = ScipyIVP_3D(config)
    sim.u0_list = u0_list

    # Run batch in parallel
    print("Simulating trajectories...")
    res_list = sim.run(time_points, npools=4, verbose=False)

    # 3. Create Plot with Force Heatmap Background
    print("Generating Force Heatmap and Trajectory Plot...")

    fig, ax = plt.subplots(figsize=(8, 6), layout='constrained')

    # --- Background Heatmap ---
    # Create a grid in the ZY plane
    z_grid = np.linspace(-0.12, 0.51, 200)
    # Y range: same physical scale as Z range (0.63m total)
    y_half = (0.51 - (-0.12)) / 2.0  # 0.315m
    y_grid = np.linspace(-y_half, y_half, 200)
    Z_mesh, Y_mesh = np.meshgrid(z_grid, y_grid)

    # Prepare states to evaluate force: V=0, all positions.
    # U vector mathematically expects (N, 6) arrays shaped [X, Y, Z, Vx, Vy, Vz]
    U_mesh = np.column_stack((
        np.zeros_like(Z_mesh.ravel()),
        Y_mesh.ravel(),
        Z_mesh.ravel(),
        np.zeros_like(Z_mesh.ravel()),
        np.zeros_like(Z_mesh.ravel()),
        np.zeros_like(Z_mesh.ravel())
    ))

    # Get the total environmental force acting on the atom correctly utilizing atomsmltr simulation coupling
    forces = sim.get_force(U_mesh)

    # Calculate magnitude and direction in ZY plane
    Fz = forces[:, 2].reshape(Z_mesh.shape)
    Fy = forces[:, 1].reshape(Z_mesh.shape)
    F_mag = np.sqrt(Fz ** 2 + Fy ** 2)

    c = ax.pcolormesh(Z_mesh, Y_mesh, F_mag, cmap='viridis', shading='auto', alpha=0.9)
    fig.colorbar(c, ax=ax, label="|Force| (N)")
    ax.streamplot(z_grid, y_grid, Fz, Fy, color='white', density=0.8, linewidth=0.5, arrowsize=0.5)

    # --- Plot Trajectories ---
    for i, res in enumerate(res_list):
        # res.y has shape (6, N_timepoints). Rows 0,1,2 are X,Y,Z.
        y_traj = res.y[1, :]
        z_traj = res.y[2, :]

        # Determine if trapped (simplistic check: doesn't fly out of bounds at end)
        final_speed = np.linalg.norm(res.y[3:, -1])
        color = 'red' if final_speed > 10.0 else 'orange'  # Fast = escaped (red), Slow = trapped/cooled (orange)

        ax.plot(z_traj, y_traj, color=color, linewidth=1.5, alpha=0.8)

    ax.set_title("Experiment A: Spatial Sweep Trajectories over Force Heatmap")
    ax.set_xlabel("Z Position (m)")
    ax.set_ylabel("Y Position (m)")
    ax.set_xlim([-0.12, 0.51])
    ax.set_ylim([-y_half, y_half])
    ax.set_aspect('equal')

    img_name = "experiment_A_heatmap.png"
    plt.savefig(img_name, dpi=300)
    print(f"✅ Saved plot to {img_name}")
    plt.show()
    # --- 3D Visualization Debugging ---
    print("Generating 3D Visualization for Debugging...")
    import scipy.spatial.transform as transform

    fig3d = plt.figure(figsize=(12, 10))
    ax3d = fig3d.add_subplot(111, projection='3d')

    # --- Helper: rotation from z-hat to an arbitrary direction ---
    def rotation_z_to_dir(dir_vec):
        z_hat = np.array([0, 0, 1.0])
        d = np.array(dir_vec, dtype=float)
        d = d / np.linalg.norm(d)
        axis = np.cross(z_hat, d)
        angle = np.arccos(np.clip(np.dot(z_hat, d), -1.0, 1.0))
        if np.linalg.norm(axis) > 1e-6:
            return transform.Rotation.from_rotvec(axis / np.linalg.norm(axis) * angle)
        elif angle > np.pi / 2:
            return transform.Rotation.from_euler('x', 180, degrees=True)
        else:
            return transform.Rotation.identity()

    # --- Helper: draw a cylinder (circular cross-section) ---
    def draw_cylinder(cyl, ax, color='yellow', alpha=0.1):
        if not (hasattr(cyl, 'radius') and hasattr(cyl, 'length')):
            return
        z_cyl = np.linspace(0, cyl.length, 30)
        theta = np.linspace(0, 2 * np.pi, 30)
        Z_c, Theta = np.meshgrid(z_cyl, theta)
        X_c = cyl.radius * np.cos(Theta)
        Y_c = cyl.radius * np.sin(Theta)

        rot = rotation_z_to_dir(cyl.direction)
        pts = np.column_stack((X_c.ravel(), Y_c.ravel(), Z_c.ravel()))
        pts_rot = rot.apply(pts) + np.array(cyl.origin)

        ax.plot_surface(
            pts_rot[:, 0].reshape(X_c.shape),
            pts_rot[:, 1].reshape(Y_c.shape),
            pts_rot[:, 2].reshape(Z_c.shape),
            color=color, alpha=alpha, shade=False
        )

    # --- Helper: recursively find and draw all FiniteCylinder zones ---
    def draw_zones_recursive(zone_obj, ax, color='yellow', alpha=0.1):
        if hasattr(zone_obj, 'zones'):
            for sub in zone_obj.zones:
                draw_zones_recursive(sub, ax, color, alpha)
        else:
            draw_cylinder(zone_obj, ax, color, alpha)

    # --- Plot Trajectories in 3D ---
    for res in res_list:
        x_traj, y_traj, z_traj = res.y[0, :], res.y[1, :], res.y[2, :]
        ax3d.plot(x_traj, y_traj, z_traj, color='blue', linewidth=1.0, alpha=0.6)

    # --- Plot ALL Zones (recursively) ---
    for zone_tag, zone_obj in config.objects['zone'].items():
        draw_zones_recursive(zone_obj, ax3d, color='yellow', alpha=0.08)

    # --- Plot Lasers as proper elliptical tubes ---
    # The 3D visualization must use the beam's stated `direction` for the tube axis,
    # NOT the internal laser frame's propagation axis (which maps to Lab -X for all beams).
    # Cross-section widths are computed from the actual intensity profile by probing
    # which laser-frame coordinate each lab transverse axis maps to.
    for laser_tag, laser_obj in config.objects['laser'].items():
        wx = getattr(laser_obj, 'wx', None)
        wy = getattr(laser_obj, 'wy', None)
        if wx is None or wy is None:
            continue

        direction = np.array(laser_obj.direction, dtype=float)
        direction = direction / np.linalg.norm(direction)
        org = np.array(getattr(laser_obj, 'waist_position', [0, 0, 0]), dtype=float)

        # Build the rotation matrix R: lab → laser frame
        probe = np.eye(3) * 0.01
        laser_coords = laser_obj._convert_coordinates_to_laser_frame(probe)
        R = laser_coords / 0.01  # 3x3: laser = R @ lab

        # Find two lab-frame transverse axes perpendicular to the stated direction
        # Use Gram-Schmidt: pick a vector not parallel to direction
        if abs(direction[2]) < 0.9:
            up = np.array([0, 0, 1.0])
        else:
            up = np.array([1.0, 0, 0])
        e1 = np.cross(direction, up)
        e1 = e1 / np.linalg.norm(e1)
        e2 = np.cross(direction, e1)
        e2 = e2 / np.linalg.norm(e2)

        # Compute the effective 1/e² beam radius along each transverse axis
        # A lab displacement along e1 maps to laser coords (R @ e1),
        # then intensity is exp(-2*(x_l²/wx² + y_l²/wy²))
        # 1/e² radius along e1 = 1/sqrt((R@e1)[0]²/wx² + (R@e1)[1]²/wy²)
        Re1 = e1 @ R
        Re2 = e2 @ R
        r_e1 = 1.0 / np.sqrt(Re1[0] ** 2 / wx ** 2 + Re1[1] ** 2 / wy ** 2)
        r_e2 = 1.0 / np.sqrt(Re2[0] ** 2 / wx ** 2 + Re2[1] ** 2 / wy ** 2)

        # Build the elliptical tube along the stated direction
        z_cyl = np.linspace(-0.04, 0.04, 30)
        theta = np.linspace(0, 2 * np.pi, 30)
        Z_c, Theta = np.meshgrid(z_cyl, theta)

        # Cross-section ellipse using lab-frame transverse basis
        pts = (r_e1 * np.cos(Theta))[..., np.newaxis] * e1 + \
              (r_e2 * np.sin(Theta))[..., np.newaxis] * e2 + \
              Z_c[..., np.newaxis] * direction + org

        ax3d.plot_surface(
            pts[..., 0], pts[..., 1], pts[..., 2],
            color='purple', alpha=0.25, shade=False
        )
        # Add a label at the beam tip
        tip = org + direction * 0.04
        ax3d.text(tip[0], tip[1], tip[2], laser_tag, fontsize=7, color='purple')

    ax3d.set_xlabel('X (m)')
    ax3d.set_ylabel('Y (m)')
    ax3d.set_zlabel('Z (m)')
    ax3d.set_title('3D Debug: Trajectories (Blue), Zones (Yellow), Lasers (Purple)')

    # --- Set truly equal axis limits ---
    # Collect all data extents
    all_pts = []
    for res in res_list:
        all_pts.append(res.y[:3, :].T)
    all_pts = np.vstack(all_pts)

    x_min, x_max = all_pts[:, 0].min(), all_pts[:, 0].max()
    y_min, y_max = all_pts[:, 1].min(), all_pts[:, 1].max()
    z_min, z_max = all_pts[:, 2].min(), all_pts[:, 2].max()

    # Expand to include zones (rough extent)
    x_min, x_max = min(x_min, -0.05), max(x_max, 0.05)
    y_min, y_max = min(y_min, -0.05), max(y_max, 0.05)
    z_min, z_max = min(z_min, -0.12), max(z_max, 0.52)

    half_range = max(x_max - x_min, y_max - y_min, z_max - z_min) / 2.0
    x_mid = (x_min + x_max) / 2.0
    y_mid = (y_min + y_max) / 2.0
    z_mid = (z_min + z_max) / 2.0

    ax3d.set_xlim(x_mid - half_range, x_mid + half_range)
    ax3d.set_ylim(y_mid - half_range, y_mid + half_range)
    ax3d.set_zlim(z_mid - half_range, z_mid + half_range)
    ax3d.set_box_aspect([1, 1, 1])

    img_name_3d = "experiment_A_3D.png"
    plt.savefig(img_name_3d, dpi=300)
    print(f"✅ Saved 3D debug plot to {img_name_3d}")
    plt.show()

if __name__ == "__main__":
    print("Initializing Default Configuration...")
    atom, config = build_base_config()

    run_experiment_A(config)

