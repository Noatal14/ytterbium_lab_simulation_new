# UI quick start

This is the shortest supported path for running simulations and optimization
campaigns. Normal users should use the application instead of running campaign
commands in a terminal.

## 1. Start the application

The first time you use a new checkout, install its Python and UI dependencies:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install -e ./atomsmltr
cd ui
npm ci
```

After that, start the application from the repository whenever you need it:

```bash
source .venv/bin/activate
cd ui
npm run dev
```

Open the local address printed in the terminal, normally
`http://localhost:5173`. Keep that terminal open while using the application.
Stop it with `Control-C` when you are finished.

## 2. Choose what to run

The Home page offers two kinds of work:

- **Run one simulation** for one Zeeman, 2D-MOT, or 3D-MOT run.
- **Start a campaign** for a complete 2D-MOT or 3D-MOT optimization.

Choose the input ensemble and settings, then follow the numbered steps shown by
the application. It may perform a read-only Zeus status check when you request
one, but it never submits a job or starts a simulation until it shows the exact
action and you confirm it.

Saved Zeeman states can be used by later 2D-MOT work. Saved 2D-MOT states can
be used by later 3D-MOT work. The application only lists sources it can verify
inside the current repository checkout.

## 3. Run on this computer or Zeus

Use **This computer** for small individual simulations. Local runs are limited
to 1,000 particles so they do not overwhelm a personal computer.

Use **Zeus** for campaigns and larger simulations. Before connecting:

1. Obtain an active Zeus account through the lab and Technion HPC process, and
   follow the current official account instructions.
2. Connect this computer to the Technion VPN.
3. Make sure your Zeus SSH key is installed and loaded on this computer.
4. Open **Zeus jobs**, enter your Technion username, and select
   **Connect and check status**.

For first-time SSH setup, expand **First time connecting? View setup guide** on
the Zeus jobs page. The application never requests or stores a Zeus password,
private key, or key passphrase.

## 4. Follow a run or campaign

- **Queued** or **Running** means no action is required.
- **Check status** requests a fresh status; the page does not update silently.
- **Action needed** explains what must be fixed before continuing.
- A successful scheduler result is not yet a scientific result. Continue only
  after the application validates the expected output files.
- If a submission result is uncertain, **do not submit again**. Check Zeus jobs
  first to avoid running the same work twice.

The application preserves completed campaign stages. Do not delete results or
restart a campaign because one stage failed; inspect the campaign and follow
the displayed recovery action.

## 5. When finished

Open **Results** to inspect the summary and any retained particle states. Keep
particle states only when they will be inspected or reused; a saved individual
run does not automatically become an approved campaign input.

If the application reports a problem that its guidance does not resolve, save
the exact message and the relevant campaign or run name. Do not manually edit
campaign manifests or generated job files.


## Windows (PowerShell)

Use Python 3.12 and Node.js 24 LTS with Git installed and available on PATH.
Windows ARM64 and x64 use the same source tree. Keep the checkout on a local
NTFS volume, rather than a shared Mac folder, for native locking and hard links.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -e .\atomsmltr
$env:PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
cd ui
npm.cmd ci
npm.cmd run dev
```

Open the localhost URL printed by Vite. The PYTHON setting selects the venv
without changing PowerShell execution policy or requiring activation scripts.
For backend tests, return to the repository root and run:

```powershell
.\.venv\Scripts\python.exe scripts/check_host_compatibility.py
cd ui
npm.cmd test
npm.cmd run build
npx.cmd playwright install chromium
npx.cmd playwright test --project=desktop --workers=2
npx.cmd playwright test --config=playwright.real-backend.config.ts
```

The native filesystem adapter retains handle-relative reads, exclusive locks,
no-overwrite publication and rejection of reparse points. Windows prevents some
POSIX directory-swap attacks while a publication lock is held; dedicated Windows
tests check that rejection. File contents are flushed before publication, but
Windows does not provide the POSIX directory-fsync durability guarantee. Atomic
visibility is retained; a power loss has weaker metadata durability.

Tests needing POSIX FIFOs or unavailable symlink privileges are reported as
skipped; junction rejection is tested without enabling Developer Mode. The
complete Python suite also tests POSIX receiver programs that execute on Zeus;
run that full suite on Linux/macOS. Remote submission still requires the usual
VPN, SSH keys and verified server host key on the Windows account.
