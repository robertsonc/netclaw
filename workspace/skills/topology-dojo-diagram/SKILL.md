---
name: topology-dojo-diagram
description: "Turn a discovered network topology (CML, GNS3, containerlab, EVE-NG, NetBox, Nautobot, Infrahub, IP Fabric, Forward, pyATS) into a validated, re-syncable Topology Dojo document — a private draft that is re-synced in place on every discovery, rendered once to SVG, and, only after explicit confirmation, shared by public link or proposed into a shared workspace. Use when the operator wants a topology diagram that stays current, can be validated, or must be shared or co-edited. Use drawio-diagram for .drawio/Confluence/Visio deliverables."
license: Apache-2.0
user-invocable: true
metadata:
  openclaw:
    requires:
      env: ["TOPOLOGY_DOJO_API_KEY"]
---

# Topology Dojo Diagram Skill

**Version**: 1.0.0
**Feature**: 124-topology-dojo-provider
**Status**: Active
**Server**: `topology-dojo-mcp` (hosted: remote HTTP + API key; local: operator-supplied clone over stdio)

## Overview

Topology Dojo is a topology *document* system, not a picture generator. A document has typed
nodes and links, pages, a validator, a layout engine, a legend, source identity on every element
and (hosted) sharing and multi-user workspaces. This skill feeds it the canonical Topology
Snapshot that every NetClaw topology source already produces (the same model
`threejs-network-viz`, `comfyui-topology-viz` and `worldlabs-topology-viz` consume) and keeps
the resulting document in sync with the network over time.

Three stdlib-only helpers ship beside this file:

| Module | Purpose |
|---|---|
| `snapshot_adapter.py` | canonical snapshot → adapted snapshot: recursive credential scrub, stable link identity, stable document identity, optional reconciliation overlay, subnet derivation |
| `dojo_document.py` | adapted snapshot → Dojo document (`import_topology`), `upsert_by_source` batches (`edit_topology`), `element.upsert` batches (`propose_workspace_changes`), the Sync Diff, and `count_created` |
| `share_guard.py` | internal-address scan of a fetched document, the code-level confirmation gate, and the GAIT payload for publish/revoke |

Everything the helpers do is deterministic and offline. Every network call is an MCP tool call
on `topology-dojo-mcp`.

## Prerequisites and connection modes

`TOPOLOGY_DOJO_MODE` selects the mode (`hosted` is the default, `local` is the other value).

### Hosted mode (default)

- **A Topology Dojo API key** in `.env` as `TOPOLOGY_DOJO_API_KEY`. Sign in to the deployment
  with GitHub and mint the key at `<deployment>/keys` (for the default deployment,
  `https://topology-dojo.harnessed.cloud/keys`). Revoke it on the same page. The key is tied to
  the GitHub identity that minted it, so drafts, shares and workspaces stay with that account.
- The registration in `config/openclaw.json` is `url` + `Authorization: Bearer
  ${TOPOLOGY_DOJO_API_KEY}` by variable reference. Never paste the key into chat, a file, a
  Sync Report or a GAIT record; a key looks like `tdk_…` and must never appear in a tracked file.
- **Scopes per story.** The `author` scope is implicit on every key. Add `share` only if the
  operator will publish links (US3), `workspace` only for proposals (US4). A tool missing from
  `tools/list` (for example no `share_topology`) means the key lacks that scope, not that the
  server is down: report the gap and point at `/keys`, do not retry the call.
- The deployment must have `API_KEYS_ENABLED`. A deployment without it cannot be used in hosted
  mode; there is no other credential path. `TOPOLOGY_DOJO_MCP_URL` overrides the endpoint for a
  self-hosted deployment.
- Rate limits: 120 write calls per minute, 8 shares per 5 minutes. When the server answers with
  a rate-limit error, report the "retry after" it states to the operator. Never loop on it.

### Local mode

The operator pre-stages a clone of `robertsonc/topology-dojo` with its dependencies installed
at `TOPOLOGY_DOJO_DIR` (Node.js 18+, `npm ci` run by the operator, never by the installer) and
sets `TOPOLOGY_DOJO_MODE=local`. The installer then registers `npm run --silent mcp` in that
directory over stdio. No network is needed at run time, so this is the air-gapped path.

| Capability | hosted | local mode |
|---|---|---|
| draft authoring, validate, tidy, inspect, render, flipbook | yes | yes |
| durable drafts across sessions | yes | no — drafts are process-lifetime; the JSON artifact is the record |
| share, list_shares, unpublish | yes (confirmation-gated) | no sharing — not available in local mode |
| workspaces, proposals, checkpoints | yes | no |
| authoring guidance / preferences | yes | no |
| rate limits | 120 writes/min, 8 shares/5 min | none (size caps only) |

In local mode, every session starts by re-importing the newest prior artifact of the same
identity — `identity --output-dir workspace/output/topology-dojo` prints it as `latest_artifact`
(the newest `<identity_stem>.*.json`, whatever snapshot id it was written under) — with
`import_topology` (`format: "topology-dojo"`), then re-syncing against it. If the operator asks to share in local
mode, refuse and offer the `.svg` and `.json` artifacts instead.

## Rules that never bend

1. **Page scope is always explicit.** Every page-scoped call — `edit_topology`,
   `balance_topology`, `tidy_topology`, `inspect_render`, `render_svg`, and the sourced-element
   listing `get_topology({sources: true, pageIndex})` — names its `pageIndex` (0 for a
   single-page document); never rely on a server default. The two whole-document reads are the
   opposite: the final read-back that becomes the `.json` artifact (Workflow 1 step 9) and the
   pre-share scan (Workflow 3 step 2) call `get_topology({topologyId})` and MUST omit
   `pageIndex`, because a page-scoped read-back drops the other pages from the artifact and a
   page-scoped scan misses internal addresses on them.
2. **Render once per page per sync.** Render only after the final validate/tidy pass; never
   render after every edit. `render_svg` output is capped at 2 MiB, `export_flipbook` at 6 MiB.
3. **The artifact is the read-back document.** The `.json` written to
   `workspace/output/topology-dojo/` is the result of `get_topology` (full) after the last
   edit, never the converter's pre-import object.
4. **Locate documents by stable identity, never by snapshot id.** `document_identity` is
   `netclaw:<source_kind>:<slug(source_label)>` and does not change between discoveries; the
   snapshot id changes every run. Artifacts are named
   `<identity_stem>.<snapshot slug>.<UTC timestamp>[.<page>].<ext>`: the stem is the identity
   alone, the snapshot id is provenance inside the name, and the lookup pattern
   `<identity_stem>.*.json` finds every prior run and no sibling identity.
5. **Source ids are exact and element ids are collision-proof.** `source.id` is the canonical
   hostname or link identity exactly as the source reports it (`R1` and `r1` are two devices).
   Element ids are `<prefix>-<slug>-<6-hex hash of the exact original>`, so `edge_1` and
   `edge-1` never share an id; the converter refuses to emit a page whose ids collide.
6. **One page at a time.** A split-by-site document is synced page by page: listing, diff and
   batches are all scoped to one page (`pages` prints the plan; `--site`/`--unassigned` scope
   the converter). A link whose endpoints sit on different pages is drawn on no page and is
   reported as a cross-site link, never silently dropped.
7. **Nothing leaves the account without a confirmation.** Sharing and workspace proposals are
   the only outward actions, both gated below. Removal of elements is gated too.
8. **Credentials never enter a document.** The adapter strips `password`, `passwd`, `secret`,
   `credential(s)`, `api_key`, `apikey`, `token`, `running_config`, `startup_config`, `config`,
   `private_key` and `community` at any depth, including inside stringified nested metadata.

## Workflow 1 — Document a discovered topology (first sync)

1. **Discover.** Obtain the canonical Topology Snapshot from the source skill the operator
   named (CML, GNS3, containerlab, EVE-NG, NetBox, Nautobot, Infrahub, IP Fabric, Forward,
   pyATS). Do not re-discover if a snapshot from this session already exists.
2. **Adapt and convert** (offline):

   ```bash
   SKILL=workspace/skills/topology-dojo-diagram
   python3 $SKILL/dojo_document.py identity --snapshot snapshot.json --output-dir workspace/output/topology-dojo
   #   → document_identity, title, identity_stem, artifact_glob, artifact_json, latest_artifact
   python3 $SKILL/dojo_document.py pages --snapshot snapshot.json [--split-by-site]
   #   → the page plan {index, id, name, site} and the cross_site_links a split cannot draw
   python3 $SKILL/dojo_document.py document --snapshot snapshot.json [--overlay overlay.json] [--split-by-site] > document.json
   ```

   `--overlay` takes reconciliation rows keyed by `link_id` (from `netbox-reconcile` or
   similar); `--split-by-site` makes one page per `metadata.site` plus an `Unassigned` page
   when some devices carry no site. Tell the operator about every cross-site link up front.
3. **Consult the server once per session.** `describe_capabilities` confirms the built-in node
   and link types the converter targets still exist; `layout_guidelines` gives the grid and
   spacing constants the converter honours; hosted only, `get_authoring_guidance` returns at most
   five directives, applied verbatim to the document before import.
4. **Import.** `import_topology({json: <document>, title: <identity title>, format: "topology-dojo"})`
   returns `{id}`. Remember the id for the session.
5. **Validate.** `validate_topology({topologyId})` → `{valid, problems[], layoutClean}`. Fix
   problems by editing the element the problem names (`edit_topology`, `update_element`), never by
   dropping it silently.
6. **Tidy.** If `layoutClean` is false, `balance_topology({topologyId, pageIndex})`, then
   re-validate; if overlaps remain, `tidy_topology({topologyId, pageIndex, minGap: 24})`.
   `layout_topology` moves every node and is only used on an explicit "re-layout" request.
7. **Inspect.** `inspect_render({topologyId, pageIndex})`; its summary counts go into the Sync
   Report.
8. **Render once per page.** `render_svg({topologyId, pageIndex})` for each page.
9. **Read back and persist.** `get_topology({topologyId})` — the full document, no
   `pageIndex` — and write it to `workspace/output/topology-dojo/<artifact_json>` (the
   `identity` output: `<identity_stem>.<snapshot slug>.<UTC timestamp>.json`) and each render to
   the same name with `.<page>.svg`. Timestamped, never overwritten.
10. **Sync Report** to the operator: mode, document identity, topology id, pages, nodes and links
    created, validation verdict, artifact paths.

## Workflow 2 — Update an existing diagram (re-sync without duplicates)

1. **Locate the document by stable identity.** Hosted: `list_topologies` and match the title
   equal to the identity title. Local mode: re-import `latest_artifact` from
   `identity --output-dir …` first (the newest `<identity_stem>.*.json`; the snapshot id in the
   name is irrelevant). If nothing matches, this is a first sync (Workflow 1).
2. **Take the page plan** from `pages --snapshot snapshot.json [--split-by-site]` (the same
   `--split-by-site` the document was built with) and run steps 3–5 **once per page**. A
   single-page document has one iteration with `--page-index 0` and no scope flag; a
   split-by-site document has one per site (`--site <name>`) plus `--unassigned` when the plan
   lists it.
3. **Fetch that page's sourced-element listing**, not the full document:
   `get_topology({topologyId, sources: true, system: <source_kind>, pageIndex})` returns
   `{id, kind, source, label}` rows for the elements this source owns on that page and nothing
   else.
4. **Diff locally** (offline), with the same scope as the listing:

   ```bash
   python3 $SKILL/dojo_document.py diff --snapshot snapshot.json --listing listing.json --page-index <i> [--site <name> | --unassigned] [--overlay overlay.json]
   ```

   The Sync Diff has `to_create`, `to_update`, `unchanged`, `absent_at_source` and
   `ambiguous_links`. Elements owned by other systems are ignored. Diffing one page's listing
   without its scope reports every other page's elements as `to_create` and would duplicate
   them on this page; the CLI refuses a multi-page listing without `--page-index`.
5. **Upsert in batches**, scoped the same way:

   ```bash
   python3 $SKILL/dojo_document.py upsert-batches --snapshot snapshot.json --page-index <i> [--site <name> | --unassigned] [--overlay overlay.json]
   ```

   One `edit_topology({topologyId, pageIndex, operations: <batch>})` call per batch of at most
   200 `upsert_by_source` operations. Each operation's `source` is `{system, kind, id, fetchedAt}`
   and its `set` carries `type/x/y` (node) or `type/from/to` (link) so creation succeeds when
   nothing matches. Batches close at node boundaries, so no link ever precedes its endpoints.
   Every result row carries `created`; the created count is `count_created(results)` and must
   equal `len(to_create)`. Rows from a current deployment also carry `changed` (false when the
   upsert was a logical no-op apart from `source.fetchedAt`): then `summarize_results(results)`
   gives exact updated and unchanged counts. When a row lacks `changed`, take updated and
   unchanged from the diff instead. Absent-at-source and ambiguous links always come from the
   diff; results cannot express them.
6. **Absent at source.** Elements in the listing that the new snapshot no longer contains are
   reported as *absent at source*. They are never removed without confirmation. On an explicit
   "yes, remove them", `remove_element({topologyId, elementId, cascade: true})` per element.
7. **Ambiguous links.** Two or more interface-less links between the same pair fall back to an
   ordinal identity and are listed under `ambiguous_links`; the report says so and asks for
   interface names at source.
8. Validate → tidy → inspect → render once per page → full read back (no `pageIndex`) →
   persist → Sync Report with created / updated / unchanged / absent / ambiguous counts per page
   and the cross-site links that are on no page.

### Reconciliation overlay and legend

With an overlay each link carries `reconciliation` and is coloured: `DOCUMENTED` green,
`UNDOCUMENTED` amber, `MISSING` red, `MISMATCH` orange. When any link carries a status, call
`set_legend({topologyId, show: true, position: "br"})` so the colours are explained on the page.

## Workflow 3 — Share, list, revoke (hosted only)

A share link is **public for 30 days** to anyone holding the URL. This is the one outward
publication this skill can make, so it is gated twice.

1. Only when the operator asks to share. Confirm the key has `share_topology` in `tools/list`.
2. `get_topology({topologyId})` — the full document, no `pageIndex` — **immediately before**
   sharing, then scan it:

   ```bash
   python3 $SKILL/share_guard.py scan --document readback.json
   ```

   `scan_internal_addresses` walks every string at every depth (labels, `subnet`, `fromLabel`,
   `toLabel`, metadata) for RFC 1918, CGNAT, loopback, link-local, ULA and IPv6 loopback
   addresses. Show the operator the full list of internal address findings.
3. Gate. The operator answers "yes" to the explicit question *"publish `<title>` publicly for 30
   days, including the N internal addresses listed?"* and the code path calls
   `assert_confirmed(confirmed=True)`. Without both, no call is made.
4. `share_topology({topologyId})` → `{id, url, expiresAt}`. Report the URL and expiry.
5. Record it: `gait_record_turn` with `gait_payload("share", document_identity, topology_id,
   share, snapshot_id, "published")`. The payload carries the share id and expiry, never the URL
   body or any token.
6. `list_shares({})` lists the account's links; `unpublish_topology({shareId})` revokes one
   (the 12-character id from the `/v/<id>` URL) and is GAIT-recorded with action `unpublish`.
7. Re-publishing an already shared document mints a **new URL**; the old link does not renew and
   keeps its own expiry. Say so before sharing again.
8. Rate limit: 8 shares per 5 minutes. Report the "retry after" the server states; do not retry.

## Workflow 4 — Propose changes to a shared workspace (hosted only)

Workspaces are multi-user documents with revisions, leases and proposals. This skill only ever
**proposes**; humans in the browser review and apply.

1. `list_workspaces({})`. Skip entries with `migrated: false` and tell the operator that legacy
   drafts must be migrated in the browser first.
2. `get_workspace_manifest({workspaceId})` → remember `revision`, the page ids and
   `operationSchemaRevision`. Stop if `operationSchemaRevision < 2`: the deployment predates
   `element.upsert` and cannot take idempotent proposals.
3. `describe_workspace_operations({})` once per `operationSchemaRevision` (cache it), to confirm
   `element.upsert` and the limits (`maxOperations: 250`, `maxSerializedBytes: 524288`). The
   converter closes a batch at 250 operations or 480 KiB of serialized operations, leaving
   headroom under the 512 KiB limit for the request envelope and the server's own
   normalization, which re-checks the size after it has expanded the operations.
4. `get_workspace_changes({workspaceId, sinceRevision, detail: "summary"})` to see what moved
   since the last sync, then, **for each affected page**,
   `get_workspace_elements({workspaceId, pageId, sourcedOnly: true})`, following `nextCursor`
   until exhausted. Diff each page's listing locally with the same `diff` subcommand and the
   same page scope (`--site`/`--unassigned` for a split-by-site document).
5. Build that page's batches, with the same scope:

   ```bash
   python3 $SKILL/dojo_document.py workspace-batches --snapshot snapshot.json --page-id <pageId> [--site <name> | --unassigned] [--overlay overlay.json]
   ```

   Every operation is `{type: "element.upsert", pageId, kind: <plural>, source, element}`.
6. `propose_workspace_changes({workspaceId, baseRevision, operationId, title, rationale,
   operations})` — the default write path. `operationId` is deterministic per
   (workspace, base revision, batch index) so a retried call cannot double-apply. Report the
   proposal id and the add/patch counts from `proposal.summary.byType`.
7. `apply_workspace_changes` is used only when the operator states a live page lease is granted
   for this page and asks for a direct apply. Otherwise it is a proposal, always.
8. On a conflict (the base revision moved), re-read `get_workspace_changes` from the old base,
   re-diff, and retry once with the new revision. A conflict target of the form
   `page/<pageId>/source/<kind>/<system>/<kind>/<id>` means another revision bound that source
   identity while the proposal waited; the re-diff turns the affected upserts into patches and
   nothing is duplicated. A second conflict is reported, not retried.
9. `create_checkpoint({workspaceId, name})` before a large proposal when the operator asks;
   `list_checkpoints` to show them.

## Safety and audit

- Read-only against the network: this skill never touches devices; it consumes snapshots.
- GAIT: every publish and revoke is recorded via `gait_record_turn`; sync runs record document
  identity, topology id, snapshot id and the counts.
- DefenseClaw: allow the tools listed in the workflows; leave `delete_topology` blocked unless
  the operator asks for a deletion explicitly.
- The `.json` artifact is the durable record in both modes; in local mode it is the only one.

## Boundaries — which diagram skill

| Want… | Use |
|---|---|
| A validated document that is re-synced on every discovery, shareable by link, or co-edited in a workspace | **this skill** |
| A `.drawio` file, or a diagram bound for Confluence or Visio | `drawio-diagram` (and `msgraph-visio` to publish it) |
| A navigable 3D scene for exploration or presentation | `threejs-network-viz`, `ue5-network-viz`, `blender-3d-viz`, `worldlabs-topology-viz` |
| A stylized single still image | `comfyui-topology-viz` |
| A hierarchy or mind map (OSPF areas, BGP AS tree) | `markmap-viz` |
| A protocol state machine, sequence, rack or packet diagram | `uml-diagram` |
| A report that embeds the diagram | `document-generation` / `network-report-documents` embed the `.svg` artifact and never redraw it |
| Render QA of the `.svg` | `browser-viz-verify` |

## Tests

`tests/topology-dojo/run-tests.sh` runs the offline suite (adapter, converter, share guard,
registration shape and this file's safety language) with no network and no account. With
`TOPOLOGY_DOJO_DIR` set to a prepared clone, `live_local.sh` drives the local stdio server with
network access forced off.
