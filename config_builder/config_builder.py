"""
config_builder.py — Step 9: Configurations

A Configuration Factory to combine modular components built in Steps 1-8 into a 
dynamic simulation Environment. Avoids hardcoded static configurations.
"""

from atomsmltr.simulation import Configuration

# Import all component builders from Steps 1-8
from .atom_species import create_atom
from .laser_setup import setup_2dmot_lasers
from .zeeman_laser_setup import setup_zeeman_laser
from .mag_field_custom import CustomQuadrupole
from .mag_field_Zeeman import ZeemanSlowerField
from .mag_field_builtin import get_builtin_2dmot_magnetic_field
from .gravity import get_gravity_force
from .zones import get_2dmot_testing_zone

def build_base_config(**kwargs):
    """
    Configuration Factory for 2DMOT Simulation.
    Creates an `Atom` and an `Environment` configured with dynamic parameters.

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
    atom_name = kwargs.get("atom_species", "Yb171")
    atom = create_atom(atom_name)
    
    # --- 2. MOT Lasers Config ---
    s0 = kwargs.get("s0", 1.0)
    detuning_gamma = kwargs.get("detuning_gamma", -1.0)
    swap_pol = kwargs.get("swap_polarization", False)
    mot_beams = setup_2dmot_lasers(s0=s0, detuning_gamma=detuning_gamma, atom_species_name=atom_name, swap_polarization=swap_pol)
    
    include_zeeman_laser = kwargs.get("include_zeeman_laser", False)
    if include_zeeman_laser:
        s0_z = kwargs.get("s0_zeeman", 3.0)
        det_gamma_z = kwargs.get("detuning_gamma_zeeman", -13.75)
        zeeman_beams = setup_zeeman_laser(s0=s0_z, detuning_gamma=det_gamma_z, atom_species_name=atom_name)
    else:
        zeeman_beams = []
    
    all_beams = mot_beams + zeeman_beams
    
    # --- 3. Magnetic Field Config ---
    use_builtin_mag = kwargs.get("use_builtin_mag", False)
    include_zeeman_field = kwargs.get("include_zeeman_field", False)
    
    mag_fields = []
    if not use_builtin_mag:
        radius = kwargs.get("magnet_radius", 0.06)
        mag_fields.append(CustomQuadrupole(radius=radius))
    else:
        gradient_G_cm = kwargs.get("builtin_mag_gradient", 50.0)
        mag_fields.append(get_builtin_2dmot_magnetic_field(gradient_G_cm=gradient_G_cm))
        
    if include_zeeman_field:
        z_angle = kwargs.get("zeeman_angle_deg", 25.0)
        z_dist = kwargs.get("zeeman_start_distance", 0.314)
        mag_fields.append(ZeemanSlowerField(angle_deg=z_angle, start_distance=z_dist))

    # --- 4. Gravity Config ---
    gravity_enabled = kwargs.get("gravity_enabled", False)
    gravity_force = get_gravity_force(atom.mass, enabled=gravity_enabled)

    # --- 5. Zones Config ---
    zones = kwargs.get("zones", get_2dmot_testing_zone())

    # --- Construct Full Configuration ---
    # The Configuration object requires a list of EnvObjects and the Atom object.
    env_objects = all_beams + mag_fields + [gravity_force]
    if isinstance(zones, list):
        env_objects.extend(zones)
    else:
        env_objects.append(zones)
        
    config = Configuration(object_list=env_objects, atom=atom)
    
    # --- 6. Couple Atom to Lasers ---
    # Atomsmltr strictly requires explicit coupling to compute optical forces.
    main_trans_tag = list(atom.trans.keys())[0] if atom.trans else None
    if main_trans_tag:
        trans = atom.trans[main_trans_tag]
        
        # We need to correctly couple detunings based on the beam type
        # MOT beams use `detuning_gamma`, Zeeman beams use `detuning_gamma_zeeman`
        for laser_tag, laser_obj in config.objects['laser'].items():
            if "Zeeman" in laser_tag:
                curr_detuning_rad_s = kwargs.get("detuning_gamma_zeeman", -13.75) * trans.Gamma
            else:
                curr_detuning_rad_s = detuning_gamma * trans.Gamma
                
            config.add_atomlight_coupling(laser=laser_tag, transition=main_trans_tag, detuning=curr_detuning_rad_s)

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
        atom_o, env_o = build_base_config(
            atom_species="Strontium",
            s0=2.5,
            detuning_gamma=-1.5,
            use_builtin_mag=True,
            builtin_mag_gradient=40.0,
            gravity_enabled=True
        )
        print(f"Atom: {atom_o.name}")
        print("✅ Config factory test passed successfully.")
        
    except Exception as e:
        print(f"❌ Error during config build test: {e}")
