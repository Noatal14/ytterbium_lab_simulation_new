# UI quick start

Use the application to run simulations and optimization campaigns. The terminal
is needed only to install and start it; run controls are in the browser.

## 1. Get the project — both Mac and Windows

Install **Python 3.12**, **Node.js 24 LTS** (includes npm), and **Git**.
On Windows, enable “Add Python to PATH” during installation and use a folder
on the local Windows drive, not a shared Mac folder or network drive.

If you do not already have the project, open **Terminal on Mac** or
**PowerShell on Windows**, then run:

```text
git clone https://github.com/Noatal14/ytterbium_lab_simulation_new.git
cd ytterbium_lab_simulation_new
```

GitHub may ask you to sign in if the repository is private. If you already have
the project, open a terminal in its main folder instead: the folder containing
`config.py`, `requirements-dev.txt`, and `ui`.

## 2. Install and start — choose your operating system

### Mac — Terminal

**First time only**, from the main project folder:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip install -e ./atomsmltr
cd ui
npm ci
npm run dev
```

**Next time**, open a new terminal in the main project folder:

```bash
source .venv/bin/activate
cd ui
npm run dev
```

### Windows — PowerShell

**First time only**, from the main project folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -e .\atomsmltr
$env:PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
cd ui
npm.cmd ci
npm.cmd run dev
```

If `py` is unavailable, use `python -m venv .venv` instead, after checking that
`python --version` reports Python 3.12.

**Next time**, open a new PowerShell window in the main project folder:

```powershell
$env:PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
cd ui
npm.cmd run dev
```

No PowerShell activation script or execution-policy change is needed.

### Open the application — both systems

Open the address printed in the terminal, normally **http://localhost:5173**.
Keep the terminal open. To stop the application, press **Ctrl+C** there.
Do not close it while a local simulation is running.

## 3. Choose a simulation or campaign — both systems

- **Run one simulation:** Zeeman, 2D MOT, or 3D MOT. Choose **This computer**
  for a small local run (up to 1,000 atoms), or **Zeus** for remote work.
- **Start a campaign:** a 2D-MOT or 3D-MOT optimization on Zeus. Campaigns can
  take days; use an individual simulation for a quick trial.

Choose the source and settings, review them, and confirm the action. Selecting
a page or reviewing settings does not start a simulation or submit a job.

2D MOT needs a verified Zeeman source; 3D MOT needs a verified 2D-MOT source.
To reuse an individual run's output, enable particle-state retention before
running it. Only verified sources in this checkout are listed, and saved
individual states are not automatically approved campaign inputs. If the list
is empty, ask the project maintainer for the required source data.

## 4. Connect to Zeus — both systems

Local runs do not need Zeus. For remote runs:

1. Obtain an active Zeus account and connect to the **Technion VPN**.
2. In the application, open **Zeus jobs**. For a new computer, expand
   **First time connecting? View setup guide** and follow the SSH-key setup.
   Windows and Mac each need their own working SSH setup.
3. Enter your Technion username, check the remote project directory, and select
   **Connect and check status**.
4. Before the first submission, ask the project maintainer to verify that the
   remote checkout, Python environment, source data, and code revision are ready.
   A successful connection alone does not install or configure them.

SSH setup is a one-time prerequisite, not completed by clicking Connect. Follow
the official Technion instructions; verify the server fingerprint before
trusting a first connection. Load your key into the SSH agent before opening
the application. Never paste a password, private key, or passphrase into it.

## 5. Follow the work and view results — both systems

- **Queued / Running:** wait; use **Check status** for a fresh remote status.
- **Action needed:** read the message near the relevant action.
- **Results:** open the verified summary and any retained particle states.
  A finished Zeus job is not a verified result until its output is checked.
- **Uncertain submission:** do not submit again. Inspect **Zeus jobs** first
  to avoid duplicate work.

Remote campaign actions and status checks require the code version that created
the campaign. Keep that checkout for recovery; ask the maintainer to use a
separate checkout for application updates. Updating another checkout does not
change or cancel running Zeus jobs.

If something fails, keep the exact message and run/campaign name and send them
to the project maintainer. Do not delete results, edit campaign files, or
restart an entire campaign to recover one failed stage.

For maintainers: [release tests and isolated Zeus test mode](docs/UI_RELEASE_ACCEPTANCE_CHECKLIST.md)
and [Windows validation details](docs/windows-validation.md).

## Included team inputs

A checkout of `main` includes exactly three initial particle populations:

| Input | Particles | Original ensembles | Intended use |
| --- | ---: | ---: | --- |
| Canonical Zeeman survivors | 1,110,091 | 35 | Input to 2D MOT |
| Optimized 2D-MOT survivors, s₀=1.3 | 16,883 | 20 | Individual 3D-MOT input |
| Held-out 2D-MOT validation survivors, s₀=1.3 | 16,675 | 20 | Individual 3D-MOT input; retains its historical held-out identity |

Each population preserves its original ensemble files and metadata, rather
than merging away seed identities. All arrays and provenance are checked before
use. The two 3D input populations remain separate; their presence does not admit
them as fresh campaign search or validation inputs. New campaigns retain their
existing upstream qualification and population-separation requirements.

Old smoke-test inputs and saved individual runs are not included. New results
created by a user remain local runtime data and can appear as individual follow-up
inputs. Scientific reports and closed-campaign evidence are retained separately;
they are not extra selectable input populations.

### One code version, a separate Zeus deployment

The local UI/backend and the dedicated Zeus checkout must run the same Git
commit. A saved run also pins that commit; updating code does not rewrite old
runs or their scientific evidence. A version mismatch stops submission before
`qsub` and must be resolved by synchronizing the deployment, not by changing
saved records.

To use the isolated deployment with the normal UI, put
`VITE_ZEUS_CHECKOUT=ytterbium_lab_simulation_ui_test` in
`ui/.env.development.local` before starting. This is a deployment setting, not a
second product version; it does not change numerical or campaign policies.
Only the named supported checkouts are accepted. The Zeus connection screen
shows the selected remote project directory. Restart after changing the setting.
Do not update the scientific checkout to run UI acceptance tests.

Individual particle capacities are owned by
`workflow_api/individual_limits.py`. Family JSON specifications and generated
TypeScript are checked contract projections, not separate policy owners.
Run `python -m scripts.generate_individual_limits` after updating the policy;
regression tests reject divergent family contracts. Storage metadata and SSH
request byte bounds are separate finite safeguards; full maximum-particle
packages are tested against them.
