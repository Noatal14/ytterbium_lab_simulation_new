# Campaign manifest compatibility

Campaign manifests are immutable scientific and operational records.  Reading
one must not silently rewrite it, add defaults, reorder keys, or upgrade it.

`workflow_api.manifest_codec` is the central read adapter.  It retains the
exact input bytes and an internal JSON object parsed from those bytes, then dispatches
the two established implicit V1 schemas by their historical `kind` values:

| Family | Historical `kind` | Adapter version |
| --- | --- | --- |
| 2D MOT | `mot_2d_s0_campaign` | `mot-2d-manifest-v1` |
| 3D MOT | `mot_3d_campaign_v2` | `mot-3d-manifest-v1` |

The `v2` text inside the historical 3D kind is part of that pre-existing kind;
it does not indicate a new codec version.  C4 introduces no V2 schema and no
new manifest fields.

Unknown kinds, a caller-requested family mismatch, and records containing
identity markers from both campaign families fail closed.  Reads are bounded,
reject final-component symlinks (including a symlink swapped in during the
read), and detect replacement or truncation.  Callers receive a defensive deep
copy of the parsed model, so nested mutation cannot alter the authenticated
document.  Typed internal failure reasons are translated at the API boundary
to the unchanged V1 error codes and messages.  Existing writer renderers remain authoritative and unchanged;
there is deliberately no generic manifest writer or read-time migration.
