# Original corrected 19-ring Zeeman bank

## Scope and evidence

This authorizes one existing historical input bank for new 2D campaigns. It does
**not** certify that the historical simulation used the current laboratory
specification. No original metadata, arrays, receipts or scientific campaigns
are rewritten.

The distributed source directory is
`data/particle_states/after_zeeman/corrected_projectant_19ring_20261005`.
Read-only inspection on 2026-10-28 verified all 35 seeds 3000–3034, 70 original
files, finite float64 Nx6 states, their metadata/output SHA-256 agreement,
1,110,091 total survivors, canonical embedded 19-ring arrays, and clean recorded
source revision `f042931070b58f9dac47789212e449f0552be25b` in every metadata file.

Original Git evidence, inspectable with `git show <revision>:<path>`:

| Path at f042931 | Original Git blob ID |
| --- | --- |
| `studies/generate_corrected_zeeman_ensembles.py` | `c87e20062230dfa8a5afcc5e627c7ceb791ecf65` |
| `simulations/zeeman.py` | `407f47f0b224cb1057a2d882e1996f484b102d46` |
| `config.py` | `9bcc4066d58440f171305fd08d72864bfd2ff6c0` |

The generator explicitly selects the corrected 19-ring arrays, 50,000 initial
atoms per seed, dt=40 μs, stochastic dynamics, collimation 1.5°. The original
metadata writer records those resolved parameters, state hash, Git revision and
worktree cleanliness. Each original metadata file lacks the later laboratory
identity trio. Historical settings differ from today's specification (including
the recorded start distance); neither v1 nor current full laboratory provenance
is inferred or assigned retroactively.

## Exact artifact authorization

`lab_setup/historical_zeeman_source.py` pins the SHA-256 of the newline-joined
ordered records `seed:state_sha256:metadata_sha256`:

`a8699ba2f14146c7427cda8118e688cf3b3157792be9c0b7e0d99d832eeab13c`

Normal source inspection still validates actual paths, arrays, metadata,
scientific/TEST ONLY separation and hashes. The shared new-campaign manifest
builder requires the exact historical evidence for legacy records. Changing any
original metadata or array, substituting a synthetic bank, dropping a seed or
claiming a laboratory identity fails authorization. CLI and UI share that gate.
New manifests retain legacy input records, omit the absent laboratory identity,
and explicitly record `ensemble_source.historical_evidence`. Normal campaign
validation verifies that evidence against the registry and checks original
files again. Historical manifests without this new field retain their existing
read-only/resumption interpretation; this change does not rewrite them.

The campaign's executing code/model identity is independently frozen in
`provenance`, as before. Numerical design, role/seed separation, source closures,
submission locks, confirmation and scientific validation are unchanged.

## Validation

Regression coverage: `tests/test_historical_zeeman_source.py`, existing
`tests/test_workflow_api_creation.py` and
`tests/test_mot_2d_campaign_integrity.py`. The actual distributed bank is used in
positive creation/runner-input tests. Negative cases cover unknown legacy inputs,
changed state/metadata identities, wrong/missing seeds, spoofed provenance,
forged evidence and metadata corruption. Original files remain byte-identical.

UI confirmation evidence is recorded separately after browser verification.
No Zeus job submission is required or authorized by this campaign-creation fix.
