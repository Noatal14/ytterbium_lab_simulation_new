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
git clone --branch main https://github.com/Noatal14/ytterbium_lab_simulation_new.git "Ytterbium UI"
cd "Ytterbium UI"
```

GitHub may ask you to sign in if the repository is private. If you already have
the project, open a terminal in its main folder instead: the folder containing
`config.py`, `requirements-dev.txt`, and `ui`.

## 2. Install and start — choose your operating system

### Mac — Terminal

**First time only**, from the main project folder:

```bash
set -e
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-team.txt
python -m pip install --no-build-isolation -c constraints-team.txt -e ./atomsmltr
python -m pip check
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
if ($LASTEXITCODE -ne 0) { throw "Installation failed. Stop here and keep the error message." }
.\.venv\Scripts\python.exe -m pip install -r requirements-team.txt
if ($LASTEXITCODE -ne 0) { throw "Installation failed. Stop here and keep the error message." }
.\.venv\Scripts\python.exe -m pip install --no-build-isolation -c constraints-team.txt -e .\atomsmltr
if ($LASTEXITCODE -ne 0) { throw "Installation failed. Stop here and keep the error message." }
.\.venv\Scripts\python.exe -m pip check
if ($LASTEXITCODE -ne 0) { throw "Installation failed. Stop here and keep the error message." }
cd ui
npm.cmd ci
if ($LASTEXITCODE -ne 0) { throw "Installation failed. Stop here and keep the error message." }
npm.cmd run dev
```

If `py` is unavailable, use `python -m venv .venv` instead, after checking that
`python --version` reports Python 3.12.

**Next time**, open a new PowerShell window in the main project folder:

```powershell
cd ui
npm.cmd run dev
```

No PowerShell activation script or execution-policy change is needed. The shared
launcher uses the Python environment inside this checkout on both platforms.
Remove any old `PYTHON` environment override before launching a new installation.

### Open the application — both systems

Open the address printed in the terminal, normally **http://localhost:5173**.
Keep the terminal open. To stop the application, press **Ctrl+C** there.
Do not close it while a local simulation is running.

## 3. Choose a simulation or campaign — both systems

- **Run one simulation:** Zeeman, 2D MOT, or 3D MOT. Choose **This computer**
  for a small local run, or **Zeus** for remote work. The form shows the
  validated capacity for the chosen simulation and execution mode.
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
4. Before the first submission, complete the one-time personal-account setup in
   [Team deployment](docs/TEAM_DEPLOYMENT.md). The UI must show
   `/home/YOUR_USERNAME/ytterbium_lab_simulation_ui`. Connecting does not install it.
   The local and remote commit must match exactly.

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

After a 2D campaign finishes on Zeus, check Finalization and select
**Review local collection**. Review the exact files and sizes, then select
**Collect verified outputs**. This copies and verifies the completed results;
it does not submit a job. Keep the original local checkout and matching Zeus
deployment at the campaign's pinned commit throughout collection. Once the
verified local collection is recorded, eligible 2D results can appear in the
3D campaign source list. Completion alone does not bypass the existing source
qualification requirements. If collection is interrupted, check its status
before taking another action; do not restart the campaign or edit its files.

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

A normal launch selects `~/ytterbium_lab_simulation_ui` in each member's personal
Zeus account, with `~/venvs/atomsmltr-ui`. No local environment-file override is
needed. Test modes are for maintainers only; do not distribute `.env*.local`
files or saved test browser profiles. The historical scientific checkout is
never an installation/update target for the team UI.

Individual particle capacities are owned by
`workflow_api/individual_limits.py`. Family JSON specifications and generated
TypeScript are checked contract projections, not separate policy owners.
Run `python -m scripts.generate_individual_limits` after updating the policy;
it updates the family JSON capacity projections and generated TypeScript together.
`python -m scripts.generate_individual_limits --check` detects drift without
writing files. Scientific fields and Zeeman defaults are preserved. Storage metadata and SSH
request byte bounds are separate finite safeguards; full maximum-particle
packages are tested against them.

## Release limitations

Windows ARM in Parallels and Windows Intel/AMD are different qualification targets;
check the release report for the systems actually tested. The known 3D refinement
boundary limitation remains: some boundary designs can fail with
`refinement_design_duplicate`. Do not retry, change bounds, or edit candidate files
to bypass it. Installation/preparation checks do not certify a full scientific
optimization. Individual results currently provide verified summaries and saved
states; built-in result graphs are not available.
