"""
atom_species.py — Atomic species creation.

Defines the Yb-171 atom with the broad (1S0 F=1/2 → 1P1 F=3/2) transition.
Uses atomSmltr's Atom and J0J1Transition classes.

NOTE: The J0J1Transition model approximates the hyperfine F=1/2→F=3/2
cycling transition as a simple J=0→J=1 system. This is standard practice
and captures the essential MOT physics. The Landé factor is set to g_F of
the excited F=3/2 state (ground state J=0 has negligible Zeeman shift).
"""

import numpy as np
from scipy import constants as csts
from atomsmltr.atoms import Atom, J0J1Transition, Ytterbium, Strontium

# ── Yb-171 physical constants ──────
YB171_MASS_AMU = 170.936331515          # atomic mass in amu
YB171_WAVELENGTH_M = 398.9108443e-9     # transition wavelength (m)
YB171_GAMMA_HZ = 2 * np.pi * 29.13e6    # linewidth Γ (rad/s)
YB171_ISAT_MW_CM2 = 59.97               # saturation intensity (mW/cm²)

# g-factors given as μ_B·g_F/h in kHz/G:
#   Excited 1P1 F=3/2:   965    → g_F ≈ 0.6895
_MU_B_OVER_H_KHZ_PER_G = ( csts.value("Bohr magneton") / csts.h * 1e-4 * 1e-3)  # μ_B/h in kHz/G ≈ 1399.6
YB171_LANDE_G = 965.0 / _MU_B_OVER_H_KHZ_PER_G  # ≈ 0.6895


def create_yb171():
    """
    Create a Yb-171 atom with the broad transition
    (1S0 F=1/2 → 1P1 F=3/2).

    Using J0J1Transition to approximate the true cycling transition.

    Returns
    -------
    atomsmltr.atoms.Atom
    """
    atom = Atom(mass=YB171_MASS_AMU * csts.m_u, name="Yb171")

    # Correction factor for J=0 -> J=1 model:
    # Real transition is F=1/2 -> F=3/2 with max shift 1.5 * g_F.
    # Model has max shift 1.0 * g_model.
    # So we set g_model = 1.5 * g_F to match the force strength.
    g_effective = YB171_LANDE_G * 1.5

    main_transition = J0J1Transition(
        wavelength=YB171_WAVELENGTH_M,
        Gamma=YB171_GAMMA_HZ,
        lande_factor=g_effective,
        tag="main",
    )
    atom.add_transition(main_transition)
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
