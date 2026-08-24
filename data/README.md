# Data directory

Generated data is grouped by its role in the stage-based workflow:

```text
data/
├── particle_states/
│   ├── after_zeeman/   # input ensembles for the 2D MOT
│   ├── after_2d_mot/   # input ensembles for the 3D MOT
│   └── after_3d_mot/   # captured states and 3D capture summaries
├── optimization/
│   ├── *.json          # accepted Optuna result summaries
│   └── seed_scan/      # repeated-seed uncertainty results
└── validation/
    └── zeeman/         # pre-production field/resonance audit
        ├── trajectories/ # deterministic single-particle diagnostics
        ├── capture_velocity_scan/ # ideal on-axis capture boundary
        └── stochastic_convergence/ # multi-seed RK4 timestep checks
```

The three state directories are created automatically when a stage saves an
output. Particle-state files use NumPy's ``(N, 6)`` format: position
``(x, y, z)`` followed by velocity ``(vx, vy, vz)`` in SI units.

Particle-state ``.npy`` ensembles are intentional scientific artifacts and
should be committed together with provenance metadata. They are the interfaces
between simulation stages and are required to reproduce downstream runs. Do not
delete or replace an accepted ensemble silently.

Each important state file should have an adjacent metadata JSON recording, at a
minimum, its purpose, array shape, units, generating code commit, input ensemble,
physical configuration, timestep, solver/stochastic mode, particle count, and
seed. If an older file lacks some of this information, record the unknown fields
explicitly rather than inferring them.

GitHub rejects individual files larger than 100 MB. If future state ensembles
approach that size, use Git LFS or documented external storage instead of adding
them to ordinary Git history. Historical optimization summaries are stored in
``data/optimization``.

## Stage commands

```bash
python -m simulations.zeeman
python -m simulations.mot_2d
python -m simulations.mot_3d
python -m studies.validate_zeeman_configuration
python -m studies.diagnose_zeeman_trajectories
python -m studies.scan_zeeman_capture_velocity
```

Each command accepts ``--input`` and/or ``--output`` options when a non-default
ensemble should be used. Run a command with ``--help`` for the complete list.
