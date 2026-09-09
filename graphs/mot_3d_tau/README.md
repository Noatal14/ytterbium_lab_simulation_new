# 3D-MOT population and retention plots

The PNG files in this directory are generated from an existing
`retention_summary.json` by:

```bash
python -m graphs_scripts.plot_3d_mot_tau
```

Each configuration receives a separate population plot and a separate
peak-cohort retention plot. Generated plots reflect the configuration version
that produced the selected input summary; they are not recalculated from the
current `config.py`.
