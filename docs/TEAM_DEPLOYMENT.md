# Personal-account team deployment

Use one `main` revision for the local UI/backend and the dedicated Zeus checkout.
Each member uses their own Technion username, SSH key and scheduler permissions.
The product target is **`/home/USERNAME/ytterbium_lab_simulation_ui`**, with
**`/home/USERNAME/venvs/atomsmltr-ui`**. No `_ui_test` or scientific `_new`
checkout is used by a normal launch. No shared account is required.

## Local installation

Follow [UI_QUICKSTART.md](../UI_QUICKSTART.md) literally. The three particle banks
are tracked by Git, so no manual data copy is required. Check `git status --short`
and record `git rev-parse HEAD`. A dirty or different revision is not interchangeable
with the released revision. Use `npm ci`, not `npm install`, and the committed
`requirements-team.txt`/`constraints-team.txt` on all hosts.

Keep generated results in this checkout until archived. Never delete a checkout
containing unsaved results just to update the UI. There is no automatic scientific
campaign migration between revisions.

## First connection and remote installation

1. Obtain Zeus access and permission for `zeus_combined_q`. Connect the Technion VPN.
2. Set up an SSH key for this computer using the connection screen's setup guide.
   Verify the Zeus host fingerprint through the university before accepting it.
   Test `ssh YOUR_USERNAME@zeus.technion.ac.il` in the terminal. The UI requires
   key/agent access without an interactive password prompt.
3. In that **Zeus shell**, run the following once. Replace `RELEASE_COMMIT` with
   the complete 40-character `git rev-parse HEAD` value from the local checkout.
   GitHub access to the private repository is required on Zeus too. Use GitHub's
   supported authentication; never put tokens in a command, script or clone URL.

```bash
set -euo pipefail
test ! -e "$HOME/ytterbium_lab_simulation_ui"
test ! -e "$HOME/venvs/atomsmltr-ui"
git clone --branch main https://github.com/Noatal14/ytterbium_lab_simulation_new.git "$HOME/ytterbium_lab_simulation_ui"
cd "$HOME/ytterbium_lab_simulation_ui"
test "$(git rev-parse HEAD)" = RELEASE_COMMIT
module load SPACK/apps
module load gcc/14.1.0
module load python/3.14.2
python3 -m venv "$HOME/venvs/atomsmltr-ui"
"$HOME/venvs/atomsmltr-ui/bin/python" -m pip install -r requirements-team.txt
"$HOME/venvs/atomsmltr-ui/bin/python" -m pip install --no-build-isolation -c constraints-team.txt -e ./atomsmltr
"$HOME/venvs/atomsmltr-ui/bin/python" -m pip check
git status --short
```

**Stop if any command fails.** Existing directories require inventory and a safe
update plan, not deletion or overwrite. If direct GitHub access is unavailable,
the maintainer can deliver a Git bundle of the exact released revision through
SSH; verify its commit, clean tree and bank hashes before use. This is the same
code and input data, not a second product build.

4. Return to the local UI, enter your username on **Zeus connection**, and click
   **Connect and check status**. Check the displayed path and revision against
   the local one. No job is submitted by this step.
5. For a new 2D campaign, choose the corrected 19-ring Zeeman bank, enter a new
   campaign folder, and review. Confirming creation writes local files only.
   **Review Zeus preparation** and its explicit confirmation transfer the exact
   frozen inputs, then verify remote file hashes. Submission is a separate review
   and explicit confirmation; do not click Submit merely to test installation.

## Inputs included in the release

| Directory under `data/particle_states/` | Count | Identity |
| --- | ---: | --- |
| `after_zeeman/corrected_projectant_19ring_20261005` | 1,110,091 | Corrected 19-ring source; 35 original ensembles |
| `after_2d_mot/final_ensemble_s0_1.3` | 16,883 | Optimized 2D population |
| `after_2d_mot/final_validation_s0_1.3` | 16,675 | Distinct historical validation population |

The application validates original metadata and arrays. Do not merge populations,
edit metadata, or invent provenance. A new 3D campaign still requires an approved
completed 2D handoff; these two banks support individual 3D simulations, not an
automatic new-campaign qualification.

## Deployment and recovery rules

New campaigns freeze their explicit target in `execution_checkout`. A 3D child
inherits it from its validated 2D parent. Legacy campaigns without a binding keep
their historical target; this release never rewrites them. TEST ONLY inputs,
policies and destinations remain separate.

Individual Zeus package/receipt state for the team target lives under
`data/runs/.zeus-state/`, separate from tracked source. Preserve this directory:
receipts and pending submission locks prevent duplicates after uncertain outcomes.
Legacy `.workflow` state is not moved or deleted by the product.

Before updating, inspect jobs and local workers, preserve results and receipts,
and resolve recovery needs for existing pinned campaigns. Do not pull over an
active or recoverable old campaign merely to obtain a newer UI. A revision mismatch
must block submission rather than silently rewriting provenance. Application stop
or network loss does not cancel a Zeus job. An uncertain submission must be checked,
never automatically retried.

Read the release verification report for tested platforms and remaining limitations.
This setup does not change or operate the closed scientific 3D campaign.
