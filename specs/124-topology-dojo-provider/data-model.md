# Phase 1 Data Model: Topology Dojo Topology Documentation Provider

No new persistent store. The only durable outputs are files in `workspace/output/topology-dojo/`
(spec 046 convention) and GAIT records for publish/revoke. Everything else lives for one
invocation.

## Topology Snapshot *(consumed, unchanged — the real canonical model)*

Exactly the dataclasses in `workspace/skills/comfyui-topology-viz/topology_model.py` (spec 120,
from spec 046), as produced by `_build_snapshot()` in that skill's `sources.py` for every source
adapter (CML, GNS3, containerlab, EVE-NG, Nautobot, NetBox/Infrahub, IP Fabric, Forward,
freeform). Field names below are the model's own; nothing is renamed.

| Type | Fields | Notes |
|---|---|---|
| `TopologySnapshot` | `snapshot_id: str`, `source_kind: SourceKind`, `source_label: str`, `created_at: datetime`, `devices: list[Device]`, `links: list[Link]` | `snapshot_id` is minted from the wall clock per discovery (`sources.py:57`) — provenance, never identity |
| `Device` | `hostname: str`, `role: DeviceRole`, `state: OperationalState \| None`, `interfaces: list[Interface]`, `metadata: dict` | `metadata` has already passed the shallow `sanitize_metadata` |
| `Interface` | `name: str`, `parent_hostname: str`, `ip_address: str \| None`, `state`, `metadata: dict` | `ip_address` may or may not carry a prefix length |
| `LinkEndpoint` | `hostname: str`, `interface_name: str \| None` | |
| `Link` | `link_id: str`, `endpoint_a: LinkEndpoint`, `endpoint_b: LinkEndpoint`, `state`, `label: str` | `link_id` is `link-<idx>` (positional, unstable) when the source supplied no id |

Not present in the canonical model, and therefore never assumed: `fetched_at`, per-link metadata,
VLAN, subnet, bandwidth, transport, reconciliation status.

## Link Overlay *(optional caller input)*

Data the canonical model does not carry, supplied by the calling skill when it has it (for
example `netbox-reconcile`'s categories) and keyed by the canonical `link_id`:

```python
LinkOverlay = dict[str, {"reconciliation": "DOCUMENTED|UNDOCUMENTED|MISSING|MISMATCH",
                         "vlan": str, "bandwidth": str, "transport": str}]   # every key optional
```

## Adapted Snapshot *(internal, produced by `snapshot_adapter.py`)*

The adapter validates the canonical snapshot (`TopologySnapshot.validate()` semantics: unique
hostnames, link endpoints reference declared devices, empty snapshot rejected), re-sanitizes
recursively, resolves identities, and yields plain dicts the converter consumes.

| Field | Derivation |
|---|---|
| `document_identity` | `netclaw:<source_kind>:<slug(source_label)>` — stable across discoveries |
| `title` | `NetClaw — <source_kind> — <source_label>` |
| `provenance` | `{snapshot_id, created_at}` — goes into `source.fetchedAt`, the artifact filename suffix, the GAIT record |
| `devices[]` | hostname, role, state, `meta` (recursively sanitized `Device.metadata` + platform/site if present), `site` (from metadata, when present) |
| `links[]` | `identity` (see precedence below), endpoints with interface names, `subnet` (only when both endpoint interfaces carry an `ip_address` with a prefix and they agree), overlay fields, `ambiguous: bool` |

**Recursive sanitizer** (FR-014): the union of the existing NetClaw denylist — `password`,
`secret`, `credential`, `credentials`, `api_key`, `apikey`, `token`, `running_config`,
`startup_config`, `config`, `private_key` — with `passwd` and `community`; matched case-insensitively
against every mapping key at any depth, lists included, before anything leaves the host. The
existing shallow sanitizer stays untouched in its own skills.

**Link identity precedence** (FR-004): (1) source-supplied `link_id` (a positional `link-<n>` is
treated as absent); (2) sorted `<a>:<ifA>|<b>:<ifB>` when both interface names are known;
(3) sorted `<a>|<b>#<n>`, `n` being the ordinal after sorting that pair's interface-less links by
`(label, state)` — deterministic for the input, flagged `ambiguous` because parallel unlabeled
links can swap between discoveries.

## Dojo Document *(produced by `dojo_document.build_document`)*

Minimal projection of `src/pages/model.ts` + `src/vendor/topology-ds.ts` that the converter
emits and the contract test asserts. Field names are Topology Dojo's; NetClaw adds nothing.

```json
{
  "title": "NetClaw — netbox_infrahub — dc1-fabric",
  "pages": [{
    "id": "p-0", "name": "<site or 'Topology'>", "viewBox": "0 0 1050 700",
    "nodes": [{ "id": "n-<slug>", "type": "router", "x": 0, "y": 0, "label": "<hostname>",
                "sublabel": "<platform?>", "status": "ok", "meta": {"...": "..."},
                "source": {"system": "netbox_infrahub", "kind": "device", "id": "<hostname>", "fetchedAt": "<created_at>"} }],
    "links": [{ "id": "l-<slug>", "type": "line", "from": "n-a", "to": "n-b",
                "fromLabel": "Gi1", "toLabel": "Gi1", "vlan": "10", "subnet": "10.1.1.0/30",
                "bandwidth": "1G", "showMeta": true, "color": "#2e7d32",
                "source": {"system": "netbox_infrahub", "kind": "link", "id": "<link identity>", "fetchedAt": "<created_at>"} }],
    "anchors": [], "zones": [{ "id": "z-<slug>", "nodes": ["n-a"], "label": "<site>",
                "source": {"system": "netbox_infrahub", "kind": "site", "id": "<site>"} }],
    "flowPaths": [], "policyMarkers": []
  }],
  "customNodes": [],
  "legend": { "show": true, "position": "br" }
}
```

Rules:
- `label` is the hostname verbatim; `id` is a slug (`[a-z0-9-]`) derived from it, with a numeric
  suffix on collision.
- `viewBox` grows with device count: `1050×700` up to 20 devices, then width/height scale so the
  tier rows keep the layout-guideline minimum gap.
- No `stencils`, `palette`, `layers` or `customNodes` are emitted; those are human choices in the
  editor and survive a re-sync because `upsert_by_source` patches only the fields it is given.
- This object is what is **sent** on first import. It is never what is **saved**: the artifact is
  the document read back with `get_topology` after the final validate/tidy pass (FR-008), because
  `balance_topology`/`tidy_topology` mutate server state after import.

## Source Identity

| Element | `system` | `kind` | `id` |
|---|---|---|---|
| node | `snapshot.source_kind` | `device` | hostname, lowercased |
| link | `snapshot.source_kind` | `link` | link identity (precedence above) |
| zone | `snapshot.source_kind` | `site` or `vrf` | name |

`fetchedAt` is set from `created_at` on every sync; matching ignores it (`sameSource`).

## Document Identity and lookup

| Mode | How the existing document is found |
|---|---|
| hosted | `list_topologies` → the entry whose title equals the adapted `title`; none → first import |
| local | newest `workspace/output/topology-dojo/<document_identity>-*.json` → `import_topology` (`format: "topology-dojo"`) → then sync; none → first import |

## Sync Diff *(computed locally, before the batch)*

Input: the affected page(s) fetched with `get_topology(pageIndex)` — the summary form returns
counts only and cannot feed this — and the adapted snapshot.

| Output | Derivation |
|---|---|
| `to_create[]` | intended elements whose source identity matches no fetched element of that kind |
| `to_update[]` | matched elements where any intended `set` field differs from the fetched value |
| `unchanged[]` | matched elements with no differing field (still upserted, to refresh `fetchedAt`) |
| `absent_at_source[]` | fetched elements whose `source.system == source_kind` with no intended counterpart; never removed without confirmation |
| `ambiguous_links[]` | identities that fell to precedence rule 3 |

Counters in the Sync Report come from this diff only. `edit_topology` returns `{applied,
results: [{op, id, pageIndex}]}` and drops `upsert_by_source`'s `created` flag, so the batch
result is used solely to assert `applied == len(batch)`.

## Sync Batch

| Field | Type | Notes |
|---|---|---|
| `index` | int | 0-based |
| `operations[]` | list | `{op: "upsert_by_source", kind, source, set}` — ≤ 200 for a draft, ≤ 250 and ≤ 512 KiB serialized for a workspace proposal |
| `outcome` | `applied` \| `failed` \| `skipped` | filled after the call; a failed batch stops the sync and is reported |

Ordering inside a batch: nodes first, then links, then zones, split by count at element-kind
boundaries so no link precedes an endpoint and no zone precedes a member.

## Sync Report *(returned to the conversation)*

| Field | Notes |
|---|---|
| `mode` | `hosted` or `local` |
| `document_identity`, `topology_id` / `workspace_id` | whichever applies |
| `created`, `updated`, `unchanged` | from the Sync Diff, never from batch results |
| `absent_at_source[]`, `ambiguous_links[]` | from the Sync Diff |
| `validation.problems[]`, `validation.layoutClean` | verbatim from `validate_topology` after tidy |
| `inspection` | `inspect_render` summary counts |
| `artifacts.json`, `artifacts.svg`, `artifacts.flipbook?` | absolute paths; `.json` is the read-back canonical document |
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
| network needed at run time | yes | no |
| how the server is reached | `url` + `Bearer ${TOPOLOGY_DOJO_API_KEY}` (fallback: `npx mcp-remote`, cached by the installer) | operator-supplied clone at `TOPOLOGY_DOJO_DIR` with dependencies installed; pre-staged on air-gapped hosts |

Selected by `TOPOLOGY_DOJO_MODE` (`hosted` default, `local`); the installer rewrites the server
registration for local mode.

## Share Scan *(computed immediately before publish)*

Input: the current server-side document from `get_topology` (full). Walk every string value at
any depth — node `label`/`sublabel`/`meta`/`tooltip`, link `label`/`fromLabel`/`toLabel`/`subnet`
and every other link field, zone `label`/`sublabel`/`description`, flow-path and policy-marker
text, page names and captions — and collect matches for RFC 1918, `169.254/16`, `127/8`,
`fe80::/10`, `fc00::/7` and `::1`. The list is shown to the engineer before confirmation is asked.

## Share Record *(GAIT)*

`gait_record_turn` payload: `{feature: "topology-dojo", action: "share"|"unpublish",
document_identity, topology_id, share_id, expires_at, source_kind, snapshot_id, outcome}`. Never
the document, never the URL's content, never a token.
