"""
lab_setup/atom_species.py — Atomic species creation.

Defines the Yb-171 atom with the broad (1S0 F=1/2 → 1P1 F=3/2) transition.
Uses atomSmltr's Atom and J0J1Transition classes.

NOTE: The J0J1Transition model approximates each hyperfine F=1/2→F=3/2
transition as a simple J=0→J=1 system.  Its model states have m=0,±1,
whereas the physical stretched excited states have m_F=±3/2.  Therefore the
factor passed to the model is (3/2)g_F, using the measured F=3/2 Zeeman
coefficient.  This is distinct from the electronic g_J value.
"""

import numpy as np
from scipy import constants as csts
from atomsmltr.atoms import Atom, J0J1Transition, Ytterbium, Strontium
from config import YB171, BLUE_TRANSITION, GREEN_TRANSITION


def _j0j1_effective_lande_factor(transition):
    """Map the physical F=3/2 ``g_F`` to the model's m=±1 states."""

    return 1.5 * transition.lande_g

def create_yb171():
    """
    Create a Yb-171 atom with the broad transition
    (1S0 F=1/2 → 1P1 F=3/2).

    Using J0J1Transition to approximate the true cycling transition.

    Returns
    -------
    atomsmltr.atoms.Atom
    """
    atom = Atom(mass=YB171.mass_kg, name="Yb171")

    # Correction factor for J=0 -> J=1 model:
    # Real transition is F=1/2 -> F=3/2 with max shift 1.5 * g_F.
    # Model has max shift 1.0 * g_model.
    # So we set g_model = 1.5 * g_F to match the force strength.
    g_effective = _j0j1_effective_lande_factor(BLUE_TRANSITION)

    main_transition = J0J1Transition(
        wavelength=BLUE_TRANSITION.wavelength_m,
        Gamma=BLUE_TRANSITION.gamma_rad_s,
        lande_factor=g_effective,
        tag="399",
    )
    atom.add_transition(main_transition)

    # 556nm Intercombination Line (F=1/2 -> F=3/2)
    green_transition = J0J1Transition(
        wavelength=GREEN_TRANSITION.wavelength_m,
        Gamma=GREEN_TRANSITION.gamma_rad_s,
        lande_factor=_j0j1_effective_lande_factor(GREEN_TRANSITION),
        tag="556",
    )
    atom.add_transition(green_transition)

    return atom


def create_atom(species="Yb171", **kwargs):
    """
    Factory function — returns an atomsmltr Atom object.

    Parameters
    ----------
    species : str
        "Yb171", "Ytterbium" (built-in ¹⁷⁴Yb), "Strontium" (built-in), or "custom".
    **kwargs : dict
        For "custom": mass_amu, wavelength_nm, Gamma_MHz, lande_g, name.

    Returns
    -------
    atomsmltr.atoms.Atom
    """
    if species == "Yb171":
        return create_yb171()
    elif species == "Ytterbium":
        return Ytterbium()
    elif species == "Strontium":
        return Strontium()
    elif species == "custom":
        # Provide defaults just in case kwargs are partially missing
        mass_amu = kwargs.get("mass_amu", 87.0)
        wavelength_nm = kwargs.get("wavelength_nm", 780.0)
        Gamma_MHz = kwargs.get("Gamma_MHz", 6.0)
        lande_g = kwargs.get("lande_g", 1.0)

        atom = Atom(
            mass=mass_amu * csts.m_u,
            name=kwargs.get("name", "CustomAtom"),
        )
        atom.add_transition(
            J0J1Transition(
                wavelength=wavelength_nm * 1e-9,
                Gamma=2 * np.pi * Gamma_MHz * 1e6,
                lande_factor=lande_g,
                tag="main",
            )
        )
        return atom
    else:
        raise ValueError(f"Unknown species: {species}")

if __name__ == "__main__":
    # Test Block to ensure everything forms correctly
    print("Testing atom_species.py...")
    try:
        atom_tests = ["Yb171", "Ytterbium", "Strontium"]
        for spec in atom_tests:
            atom = create_atom(spec)
            print(f"✅ Successfully created {atom.name} atom (Mass: {atom.mass/csts.m_u:.2f} amu).")
            # Usually the transition tag on built-in ones is 'main' or the first one in the dict
            trans_tag = list(atom.trans.keys())[0] if atom.trans else "None"
            if trans_tag != "None":
                trans = atom.trans[trans_tag]
                print(f"   -> Transition '{trans_tag}': λ = {trans.wavelength*1e9:.2f} nm, Γ/2π = {trans.Gamma/(2*np.pi)/1e6:.2f} MHz")
            
        # Test custom atom creation
        custom_atom = create_atom("custom", name="TestCustom", mass_amu=100.0, wavelength_nm=500.0, Gamma_MHz=10.0)
        print(f"✅ Successfully created Custom atom '{custom_atom.name}'.")
        print("All tests passed.")
    except Exception as e:
        print(f"❌ Error occurred: {e}")
