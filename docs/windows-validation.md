# Native Windows compatibility validation — 2026-10-17

Implementation and test fixes were authored on macOS in `codex/ui-review-fixes`.
Commits were transferred using local Git bundles and fast-forwarded into a
separate checkout on the Windows C: volume. No project code was authored in the
Windows checkout. The existing Mac simulation data was not modified.

## Environment

- Host: MacBook Air M4, 16 GB RAM, macOS 26.6.2.
- Guest: Windows 11 Pro ARM64, build 26300, Parallels 27.0.3,
  4 virtual CPUs and 6 GB RAM.
- Windows tools: Python 3.12.10 ARM64, Node 24.20.0, npm 11.19.0,
  Git 2.55.0.windows.5. macOS checks used Python 3.12 and Node 24.19.0.
- Code revision: `c7c0f943c3980fa98ac11630c9861594f3c95390`.
- Windows checkout: `C:\Users\noatal\work\ui-review-fixes`.

## Results

| Check | macOS | Windows ARM64 |
| --- | --- | --- |
| `python scripts/check_host_compatibility.py` | 792 passed, 6 skipped | 756 passed, 42 skipped |
| UI unit tests | 706 passed | 706 passed |
| Node launcher tests | 3 passed | 3 passed |
| Desktop Chromium browser scenarios | 24 passed | 24 covered successfully across the initial run and corrected Zeeman rerun |
| Browser against real Python HTTP handler | 1 passed | 1 passed |
| ESLint, checked formatting, TypeScript, production build | Passed | Passed |
| Real Zeeman, 2D-MOT and 3D-MOT integrations | Passed | Passed |
| Seeded serial versus two spawn workers | Matched in all three families | Matched in all three families |

The host suite covers local execution, records and results, source discovery,
HTTP/session/CSRF boundaries, 2D/3D campaign preparation, mocked pinned SSH,
configuration and scientific helpers. Windows-specific tests cover junction
rejection, independent positioned reads, file-lock exclusion between processes,
no-overwrite publication and protection of locked publication directories.

The additional full macOS sweep completed 2,243 passing tests and two skips.
One source-inspection assertion observed a file being edited while that process
was running; it passed on rerun in a fresh process. The final common host suite
and focused changed-module checks also passed in fresh processes. A second full
18-minute sweep was not repeated after the final targeted fixes.

Windows skips comprise 20 fixtures requiring unavailable symlink privileges,
two POSIX FIFO cases, and 20 POSIX directory-replacement cases. The latter have
five native Windows tests that assert the attempted replacement is denied and
the run remains intact. macOS skips comprise the Windows junction test and the
five native Windows publication tests. Developer Mode was not enabled.

## Numerical and source parity

Each real smoke case integrated two particles with seed 713 and a few time
steps, both serially and with two spawned processes. These checks exercise the
real numerical engines and worker serialization; they are not production-size
physics convergence or performance studies.

Maximum absolute differences between the macOS and Windows final state arrays:

| Family | Maximum absolute difference |
| --- | --- |
| Zeeman | 2.22e-16 |
| 2D-MOT | 6.18e-13 |
| 3D-MOT | 6.87e-16 |

All 78 files in the combined individual-run runtime ledgers had matching raw
bytes on both hosts. The aggregate SHA-256 was:

`99bb431582549f4c2945578a855bcd75e399f81025641591a1635298fb4afbf2`

The pre-existing Windows checkout retained old CRLF conversions despite a
checkout refresh. Its clean tracked text files were restored from Git blobs,
and the index normalization cache was refreshed without creating content
changes. `.gitattributes` now enforces LF for text files; vendored batch bytes
are preserved. Fresh clones and future Git updates should retain the policy.

## Scope and operational limits

### Real Windows UI chain, 2026-10-17

Visible Microsoft Edge, controlled by Playwright inside Windows, exercised the
real UI and Python API without mocked routes. Every stage was reviewed, created,
started locally, and displayed `Verified results are ready`.

| Stage | Input particles | Output | Runtime | Workers |
| --- | --- | --- | --- | --- |
| Zeeman | 200 | 120 survivors | 19.485 s | 4 |
| 2D-MOT | 120 retained Zeeman survivors | 4 survivors | 882.563 s | 4 |
| 3D-MOT, angled donut | 4 retained 2D-MOT survivors | 0 usable / 0 residence-qualified captured | 82.594 s | 2 |

The run IDs were `zeeman-2339c599c4ab007cc2837409`,
`mot2d-7810e02c9c2218e72834a71a`, and
`mot3d-770a2f91b5f7f8874835f318`. All three catalog records were
`succeeded`, `complete_verified`, and local, with no Zeus job IDs. Both downstream
input manifests referenced the preceding run's actual `results/states.npy`;
the SHA-256 values matched the files on disk. States were retained at every stage.
Zero capture in this small 3D sample is a numerical outcome, not an execution
failure. This checks the chain and does not establish scientific convergence.

The real HTTP path exposed two 3D review defects: the adapter rejected the UI's
explicit `npools` field, and nested immutable capture settings were not JSON
serializable. Both were fixed on macOS and transferred with Git to Windows.
The API, planning, and creation regression tests passed on both systems
(14 tests each), including legacy requests and JSON round trips for both
geometry families. The successful 3D run used revision
`b4a1e5b4f8935944073fe774ab3781d1d2b5f8d5`; upstream runs used `9cc871d`.

### Independent macOS chain comparison, 2026-10-17

The same production creation services and local worker pools ran an independent
chain on macOS ARM64 at revision `6831654`. Each stage consumed the preceding
Mac stage's states; the downloaded Windows states were comparison references
only. Their sizes and SHA-256 values matched the verified Windows artifact
registry. All resolved scientific configuration fields, seeds, worker counts,
and selected particle identities matched. Run/source identifiers, timestamps,
input fingerprints, Git provenance, and runtime were allowed to differ.

| Stage | Matching outcome on both hosts | Mac runtime | Windows runtime |
| --- | --- | --- | --- |
| Zeeman | 120 survivors / 200 initial | 12.061 s | 19.485 s |
| 2D-MOT | 4 survivors / 120 input | 463.371 s | 882.563 s |
| 3D-MOT, angled donut | 0 usable and 0 residence-qualified captured / 4 input | 23.365 s | 82.594 s |

All scientific scalar metrics and selection hashes matched exactly. Retained
survivor arrays matched with the preselected comparison tolerances
`rtol=1e-9`, `atol=1e-10`; they were not byte-identical.

| Retained state arrays | Maximum position difference (m) | Maximum velocity difference (m/s) |
| --- | --- | --- |
| Zeeman, 120 x 6 | 1.6793e-15 | 1.3792e-11 |
| 2D-MOT, 4 x 6 | 2.1643e-14 | 4.2138e-12 |

Both 3D survivor arrays had shape `(0, 6)`, so that stage compares the input
selection and capture metrics, not nonempty final survivor coordinates. Full
trajectories were not retained by the application. These are functional and
numerical repeatability checks, not convergence or controlled speed benchmarks.

Mac run IDs: `zeeman-67875ae54c5c712c3bea0e37`,
`mot2d-04e0a605e5033dd68c230943`, and
`mot3d-47ef814fb13d1bcf02e5a395`. All three completed with verified results.

### Single-pass 3D-MOT comparison, 2026-10-17

Four saved survivors from each host's preceding 2D-MOT run were selected with
selection seed 42, simulation seed 42, and two workers. Windows used the real
UI in visible Edge; macOS used the production creation and local worker services.
Both hosts used revision `2d17cfe`, the canonical Single-pass defaults, and
identical resolved science, derived geometry, and selected particle identities.

Parameters: green s0 30, detuning -25 gamma, waist 0.01 m; blue s0 0.75,
waist 0.01 m, detuning anchor -2.034161875 gamma; magnetic gradient 2.5 G/cm;
crossing angle 45 degrees and requested z offset -0.05 m. The resolved blue
detuning was -2 gamma and effective slowing offset -0.061 m. The solver was
RK4StHybridCustom, dt 1e-5 s, t_max 0.1 s, with gravity and stochastic sampling.

Both runs completed with verified results: 4 inputs, 0 usable at simulation end,
and 0 residence-qualified captures. Runtime was 10.125 s on macOS and 15.031 s
on Windows; this was not a controlled performance benchmark. Run IDs:
`mot3d-7c57d5354a63c2ec6e915c12` (Mac) and
`mot3d-e3cd03864630f94426968cfc` (Windows).

Because both retained survivor arrays were empty, an additional unchanged-engine
repeat retained diagnostic trajectories for all four inputs on each host.
Captured arrays matched each host's original result exactly. The four trajectory
shapes were `(6, 452)`, `(6, 687)`, `(6, 489)`, and `(6, 627)`. Time arrays were
identical, and all position/velocity samples matched with `rtol=1e-9`, `atol=1e-10`.
Across all samples, the maximum absolute position difference was 2.1306e-13 m
and the maximum velocity difference was 8.2892e-11 m/s. No scientific equations
or numerical settings were changed.

### Remaining scope

- Native Windows ARM64 was exercised locally. Windows x64 and macOS CI jobs
  were added, but the new GitHub jobs have not been dispatched in this task.
- The UI and its Python host run natively; WSL is not required. Keep working
  copies on local NTFS. See `UI_QUICKSTART.md` for PowerShell setup.
- The Windows adapter uses directory-relative native handles, reparse-point
  rejection, native exclusive locks and atomic publication. File contents are
  flushed, but POSIX directory-fsync power-loss durability is unavailable on
  Windows. Atomic visibility is preserved.
- POSIX receiver programs still execute on Zeus. No actual SSH connection,
  scheduler submission, or lab hardware operation was performed. Remote flows
  were tested with closed transport doubles and the real HTTP/browser boundary.
- No scientific equations or numerical-policy values were changed.
