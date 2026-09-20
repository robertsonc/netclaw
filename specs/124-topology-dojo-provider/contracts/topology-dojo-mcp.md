# Contract: `topology-dojo-mcp` as used by `topology-dojo-diagram`

**Registered key**: `topology-dojo-mcp` in `config/openclaw.json`. Hosted form (tracked) — a
user-minted Topology Dojo API key (proposal 0005) by variable reference, the Globalping shape:

```json
"topology-dojo-mcp": {
  "url": "${TOPOLOGY_DOJO_MCP_URL:-https://topology-dojo.harnessed.cloud/mcp}",
  "headers": { "Authorization": "Bearer ${TOPOLOGY_DOJO_API_KEY}" },
  "env": { "TOPOLOGY_DOJO_API_KEY": "${TOPOLOGY_DOJO_API_KEY}" }
}
```

Fallback for a deployment without `API_KEYS_ENABLED` (written by the installer when the operator
chooses it, research R2): `{"command": "npx", "args": ["-y", "mcp-remote@0.14.2", "<url>"]}`.

Registering a remote integration here is a declared classification against
`docs/ADDING-AN-MCP.md` (research R13).

Local form (written by the installer with `openclaw mcp set` from an operator-supplied clone at
`TOPOLOGY_DOJO_DIR`, never tracked — path is user-specific):

```json
"topology-dojo-mcp": { "command": "npm", "args": ["run", "--silent", "mcp"], "cwd": "<MCP_DIR>/topology-dojo" }
```

Server identity advertised by Topology Dojo: `{ name: "topology-dojo", version: "0.1.0" }`.
Source of truth for every tool below: `src/mcp/tools.ts` at commit `4dddaca`. Unknown argument
keys are stripped by the server before the handler runs; errors come back as `isError: true`
with text `Error: <message>`.

## Tools the skill uses, by phase

### Discover (once per session)

| Tool | Args | Used for |
|---|---|---|
| `describe_capabilities` | `{}` or `{types: [...]}` | confirm the built-in node/link types the converter targets still exist |
| `layout_guidelines` | `{}` | grid, spacing and margin constants the converter's tier placement honours |
| `get_authoring_guidance` | `{archetype?, workspaceId?, lastProfileRevision?, lastGuidanceRevision?}` | hosted only; ≤5 directives, applied verbatim |

### Load and sync (private draft)

| Tool | Args | Used for |
|---|---|---|
| `import_topology` | `{json: <Dojo Document>, title, format: "topology-dojo"}` | first sync — returns `{id}` |
| `list_topologies` | `{}` | hosted: find the existing draft whose title equals the stable document identity title |
| `get_topology` | `{topologyId, pageIndex}` | fetch each affected page (with element `source` fields) for the local Sync Diff; `summary: true` returns counts only and is never used for the diff |
| `get_topology` | `{topologyId}` | full read-back after the final validate/tidy pass — this is what is written to the `.json` artifact, and what the share scan walks |
| `edit_topology` | `{topologyId, pageIndex, operations: [{op: "upsert_by_source", kind, source, set}, ...]}` | re-sync; ≤ 200 ops; atomic per call; result `{applied, results: [{op, id, pageIndex}]}` — no `created` flag survives, so counters come from the local Sync Diff and the result only confirms `applied == len(operations)` |
| `remove_element` | `{topologyId, elementId, cascade: true}` | only after the engineer confirms removal of absent-at-source elements |
| `set_legend` | `{topologyId, show: true, position: "br"}` | when any link carries reconciliation status |
| `set_document_title` | `{topologyId, title}` | when the engineer renames |

`upsert_by_source.source` = `{system, kind, id, fetchedAt?}`; `set` must include `type/x/y` for a
node and `type/from/to` for a link when the element does not exist yet.

### Validate, tidy, inspect, render

| Tool | Args | Rule |
|---|---|---|
| `validate_topology` | `{topologyId}` | after every load; `{valid, problems[], layoutClean}` |
| `balance_topology` | `{topologyId, pageIndex}` | when `layoutClean` is false; then re-validate |
| `tidy_topology` | `{topologyId, pageIndex, minGap?: 24}` | fallback when balance leaves overlaps |
| `layout_topology` | `{topologyId, pageIndex, algorithm: "hierarchical", direction: "TB"}` | only on explicit "re-layout" — moves every node |
| `inspect_render` | `{topologyId, pageIndex}` | before render; summary counts go in the Sync Report |
| `render_svg` | `{topologyId, pageIndex}` | once per page per sync; string result written to `.svg`; 2 MiB cap |
| `export_flipbook` | `{topologyId}` | only for multi-page documents; 6 MiB cap |

### Share (hosted only, confirmation-gated)

| Tool | Args | Rule |
|---|---|---|
| `share_topology` | `{topologyId}` | only after `get_topology` (full) → `share_guard.scan_internal_addresses(document)` → engineer sees the list → `share_guard.assert_confirmed(confirmed=True)`; result `{id, url, expiresAt}`; 8 per 5 min |
| `list_shares` | `{}` | `{shares: [{id, title, createdAt, expiresAt}]}` |
| `unpublish_topology` | `{shareId}` | 12-character id from the `/v/<id>` URL |

### Workspace (hosted only, proposal-only)

| Tool | Args | Rule |
|---|---|---|
| `list_workspaces` | `{}` | skip entries with `migrated: false` and tell the engineer why |
| `get_workspace_manifest` | `{workspaceId}` | remember `revision`, page ids, `operationSchemaRevision` |
| `describe_workspace_operations` | `{}` | once per `operationSchemaRevision`; limits `{maxOperations: 250, maxSerializedBytes: 524288}` |
| `get_workspace_changes` | `{workspaceId, sinceRevision, limit?, detail?: "summary"}` | before proposing, and after a conflict |
| `get_workspace_elements` | `{workspaceId, pageId, elementIds?, kinds?, cursor?, limit?}` | only the affected page |
| `propose_workspace_changes` | `{workspaceId, baseRevision, operationId, title, rationale, operations}` | default write path |
| `apply_workspace_changes` | same minus title/rationale | only when the engineer states a live page lease is granted |
| `create_checkpoint` / `list_checkpoints` | `{workspaceId, name}` / `{workspaceId}` | before a large proposal, when asked |

## Adapter contract (`snapshot_adapter.py`)

```python
FORBIDDEN_KEYS: frozenset[str]   # union of the existing NetClaw denylist + {"passwd", "community"}
def sanitize_recursive(value: Any) -> Any                     # walks mappings and lists at any depth
def link_identity(link: dict) -> tuple[str, bool]             # (identity, ambiguous) per the precedence rule
def document_identity(source_kind: str, source_label: str) -> str   # "netclaw:<kind>:<slug>"
def adapt(snapshot: TopologySnapshot | dict, overlay: LinkOverlay | None = None) -> AdaptedSnapshot
```

`adapt` accepts either the canonical dataclasses or their `dataclasses.asdict` form so the tests
can feed JSON serialized from the real `_build_snapshot()`.

Guarantees asserted by `tests/topology-dojo/test_snapshot_adapter.py`:
- every fixture is a verbatim serialization of the real model (`link_id`, `endpoint_a`,
  `endpoint_b`, `interface_name`, `source_label`, `created_at`); no invented field is read
- `link-<n>` ids are treated as absent; a real `link_id` wins over the interface pair
- endpoint swap does not change identity; interface-less parallel links are flagged `ambiguous`
- overlay fields land on the right link by `link_id`; missing overlay is not an error
- nested secrets (`{"snmp": {"community": "..."}}`, lists of dicts) are removed; the union
  denylist is enforced

## Converter contract (`dojo_document.py`)

```python
def build_document(adapted: AdaptedSnapshot, *, split_by_site: bool = False) -> dict   # Dojo Document (data-model.md)
def build_upsert_batches(adapted: AdaptedSnapshot, *, page_index: int = 0,
                         max_ops: int = 200, max_bytes: int | None = None) -> list[list[dict]]
def diff_page(fetched_page: dict, adapted: AdaptedSnapshot) -> SyncDiff   # to_create / to_update / unchanged / absent_at_source / ambiguous_links
def slug(text: str) -> str                                        # deterministic element-id component
ROLE_TO_TYPE, STATE_TO_STATUS, RECONCILIATION_COLOR                # documented tables (research R4)
```

Guarantees asserted by `tests/topology-dojo/test_dojo_document.py`:
- node count == device count; link count == link count; labels == hostnames (SC-001)
- `build_upsert_batches(a)` twice → identical output; identities stable under endpoint swap (SC-002)
- 60/90 fixture → 1 batch at `max_ops=200`; 250/512 KiB proposal limits respected when set (SC-003)
- `diff_page` against a fixture page: unchanged fixture → all `unchanged`; one added device → one
  `to_create`; one removed device → one `absent_at_source`; a changed status → one `to_update`
- every emitted field name is in the recorded projection of `src/pages/model.ts` /
  `src/vendor/topology-ds.ts` (the schema drift check)

## Share guard contract (`share_guard.py`)

```python
def scan_internal_addresses(document: dict) -> list[str]   # recursive walk of the fetched document: every string at any depth, incl. link subnet/fromLabel/toLabel
def assert_confirmed(confirmed: bool) -> None               # raises unless confirmed is True (code-level gate, FR-012)
def gait_payload(action: str, document_identity: str, topology_id: str, share: dict | None,
                 snapshot_id: str, outcome: str) -> dict
```

Guarantees asserted by `tests/topology-dojo/test_share_guard.py`:
- a link with `subnet: "10.1.1.0/30"` and nothing else internal is reported (the case a
  label/meta-only scan misses); `169.254.1.1`, `127.0.0.1`, `fe80::1`, `fd00::/8` are reported;
  `203.0.113.1` and `2001:db8::1` are not
- `assert_confirmed(False)` raises; the GAIT payload contains no URL body and no token
