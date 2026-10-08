# Contributing

This is a research simulation project. Correctness and reproducibility take
priority over broad refactoring. Read `docs/ARCHITECTURE.md` before changing a
campaign or adding application code.

## Development environment

The supported local development interpreter is Python 3.12, matching the
minimum version declared by the bundled `atomsmltr` package.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install -e ./atomsmltr
```

`requirements.txt` contains runtime dependencies. `requirements-dev.txt` adds
the tools required to validate a change. UI dependencies will be isolated from
the scientific runtime once the UI framework is selected.

Zeus uses its managed modules and virtual environment. Do not update a live
Zeus checkout away from the commit pinned by an active campaign.

## Required checks

Run the same suite as continuous integration:

```bash
PYTHONPYCACHEPREFIX="${TMPDIR:-/tmp}/ytterbium-lab-pycache" \
  MPLBACKEND=Agg python -m compileall -q \
  config.py lab_setup simulations studies utils workflow_api
MPLBACKEND=Agg python -m pytest -q
git diff --check
```

The first command catches syntax/import-source mistakes without running a
simulation. The test suite covers both the project code and the bundled
`atomsmltr` tests through the root `pyproject.toml` configuration.

For a campaign change, also run its documented no-simulation dry run and inspect
the generated PBS files and dependency chain.

## Change boundaries

- Do not mix physics changes, campaign-design changes, file moves, and UI work
  in one commit.
- Keep the root campaign managers as the lifecycle and submission authorities.
- Keep `workflow_api` read-only and side-effect-free.
- Do not weaken manifest, hash, seed, solver, timestep, or commit checks to make
  an old result pass.
- Preserve the distinction between candidate selection and sealed validation.
- Do not commit credentials, scheduler logs, transient databases, or local
  virtual environments.

## Review expectations

A review should identify the scientific and operational risk of a change, not
only its formatting. Any moved or deleted workflow must have its active callers,
tests, documentation, generated PBS paths, and reconstruction value checked.

Before deleting data, distinguish Git-tracked, local-only, and Zeus-only copies.
A Git tag does not preserve ignored or remote-only artifacts.
