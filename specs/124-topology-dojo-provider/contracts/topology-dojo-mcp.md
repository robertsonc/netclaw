# Contract: `topology-dojo-mcp` as used by `topology-dojo-diagram`

**Registered key**: `topology-dojo-mcp` in `config/openclaw.json`. Hosted form (tracked):

```json
"topology-dojo-mcp": {
  "command": "npx",
  "args": ["-y", "mcp-remote@0.14.2", "${TOPOLOGY_DOJO_MCP_URL:-https://topology-dojo.harnessed.cloud/mcp}"],
  "env": { "TOPOLOGY_DOJO_MCP_URL": "${TOPOLOGY_DOJO_MCP_URL:-https://topology-dojo.harnessed.cloud/mcp}" }
}
```

Local form (written by the installer with `openclaw mcp set`, never tracked — path is user-specific):

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
| `list_topologies` / `get_topology` | `{}` / `{topologyId, summary?: true, pageIndex?}` | find an existing NetClaw-titled draft; read `source` fields for the absent-at-source diff |
| `edit_topology` | `{topologyId, pageIndex, operations: [{op: "upsert_by_source", kind, source, set}, ...]}` | re-sync; ≤ 200 ops; atomic per call; result `{applied, results: [{op, id, pageIndex}]}` |
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
| `share_topology` | `{topologyId}` | only after `share_guard.assert_confirmed(confirmed=True)`; result `{id, url, expiresAt}`; 8 per 5 min |
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

## Converter contract (`dojo_document.py`)

```python
def build_document(snapshot: TopologySnapshot, *, title: str | None = None,
                   split_by_site: bool = False) -> dict            # Dojo Document (data-model.md)
def build_upsert_batches(snapshot: TopologySnapshot, *, page_index: int = 0,
                         max_ops: int = 200, max_bytes: int | None = None) -> list[list[dict]]
def diff_absent_at_source(document: dict, snapshot: TopologySnapshot) -> list[dict]
def slug(text: str) -> str                                        # deterministic element-id component
ROLE_TO_TYPE, STATE_TO_STATUS, RECONCILIATION_COLOR                # documented tables (research R4)
```

Guarantees asserted by `tests/topology-dojo/test_dojo_document.py`:
- node count == device count; link count == link count; labels == hostnames (SC-001)
- `build_upsert_batches(s)` twice → identical output; identities stable under endpoint swap (SC-002)
- 60/90 fixture → 1 batch at `max_ops=200`; 250/512 KiB proposal limits respected when set (SC-003)
- credential-shaped keys never appear in any emitted `meta` (FR-014)
- every emitted field name is in the recorded projection of `src/pages/model.ts` /
  `src/vendor/topology-ds.ts` (the schema drift check)

## Share guard contract (`share_guard.py`)

```python
def scan_internal_addresses(document: dict) -> list[str]   # RFC1918, link-local, loopback, ULA strings found in labels/meta
def assert_confirmed(confirmed: bool) -> None               # raises unless confirmed is True (code-level gate, FR-012)
def gait_payload(action: str, topology_id: str, share: dict | None, snapshot_id: str, outcome: str) -> dict
```
