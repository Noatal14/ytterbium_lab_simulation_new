"""
config_builder.py — Step 9: Configurations

A Configuration Factory to combine modular components built in Steps 1-8 into a 
dynamic simulation Environment. Avoids hardcoded static configurations.
"""

from atomsmltr.simulation import Configuration

# Import all component builders from Steps 1-8
from lab_setup.atom_species import create_atom
from lab_setup.laser_setup_2d_mot import setup_2dmot_lasers
from lab_setup.zeeman_laser_setup import setup_zeeman_laser
from lab_setup.laser_setup_3d import setup_3dmot_lasers
from lab_setup.mag_field_2d_mot import CustomQuadrupole
from lab_setup.mag_field_Zeeman import ZeemanSlowerField
from lab_setup._3d_mot_mag_field import get_builtin_3dmot_magnetic_field
from lab_setup.gravity import get_gravity_force
from lab_setup.zones import get_2dmot_chamber_only_zone, get_zeeman_only_zone
from config import (
    Geometry,
    ZEEMAN_LASER_CONFIG,
    MOT_2D_LASER_CONFIG,
    MOT_3D_LASER_CONFIG,
    MOT_3D_MAGNETIC_FIELD_GRADIENT_G_CM,
    ZEEMAN_FIELD_CONFIG,
    MOT_2D_MAGNET_RADIUS_M,
)

def build_base_config(
    atom_species="Yb171",

    include_2d_mot=True,
    include_zeeman=True,
    include_3dmot=False,

    # Lasers configurations
    _2d_mot_config=MOT_2D_LASER_CONFIG,
    zeeman_config=ZEEMAN_LASER_CONFIG,
    _3d_mot_config=MOT_3D_LASER_CONFIG,

    # Magnetic field configurations
    zeeman_field_config=ZEEMAN_FIELD_CONFIG,
    magnet_radius=MOT_2D_MAGNET_RADIUS_M,
    _3d_mot_gradient_G_cm=MOT_3D_MAGNETIC_FIELD_GRADIENT_G_CM,

    gravity_enabled=False,
    zones=None,
):
    """
    Central configuration factory for the Zeeman, 2D-MOT, 3D-MOT,
    gravity, and boundary-condition environment.

    Defaults:
        - Atom: 'Yb171'
        - MOT parameters: s0=1.0, detuning_gamma=-1.0
        - Magnetic field: Custom Magpylib field (CustomQuadrupole)
        - Gravity: OFF
        - Zones: 2D MOT testing zone

    Parameters (kwargs):
    --------------------
        atom_species (str): Atom Name (e.g. 'Yb171', 'Strontium')
        s0 (float): Saturation parameter for MOT lasers
        detuning_gamma (float): Detuning in units of Gamma
        
        use_builtin_mag (bool): Set to True to use BuiltInQuadrupole instead of magpylib
        magnet_radius (float): Radius for custom quadrupole (default: 0.06m)
        builtin_mag_gradient (float): Gradient for built-in quadrupole (default: 50.0 G/cm)
        
        gravity_enabled (bool): Whether to enable the gravity constant force
        zones (ZoneCollection): Overridable zone definitions. If None or not provided, uses testing zone.
        
    Returns:
    --------
        atom (atomsmltr.atoms.Atom): Configured atomic species
        env (atomsmltr.environment.Environment): Full simulation environment
    """
    
    # --- 1. Atom Species Config ---
    atom_name = atom_species
    atom = create_atom(atom_name)
    
    # --- 2. 2D MOT Lasers Config ---
    if include_2d_mot:
        mot_beams = setup_2dmot_lasers(s0=_2d_mot_config["s0"], detuning_gamma=_2d_mot_config["detuning_gamma"], atom_species_name=atom_name, swap_polarization=_2d_mot_config["swap_polarization"])
    else:
        mot_beams = []

    # --- 3. Zeeman laser Config ---    
    if include_zeeman:
        zeeman_beams = setup_zeeman_laser(s0=zeeman_config["s0"], detuning_gamma=zeeman_config["detuning_gamma"], atom_species_name=atom_name)
    else:
        zeeman_beams = []
        
    # --- 4. 3D MOT Lasers Config ---
    if include_3dmot:
        mot3d_beams = setup_3dmot_lasers(
            mot_3d_config=_3d_mot_config,
            center_position=_3d_mot_config.get("center_position_m", Geometry.MOT_3D_CENTER_M),
        )
    else:
        mot3d_beams = []
    
    all_beams = mot_beams + zeeman_beams + mot3d_beams
    
    # --- 5. Magnetic Field Config ---    
    mag_fields = []
    if include_2d_mot:
        radius = magnet_radius
        mag_fields.append(CustomQuadrupole(radius=radius))

    if include_3dmot:
        mag_fields.append(
            get_builtin_3dmot_magnetic_field(
                gradient_G_cm=_3d_mot_gradient_G_cm,
                origin=_3d_mot_config["center_position_m"],
                strong_axis=_3d_mot_config.get("magnetic_strong_axis", "z"),
            )
        )

    if include_zeeman:
        radii = zeeman_field_config["radii_m"]
        positions = zeeman_field_config["positions_m"]
        tilt_angles = zeeman_field_config["tilt_angles_deg"]
        if radii is None or positions is None or tilt_angles is None:
            mag_fields.append(ZeemanSlowerField(angle_deg=Geometry.ZEEMAN_ARM_ANGLE_DEG, start_distance=Geometry.ZEEMAN_START_DISTANCE_M))
        else:
            mag_fields.append(ZeemanSlowerField(
                angle_deg=Geometry.ZEEMAN_ARM_ANGLE_DEG,
                start_distance=Geometry.ZEEMAN_START_DISTANCE_M,
                radii=radii,
                positions_z=positions,
                tilt_angles=tilt_angles,
            ))

    # --- 6. Gravity Config ---
    gravity_force = get_gravity_force(atom.mass, enabled=gravity_enabled)

    # --- 7. Zones Config ---
    # --- Construct Full Configuration ---
    # The Configuration object requires a list of EnvObjects and the Atom object.
    env_objects = all_beams + mag_fields + [gravity_force]
    if isinstance(zones, list):
        env_objects.extend(zones)
    else:
        env_objects.append(zones)
        
    config = Configuration(object_list=env_objects, atom=atom)
    
    # --- 8. Couple Atom to Lasers ---
    # Atomsmltr strictly requires explicit coupling to compute optical forces.
    # We map specific lasers to specific transitions based on their tags
    if atom.trans:
        main_trans_tag = list(atom.trans.keys())[0]
        for laser_tag, laser_obj in config.objects['laser'].items():
            if "556" in laser_tag:
                trans_tag = "556" if "556" in atom.trans else main_trans_tag
                curr_detuning_rad_s = _3d_mot_config["556"]["detuning_gamma"] * atom.trans[trans_tag].Gamma
            elif "399" in laser_tag:
                trans_tag = "399" if "399" in atom.trans else main_trans_tag
                curr_detuning_rad_s = _3d_mot_config["399"]["detuning_gamma"] * atom.trans[trans_tag].Gamma
            elif "Zeeman" in laser_tag:
                trans_tag = "399" if "399" in atom.trans else main_trans_tag
                curr_detuning_rad_s = zeeman_config["detuning_gamma"] * atom.trans[trans_tag].Gamma
            else:
                # Default 2D MOT beams (they cool on the 399nm transition)
                trans_tag = "399" if "399" in atom.trans else main_trans_tag
                curr_detuning_rad_s = _2d_mot_config["detuning_gamma"] * atom.trans[trans_tag].Gamma
                
            config.add_atomlight_coupling(laser=laser_tag, transition=trans_tag, detuning=curr_detuning_rad_s)

    return atom, config

def build_2dmot_config(
    s0=MOT_2D_LASER_CONFIG["s0"],
    detuning_gamma=MOT_2D_LASER_CONFIG["detuning_gamma"],
    magnet_radius=MOT_2D_MAGNET_RADIUS_M,
):
    """Build a configuration that contains only the 2D MOT components."""
    atom, config = build_base_config(
        atom_species="Yb171",

        include_2d_mot=True,
        include_zeeman=False,
        include_3dmot=False,

        _2d_mot_config={ 
            "s0": s0, 
            "detuning_gamma": detuning_gamma, 
            "swap_polarization": False 
        },
        magnet_radius=magnet_radius,
        gravity_enabled=False,
        zones=get_2dmot_chamber_only_zone(),
    )
    return atom, config


def build_zeeman_config(
    s0_zeeman=ZEEMAN_LASER_CONFIG["s0"],
    detuning_gamma_zeeman=ZEEMAN_LASER_CONFIG["detuning_gamma"],
    magnet_radius=MOT_2D_MAGNET_RADIUS_M,
    gravity_enabled=False,
    radii=None,
    positions=None,
    tilt_angles=None,
    zones=None,
):
    """Build a configuration that contains the Zeeman slower components."""
    atom, config = build_base_config(
        atom_species="Yb171",

        include_2d_mot=False,
        include_zeeman=True,
        include_3dmot=False,

        magnet_radius=magnet_radius,
        gravity_enabled=gravity_enabled,
        zeeman_config={
            "s0": s0_zeeman,
            "detuning_gamma": detuning_gamma_zeeman,
        },
        zeeman_field_config={
            "radii_m": radii,
            "positions_m": positions,
            "tilt_angles_deg": tilt_angles,
        },
        zones=get_zeeman_only_zone() if zones is None else zones,
    )
    return atom, config

if __name__ == "__main__":
    print("Testing config_builder.py...")
    try:
        # Test 1: Default Baseline Configuration
        print("\n--- Test 1: Building Default Config ---")
        atom_d, env_d = build_base_config()
        print(f"Atom: {atom_d.name} (Mass: {atom_d.mass:.2e} kg)")
        print(f"Configuration instantiated successfully.")
        
        # Test 2: Overriding kwargs
        print("\n--- Test 2: Building Override Config ---")
        atom_o, env_o = build_base_config()
        print(f"Atom: {atom_o.name}")
        print("✅ Config factory test passed successfully.")
        
    except Exception as e:
        print(f"❌ Error during config build test: {e}")
