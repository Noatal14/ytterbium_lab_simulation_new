# UI limited release notes

Scope: reviewed UI/product separation candidate based on `2ee6919`. Publication
remains a separate coordinated step; these notes do not authorize merge or push.

- Existing campaign recovery, validation and submission safeguards are retained.
  One-off v2 candidate ordering and O16 donor authorization are retired; their
  original policy/tests and historical run evidence remain preserved.
- **3D refinement limitation:** a legal boundary candidate can stop with
  `refinement_design_duplicate`. Preserve the existing results and stop there;
  no automatic alternate candidate or resubmission is supported. Do not promise
  autonomous completion for every valid campaign. The refinement algorithm is
  unchanged, as explicitly requested by the user.
- Windows ARM in Parallels has actual native test evidence. Windows Intel/AMD
  qualification remains pending; do not label it tested.
- New physical Zeus lifecycle qualification of this separation candidate and the
  browser-to-real-backend integration pass remain separate from prior historical
  campaign results and hermetic receiver checks. Consult the review handoff for
  exact commit identity, results and remaining gaps.

Any team release must disclose these restrictions. This is a limited scope, not
an unrestricted campaign-readiness claim. Historical scientific data and campaign
results are unchanged.
