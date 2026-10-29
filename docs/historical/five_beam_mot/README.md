# Historical five-beam MOT screening evidence

Recovered from the parent of commit `bded565fca0815ade4fe5b263ced21e841191716`, which retired this candidate. These records describe early inputs and a 100-ms endpoint, not the final 2026-10-20 validation.

The design has five 556-nm beams: two counterpropagating pairs in the yz plane at 45 degrees to z, and one unpaired beam opposing gravity. The four paired directions also have coaxial 399-nm annuli. The magnetic strong axis is the gravity axis. Historical code uses gravity along -x; interpret directions relative to gravity when comparing with other coordinate conventions.

A local screen and a boundary check used 600 shared input atoms. The boundary check selected 202/600 (33.7%) at 100 ms; the paired full-shell control gave 491/600 (81.8%). Five recoil repetitions at the selected point gave a mean of 31.23% and sample standard deviation of 1.70 percentage points. A larger historical run gave 4,706/15,840 (29.71%). The latter two results are documented in the recovered rationale; the JSON files preserve the two grid summaries.

The rationale initially recommended further five-beam optimization. That recommendation was superseded when the two-beam single-pass design (now Cross MOT) was selected. The project owner's final design decision was to prioritize Cross MOT as the simpler alternative, since this limited screen did not suggest enough additional performance to justify the five-beam design's greater optical complexity. This was a budget/design decision, not a matched final validation proving Cross MOT superiority.

The recovered rationale is an archival document: its old relative figure links and prospective recommendations are retained as historical text, not current instructions. Exact retired geometry implementation: `git show bded565^:lab_setup/laser_setup_3d.py`; profile: `git show bded565^:config.py`. Do not run retired submitters for a new campaign.
