# Phase 1 Data Model: Topology Dojo Topology Documentation Provider

No new persistent store. The only durable outputs are files in `workspace/output/topology-dojo/`
(spec 046 convention) and GAIT records for publish/revoke. Everything else lives for one
invocation.

## Topology Snapshot *(consumed, unchanged)*

The spec 046/120/121/122 shape, as produced by every source adapter in
`workspace/skills/comfyui-topology-viz/sources.py` and trimmed in spec 122's `topology_model.py`.

| Field | Type | Notes |
|---|---|---|
| `snapshot_id` | str | carried into the Sync Report and GAIT record |
| `source_kind` | str | `cml`, `gns3`, `containerlab`, `eve_ng`, `nautobot`, `netbox`, `ip_fabric`, `forward`, `pyats`, `freeform` — becomes `source.system` |
| `fetched_at` | ISO 8601 | becomes `source.fetchedAt` |
| `devices[]` | Device | `hostname` (unique), `role`, `state?`, `metadata?` (sanitized), `interfaces?[]` |
| `links[]` | Link | `a`, `b` (hostnames), `a_interface?`, `b_interface?`, `label?`, `metadata?` (`vlan`, `subnet`, `bandwidth`, `transport`, `reconciliation`) |

Validation (converter, before any tool call): unique hostnames; link endpoints reference declared
devices; empty snapshot rejected with a named error; `sanitize_metadata` strips credential-shaped
keys (`password`, `passwd`, `secret`, `token`, `api_key`, `apikey`, `community`, `private_key`).

## Dojo Document *(produced)*

Minimal projection of `src/pages/model.ts` + `src/vendor/topology-ds.ts` that the converter
emits and the contract test asserts. Field names are Topology Dojo's; NetClaw adds nothing.

```json
{
  "title": "NetClaw — <source_kind> — <snapshot_id>",
  "pages": [{
    "id": "p-0", "name": "<site or 'Topology'>", "viewBox": "0 0 1050 700",
    "nodes": [{ "id": "n-<slug>", "type": "router", "x": 0, "y": 0, "label": "<hostname>",
                "sublabel": "<platform?>", "status": "ok", "meta": {"...": "..."},
                "source": {"system": "netbox", "kind": "device", "id": "<hostname>", "fetchedAt": "..."} }],
    "links": [{ "id": "l-<slug>", "type": "line", "from": "n-a", "to": "n-b",
                "fromLabel": "Gi1", "toLabel": "Gi1", "vlan": "10", "subnet": "10.1.1.0/30",
                "bandwidth": "1G", "showMeta": true, "color": "#2e7d32",
                "source": {"system": "netbox", "kind": "link", "id": "a:gi1|b:gi1", "fetchedAt": "..."} }],
    "anchors": [], "zones": [{ "id": "z-<slug>", "nodes": ["n-a"], "label": "<site>",
                "source": {"system": "netbox", "kind": "site", "id": "<site>"} }],
    "flowPaths": [], "policyMarkers": []
  }],
  "customNodes": [],
  "legend": { "show": true, "position": "br" }
}
```

Rules:
- `label` is the hostname verbatim; `id` is a slug (`[a-z0-9-]`) derived from it, with a numeric
  suffix on collision.
- Link endpoints are sorted so `a`/`b` order at the source never changes the link identity.
- `viewBox` grows with device count: `1050×700` up to 20 devices, then width/height scale so the
  tier rows keep the layout-guideline minimum gap.
- No `stencils`, `palette`, `layers` or `customNodes` are emitted; those are human choices in the
  editor and survive a re-sync because `upsert_by_source` patches only the fields it is given.

## Source Identity

| Element | `system` | `kind` | `id` |
|---|---|---|---|
| node | snapshot `source_kind` | `device` | hostname, lowercased |
| link | snapshot `source_kind` | `link` | `<a>:<ifA>|<b>:<ifB>` (sorted) or `<a>|<b>#<ordinal>` |
| zone | snapshot `source_kind` | `site` or `vrf` | name |

`fetchedAt` is refreshed on every sync; matching ignores it (`sameSource`).

## Sync Batch

| Field | Type | Notes |
|---|---|---|
| `index` | int | 0-based |
| `operations[]` | list | `{op: "upsert_by_source", kind, source, set}` — ≤ 200 for a draft, ≤ 250 and ≤ 512 KiB serialized for a workspace proposal |
| `outcome` | `applied` \| `failed` \| `skipped` | filled after the call; a failed batch stops the sync and is reported |

Ordering inside a batch: zones after their member nodes; links after both endpoint nodes; a
snapshot never needs cross-batch references because the converter closes each batch at a node
boundary and starts links only once every endpoint has been emitted (nodes first, then links, then
zones, split by count).

## Sync Report *(returned to the conversation)*

| Field | Notes |
|---|---|
| `mode` | `hosted` or `local` |
| `topology_id` / `workspace_id` | whichever applies |
| `created`, `updated`, `unchanged` | element counts from the batch results |
| `absent_at_source[]` | element ids + labels present in the document with a matching `source.system` but missing from the snapshot |
| `validation.problems[]`, `validation.layoutClean` | verbatim from `validate_topology` after tidy |
| `inspection` | `inspect_render` summary counts |
| `artifacts.json`, `artifacts.svg`, `artifacts.flipbook?` | absolute paths |
| `share?` | `{url, id, expires_at}` only after a confirmed publish |
| `proposal?` | `{proposal_id, base_revision}` for the workspace path |

## Connection Mode

| Capability | hosted | local |
|---|---|---|
| draft authoring, validate, tidy, inspect, render, flipbook | yes | yes |
| durable private drafts across sessions | yes (per GitHub identity) | no — NetClaw's JSON artifact is the record |
| share / list_shares / unpublish | yes (confirmation-gated) | no |
| workspaces, proposals, checkpoints | yes | no |
| authoring guidance / preferences | yes (when enabled on the deployment) | no |
| rate limits | 120 writes/min, 8 shares/5 min | none (size caps only) |

Selected by `TOPOLOGY_DOJO_MODE` (`hosted` default, `local`); the installer rewrites the server
registration for local mode.

## Share Record *(GAIT)*

`gait_record_turn` payload: `{feature: "topology-dojo", action: "share"|"unpublish", topology_id,
share_id, expires_at, source_kind, snapshot_id, outcome}`. Never the document, never the URL's
content, never a token.
