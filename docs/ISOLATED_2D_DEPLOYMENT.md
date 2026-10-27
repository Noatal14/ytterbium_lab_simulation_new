# Historical isolated normal 2D campaign deployment

This documents the earlier maintainer deployment. New team installations follow
[TEAM_DEPLOYMENT.md](TEAM_DEPLOYMENT.md); normal launches no longer select `_ui_test`.

`execution_checkout: "ytterbium_lab_simulation_ui_test"` explicitly binds a new
normal 2D campaign to the existing isolated UI checkout. This is deployment
policy, not an acceptance workload or a scientific configuration change.

The binding is allowed only for `mot_2d_s0_campaign`, never an arbitrary path,
TEST ONLY manifest. An explicit normal 3D child may now inherit the validated
parent binding; no historical campaign is rewritten. Unbound historical manifests retain their
original production target. The shared target validator authenticates the exact
account/root plus the normal-versus-acceptance campaign path before mutation.

The UI sends the binding when its fixed deployment configuration selects this
checkout. Preview exposes the validated binding; confirmation re-derives the
plan and includes the binding in duplicate/locking identity. Rendered PBS files
for every 2D stage, including CLI generation, use that checkout and the existing
qualified `atomsmltr-ui-test` virtual environment. The adapter requires exactly
one expected root/activation substitution and fails on template drift. Physical
parameters, numerical design, population separation and PBS resources do not
change. Pinned remote execution and stage receivers accept the closed target
registry and recheck the manifest binding; isolated normal publication also
checks it remotely before publishing.

## Existing pristine campaign repair

The user's `s0_1p35_281026` is unsubmitted at smoke with only campaign.json and
its initial PBS. Its original two-file directory must be archived before an
explicit operational re-freeze. Regenerate using the existing manifest builder
and renderer, preserving exact scientific fields and frozen inputs, binding the
isolated checkout and pinning the newly reviewed executing commit/model hash.
Do not apply this operation to campaigns with outputs, receipts or submissions.
Do not rewrite original source metadata or historical campaign provenance.

The one-time operation and its evidence live outside the product repository.
The closed scientific 3D campaign and its checkout are never migration targets.

## Qualification scope

Local regression tests cover deployment identity and rejection, creation and
confirmation, all stage renderers, CLI PBS, remote security and TEST ONLY
separation. Actual UI preparation must be verified through preview, explicit
confirmation and final remote hash agreement. This task does not authorize qsub
or certify an actual scientific campaign execution on the new target.
