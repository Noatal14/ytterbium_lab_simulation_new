# Data directory

Runtime particle ensembles and campaign outputs are intentionally not shipped
in the repository. Import or generate a versioned Zeeman source under
`particle_states/after_zeeman/<source-name>/` before creating a 2D campaign.
Every array must have adjacent metadata identifying the same profile,
seed, shape, survivor count, SHA-256 and source Git revision. Discovery,
refinement, held-out confirmation, and sealed final-validation seeds are
non-overlapping. All required seeds `3000-3034` must exist and pass these checks
before campaign creation. Only sealed production outputs may support a final
unbiased performance claim and downstream 3D-MOT state ensemble.

Generated data is grouped by its role in the stage-based workflow:

```text
data/
├── particle_states/
│   ├── after_zeeman/   # input ensembles for the 2D MOT
│   ├── after_2d_mot/   # input ensembles for the 3D MOT
│   └── after_3d_mot/   # captured states and 3D capture summaries
├── optimization/
│   ├── mot_2d/         # paired joint 2D-MOT optimization campaigns
│   └── seed_scan/      # repeated-seed uncertainty results
└── validation/
    ├── mot_2d/         # timestep and numerical checks for the 2D MOT
    └── zeeman/         # pre-production field/resonance audit
        ├── trajectories/ # deterministic single-particle diagnostics
        ├── capture_velocity_scan/ # ideal on-axis capture boundary
        └── stochastic_convergence/ # multi-seed RK4 timestep checks
```

The three state directories are created automatically when a stage saves an
output. Particle-state files use NumPy's ``(N, 6)`` format: position
``(x, y, z)`` followed by velocity ``(vx, vy, vz)`` in SI units.

Particle-state ``.npy`` ensembles are runtime scientific artifacts stored with
provenance metadata. They are the interfaces between simulation stages and
must be backed up in the approved scientific-data store when they are accepted.
Adding a runtime artifact to source control requires an explicit archival
decision; generation alone does not make it canonical.

Each important state file should have an adjacent metadata JSON recording, at a
minimum, its purpose, array shape, units, generating code commit, input ensemble,
physical configuration, timestep, solver/stochastic mode, particle count, and
seed. If an older file lacks some of this information, record the unknown fields
explicitly rather than inferring them.

The Zeeman production command creates this adjacent metadata automatically,
including runtime, software versions, and a SHA-256 hash of the saved ``.npy``.

The 2D campaign generates downstream ensembles under
``data/particle_states/after_2d_mot/final_ensemble_s0_<value>/``. A 3D campaign
must consume a provenance-validated sealed output from the selected 2D
campaign, never an assumed repository fixture.

The historical full-source Zeeman campaign is stored under
``data/validation/zeeman/full_thermal_flux_v1/``. It contains one survivor-state
array and adjacent metadata file for each of 100 seeds, plus ``summary.json``.
Its metadata records the former ``active`` 20-ring magnet profile at commit
``b70c788a4e4012ac92130f2e77363c7bb406d7a2``. It is not authoritative for the
corrected 19-ring campaign and must not be combined with the corrected 2D-MOT
results. Keep it as historical evidence until a full-angular campaign is rerun
with explicit corrected-profile provenance.

Keep large runtime ensembles in documented external storage rather than adding
them to ordinary Git history. Campaign manifests and summaries are created
under ``data/optimization`` at runtime. Decide explicitly where an accepted
campaign is archived together with its input provenance.

## Stage commands

```bash
python -m simulations.zeeman
python -m simulations.mot_2d
python -m simulations.mot_3d
python -m studies.validate_zeeman_configuration
python -m studies.diagnose_zeeman_trajectories
python -m studies.scan_zeeman_capture_velocity
python -m studies.optimize_2d_mot_joint --help
python -m studies.mot_2d_s0_campaign --help
python -m studies.run_2d_mot_final_production --help
python -m studies.full_thermal_zeeman_flux --help
```

Each command accepts ``--input`` and/or ``--output`` options when a non-default
ensemble should be used. Run a command with ``--help`` for the complete list.
