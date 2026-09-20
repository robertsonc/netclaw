# A Diagram That Stays True

**Draft for review — not published.** Constitution Principle XVII requires John's sign-off first.

*Contributed draft (robertsonc) with Claude · 2026-09-20*

Every topology picture NetClaw could draw until now was a snapshot: right the moment it was
rendered, and quietly wrong the moment a link flapped or a switch was racked. Spec 124 adds a
different kind of output — a Topology Dojo *document*. The canonical Topology Snapshot that the
CML, GNS3, containerlab, EVE-NG, NetBox, Nautobot, Infrahub, IP Fabric, Forward and pyATS
integrations already produce is adapted (credentials scrubbed at every depth, link identity fixed
to the interface pair so an endpoint swap is not a new link), converted, imported once, and then
re-synced in place on every later discovery with `upsert_by_source` batches keyed by a stable
source identity. The document is validated and laid out server-side, rendered once per page, and
the read-back is what NetClaw keeps under `workspace/output/topology-dojo/`. A Sync Report says
what was created, updated, unchanged, or absent at source — and nothing is ever removed without
a human saying so.

## Hosted or local, same loop

Hosted mode reaches the deployment with a user-minted, GitHub-identity-tied API key (scoped per
job: author, share, workspace) — a tool missing from `tools/list` means a missing scope, not an
outage. Local mode runs the operator's own clone over stdio with no network at all, which is the
air-gapped path; it gives up sharing and workspaces and keeps everything else. The two outward
actions — a 30-day public link and a proposal into a shared workspace — sit behind an explicit
confirmation, an internal-address scan of the exact document about to be published, and a GAIT
record. Draw.io keeps its job for `.drawio`, Confluence and Visio deliverables; this is for the
diagram that has to still be right next month.
