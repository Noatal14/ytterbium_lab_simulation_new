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
