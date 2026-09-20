# Phase 0 Research: Topology Dojo Topology Documentation Provider

Ground truth: `robertsonc/topology-dojo` at commit `4dddaca` (branch `main`) and NetClaw at
`ad6a4a8`. Every claim below was read from source in this session; items marked **inferred** or
**unverified** were not executed against a live deployment.

## R1: One more diagram skill, not a provider abstraction (satisfies Clarification Q1, FR-017/018)

NetClaw's draw.io integration is not an abstraction: there is no `config/openclaw.json` entry, no
shared schema, and no adapter module. `drawio-diagram/SKILL.md` is invoked ad hoc through
`scripts/mcp-call.py` spawning `npx -y @drawio/mcp`, and the topology skills hand off to it in prose
(`pyats-topology/SKILL.md:147,184-186`, `netbox-reconcile/SKILL.md:395`,
`document-generation/SKILL.md:122`). Twenty-three SKILL.md files mention draw.io; each is a
natural-language contract.

The repo's one worked example of an operator-selectable backend, spec 070 (ITSM provider
abstraction), required a Constitution amendment (1.2.0 → 1.3.0) before implementation. Framing
Topology Dojo the same way would add governance cost and an abstraction that no caller would use —
the callers are skills that emit prose handoffs, not code that calls an interface.

**Decision**: add `topology-dojo-diagram` as a peer of `drawio-diagram`, give SOUL.md the routing
boundary that today does not exist even between draw.io and the 3D tools
(`docs/ADDING-AN-MCP.md:384-385` calls this out), and add reciprocal handoff lines to the files
that already name draw.io. Spec 121's pattern — one entry point, provenance reported in the
response — is reused for the mode (hosted/local) rather than for provider selection.

## R2: Hosted authentication is a user-minted Topology Dojo API key (satisfies FR-010/011)

At commit `4dddaca`, `worker/index.ts:50-57` wrapped the whole Worker in Cloudflare's
`workers-oauth-provider` with `/mcp` as the protected route, GitHub as the upstream identity
provider, and no static-credential path: `scripts/smoke.mjs:378-386` asserts an unauthenticated
`POST /mcp` returns 401, and every non-MCP `/api/*` route authenticates with a browser session
cookie. An unattended agent had only the browser OAuth hop (via a bridge such as `mcp-remote`).

Topology Dojo proposal 0005 (`docs/proposals/0005-api-key-auth.md`, robertsonc/topology-dojo#247)
closes that gap upstream: a signed-in user mints a scoped, optionally expiring `tdk_…` key at
`/keys`, and the provider's `resolveExternalToken` hook resolves it to the same `{id, login,
name}` props a grant produces, plus `auth: "api_key"` and `scopes`. Drafts, workspaces, quotas
and share ownership are therefore the user's own. It is gated by the deployment's
`API_KEYS_ENABLED` (staging on; production after the upstream UAT-MCP-04).

**Decision**: the registration is the Globalping shape and nothing else — no bridge, no OAuth
token cache on the NetClaw host, no headless recipe:

```json
"topology-dojo-mcp": {
  "url": "${TOPOLOGY_DOJO_MCP_URL:-https://topology-dojo.harnessed.cloud/mcp}",
  "headers": { "Authorization": "Bearer ${TOPOLOGY_DOJO_API_KEY}" },
  "env": { "TOPOLOGY_DOJO_API_KEY": "${TOPOLOGY_DOJO_API_KEY}" }
}
```

Scopes map onto the stories: none beyond the implicit `author` for US1/US2, `share` for US3,
`workspace` for US4; `live-data` is never needed by this skill. A key without a scope simply
does not see that tool group in `tools/list`, which is how the skill detects a scope gap (FR-011).
The `mcp-remote` OAuth bridge that an earlier revision of this research proposed was dropped on
2026-09-20 (owner decision): one credential path, no npx package, no `~/.mcp-auth` state.

## R3: Local stdio mode exists, is unauthenticated, and is in-memory only (satisfies FR-010/015, US5)

`npm run mcp` → `tsx src/mcp/server.ts` (`package.json:14`) registers the 34 core tools with a
`StdioServerTransport` and no auth (`src/mcp/server.ts:39-46`). Share, workspace, checkpoint and
authoring-preference tools are registered only when the Worker supplies their dependencies
(`src/mcp/tools.ts:1447,1583,1784,1874-1896`), so they are absent locally. Drafts live in the
process (`docs/USER_GUIDE.md:118-141`, "Treat as temporary. Export or retrieve the JSON before
stopping the process"). The renderer loads the vendored engine with `createRequire`
(`src/server/render.ts:24-26`), so no `npm run build` is needed; `tsx` is a devDependency, so
`npm ci` (not `--omit=dev`) is required. Node 22 and npm 10 are present on this host.

**Decision**: the installer's local branch takes an operator-supplied clone at
`TOPOLOGY_DOJO_DIR`, verifies `node` ≥ 18, `package.json` and an installed `node_modules`, and
registers via `openclaw mcp set` with `command: npm`, `args: ["run","--silent","mcp"]`,
`cwd: <clone>` — the documented client config (`src/mcp/README.md:19-29`). It does **not** clone
or run `npm ci` itself while the upstream repository is unlicensed (R9); once a license lands, the
Percepxion/RADKit clone-at-install path (`verify-inventory-counts.py:100-104`,
`install-steps.sh:1476-1484`) is the obvious follow-up. Two situations are kept apart: "no GitHub
identity" (connected host, operator clones and runs `npm ci` by hand) and "air-gapped" (the clone
is pre-staged with `node_modules` already populated on a connected machine of the same OS/arch —
`tsx`/`esbuild` ship native binaries — and the installer makes no network call). The repo's
tracked `config/openclaw.json` keeps the hosted (bridge) form because the clone path is
user-specific. FR-008 (always write the read-back JSON) is what makes local mode safe: NetClaw,
not the server, is the store of record.

## R4: The input is the existing canonical Topology Snapshot, consumed through an explicit adapter (satisfies FR-001..005)

The canonical model is `workspace/skills/comfyui-topology-viz/topology_model.py` (spec 120,
ported from spec 046's three.js skill and trimmed again in spec 122):

- `TopologySnapshot(snapshot_id, source_kind: SourceKind, source_label, created_at, devices, links)`
- `Device(hostname, role: DeviceRole, state: OperationalState | None, interfaces: list[Interface], metadata)`
- `Interface(name, parent_hostname, ip_address, state, metadata)`
- `LinkEndpoint(hostname, interface_name)`; `Link(link_id, endpoint_a, endpoint_b, state, label)`

Every source adapter in `sources.py` (CML, GNS3, containerlab, EVE-NG, Nautobot, NetBox/Infrahub,
IP Fabric, Forward, freeform) produces exactly these types via `_build_snapshot()`
(`sources.py:138-149`). Note what is **not** there: no `fetched_at` (it is `created_at`), no
per-link metadata, no VLAN/subnet/bandwidth, no reconciliation status, and `link_id` falls back to
the positional `link-<idx>` when the source gives no id (`sources.py:130`). The `pyats-topology`
skill's richer model (`SKILL.md:114-142`: subnets, routing adjacencies, FHRP) is prose, and the
NetBox reconciliation categories live in `netbox-reconcile`, outside the dataclasses.

Topology Dojo's document contract (`src/pages/model.ts:25-89`, `src/vendor/topology-ds.ts`)
has a home for everything the canonical model does carry, and more: `NodeConfig.meta`,
`NodeConfig.status` (`ok|warn|down|maintenance|unknown`), `LinkConfig.fromLabel/toLabel`
(interface names), `LinkConfig.vlan/subnet/bandwidth/transport/showMeta`, `ZoneConfig`, and
`source` on every sourced element.

**Decision**: two modules in `workspace/skills/topology-dojo-diagram/`, both stdlib only.
`snapshot_adapter.py` imports nothing from other skills (the repo's copy-and-trim convention) but
is tested against JSON serialized from the real `_build_snapshot()` output so the field names
cannot drift silently; it accepts the canonical dataclasses (or their `dataclasses.asdict`
form) plus an optional `LinkOverlay` keyed by `link_id` for reconciliation status, VLAN,
bandwidth and transport, and derives a link `subnet` only when both endpoint interfaces carry an
`ip_address` with a prefix length. `dojo_document.py` then converts the adapted snapshot into (a)
a native document for `import_topology` and (b) `edit_topology` batches of `upsert_by_source`
operations for re-sync. Both are deterministic functions of their input so they can be tested
offline with fixtures. The LLM never hand-writes 200 `add_node` calls.

Role mapping (spec 121 roles → Dojo built-in node types, `src/api/builtins.ts`):

| Snapshot role | Dojo type | Notes |
|---|---|---|
| `router` | `router` | |
| `switch` | `switch` | `switchEnterprise` when metadata marks it as core/distribution |
| `firewall` | `firewall` | |
| `load_balancer` | `loadbalancer` | |
| `client` | `host` | |
| `unclassified` | `server` | labeled, never an unlabeled shape (spec 121 FR-002 guarantee) |
| extended: `ap` / `wlc` / `sdwan-edge` / `cloud` | `ap` / `wlc` / `ec` / `cloud` | only when the source supplies them; not part of the base enum |

State mapping: `healthy→ok`, `degraded→warn`, `down→down`, `unknown→unknown`, absent → omitted.
Reconciliation colour: `DOCUMENTED→#2e7d32`, `UNDOCUMENTED→#f9a825`, `MISSING→#c62828`,
`MISMATCH→#ef6c00`; when any link carries a status, `legend.show = true`.

Initial placement: role tiers (firewall/router row, switch row, host row) on the layout
guideline grid, then `layout_topology hierarchical` is *not* called by default — the tiered
placement plus `balance_topology` produces stable positions across syncs, whereas a fresh layout
would move every node on every update. `layout_topology` is offered when the engineer asks for a
re-layout.

## R5: `upsert_by_source` keys on (system, kind, id) per element kind per page (satisfies FR-004, US2)

`src/api/source.ts:12-31` defines `SourceRef {system, kind, id, fetchedAt?}`; `sameSource`
ignores `fetchedAt`. `src/api/edit.ts:217-264` searches the target page's collection of that
element kind and patches on a match, otherwise creates (requiring `type/x/y` for a node,
`type/from/to` for a link). Anchors cannot carry a source. `upsert_by_source` is a valid
`edit_topology` operation (`src/mcp/tools.ts:1355-1369`), so a whole sync is one batch and one
rate-limit unit.

**Decision** — element identity scheme:

- node: `{system: <snapshot.source_kind>, kind: "device", id: <hostname lowercased>}`
- link, in precedence order:
  1. `{system, kind: "link", id: <link_id>}` when the source supplied one — NetBox/Nautobot cable
     ids, CML/GNS3/containerlab link ids. A positional `link-<n>` from `sources.py:130` is treated
     as absent.
  2. `{system, kind: "link", id: "<a>:<ifA>|<b>:<ifB>"}` when both interface names are known,
     endpoints sorted so A–B and B–A agree.
  3. `{system, kind: "link", id: "<a>|<b>#<n>"}` otherwise, where `n` is the ordinal after
     sorting that device pair's interface-less links by `(label, state)`. This is deterministic
     for a given input but cannot be stable across discoveries for truly parallel, unlabeled
     links; the adapter flags those links and the Sync Report lists them.
- zone (site/VRF): `{system: <source_kind>, kind: "site"|"vrf", id: <name>}`

Element ids are derived from the same strings (`n-<slug>`, `l-<slug>`) so the first sync's
`import_topology` document and later `upsert_by_source` batches agree. Matching is per page, so
the skill always passes `pageIndex` and single-page documents are the default; multi-page
(per-site) documents put the site name in the page name and sync each page separately.

**Decision** — document identity. `snapshot_id` is minted from the wall clock on every discovery
(`sources.py:57-58`), so a title that embeds it can never be found again. The document identity
is `netclaw:<source_kind>:<slug(source_label)>`, carried as the document title
(`NetClaw — <source_kind> — <source_label>`) and as the artifact filename stem. Hosted mode finds
the existing draft with `list_topologies` by that title; local mode re-imports the newest
`<identity>-*.json` artifact before syncing. `snapshot_id` and `created_at` are provenance only:
they go into `source.fetchedAt`, the artifact filename suffix, and the GAIT record.

**Decision** — diff and counters (updated 2026-09-20 for Topology Dojo proposal 0006). The skill
fetches the sourced-element listing — `get_topology(topologyId, sources: true, system:
<source_kind>)` for a draft (`{id, kind, source, label}` per page, no geometry), or
`get_workspace_elements(sourcedOnly: true)` for a workspace page — and the converter diffs it
against the adapted snapshot **before** sending the batch: elements absent at source are reported
(removal is a separate, engineer-confirmed `remove_element` batch — US2 scenario 3) and
updated / unchanged are decided locally from the intended `set` versus the listed element (label
and source only, since the listing carries no geometry; a geometry-only change counts as
unchanged). `created` comes from the batch itself: `edit_topology` now returns `created:
true|false` per `upsert_by_source` op, and a workspace proposal's `summary.byType` reports
`element.add` vs `element.patch`. `get_topology(summary: true)` still returns counts only and is
never used for the diff.

## R6: Sharing is an outward publication and is gated (satisfies FR-012, Clarification Q3)

`share_topology` writes a KV snapshot readable by anyone at `${PUBLIC_BASE_URL}/v/<id>` for 30
days (`worker/share.ts:99-128`, `SHARE_TTL_SECONDS`), rate-limited 8 per 300 s per user, and the
tool's own description says "Do not publish internal addresses, credentials, or other sensitive
content". Re-publishing mints a new id; nothing renews an old one. Revocation is
`unpublish_topology(shareId)` or `DELETE /api/topology/<id>` as the owner.

**Decision**: same shape as spec 122's credit-spending gate — explicit conversational "yes" in the
same turn sequence, a code-level `confirmed: true` argument on the skill helper that assembles the
call, and a `gait_record_turn` entry (topology id, share id, expiry, outcome). The pre-publish scan
runs against the **current server-side document**, fetched with `get_topology` immediately before
`share_topology`, and walks it recursively — every string value at any depth, so first-class link
fields (`subnet`, `fromLabel`/`toLabel`, `label`, `sublabel`), node `meta`, zone descriptions and
flow-path/policy-marker text are all covered — flagging RFC 1918, link-local (`169.254/16`,
`fe80::/10`), loopback and unique-local (`fc00::/7`) addresses. Scanning only the converter's
labels/meta would miss `subnet: "10.1.1.0/30"`. The default deliverable is the local SVG + JSON;
the URL is only produced on request.

## R7: Workspace writes are proposals of `element.upsert` operations (satisfies FR-013, US4)

`src/mcp/README.md:237-244`: agents are "Suggest only" by default; only the browser grants a
ten-minute, page-scoped lease; `apply_workspace_changes` without one fails. Batches carry
`baseRevision` and a client `operationId`; the coordinator rebases disjoint fields and rejects
same-field overlap as a conflict. Limits: 250 operations / 512 KiB per batch, ≤20 unresolved
proposals. Legacy drafts (`migrated: false` in `list_workspaces`) reject agent workspace reads
until the owner opens them in the browser; `worker/mcp.ts:296-301` forbids agent-triggered
migration.

At commit `4dddaca` the workspace vocabulary (`src/workspace/model.ts`) had nine stored operation
types and no source-keyed write. Topology Dojo proposal 0006 (robertsonc/topology-dojo#248) adds
`element.upsert` as an **input** operation (`operationSchemaRevision` 2): the coordinator
normalizes each one, against the current document, into `element.add` or `element.patch` by
`(system, kind, id)` before validation, conflict detection and storage. A requested `element.id`
is honoured on create; the kind's create-required fields are the same table `upsert_by_source`
uses; anchors cannot carry a source.

**Decision**: the skill's workspace path is manifest (stop if `operationSchemaRevision < 2`) →
`get_workspace_changes` since last revision → `get_workspace_elements` with `sourcedOnly: true`
for the affected page (the diff input) → `propose_workspace_changes` whose operations are all
`element.upsert`, with a title and rationale → read `summary.byType` for add vs patch counts.
Direct `apply_workspace_changes` is used only when the engineer states the lease is live. NetClaw
never resolves workspace element ids itself.

## R8: Rendering artifacts are SVG and flipbook HTML; PNG is browser-only (satisfies FR-007/008)

`render_svg` returns a standalone SVG string (20–300 KB typical, rejected above 2 MiB);
`export_flipbook` returns self-playing HTML (6 MiB cap); `inspect_render` returns a compact JSON
QA report and is the recommended pre-render step (`src/mcp/README.md:118-140,335-360`).
`docs/USER_GUIDE.md:641,1259`: "PNG is browser-only". draw.io XML export is browser-only too
(`src/editor/drawio.ts`, wired in `src/main.ts:1084-1087`; no MCP tool).

**Decision**: artifacts are `workspace/output/topology-dojo/<UTC-ts>-<slug>.json` and `.svg`
(spec 046's timestamped, never-overwritten convention), plus `.flipbook.html` when the document has
more than one page. `browser-viz-verify` screenshots the SVG when a raster is required, exactly as
it does for three.js output. `TOOLS.md:254-255` records that the draw.io CLI is unusable headlessly
on the maintainer's host, which is why spec 121 built a Pillow renderer; Topology Dojo's headless
renderer needs only Node.

## R9: Topology Dojo has no license file (satisfies FR-021, Clarification Q4)

No `LICENSE` at the repo root or anywhere in the tree; `package.json` has `"private": true` and no
`license` field. NetClaw is Apache-2.0.

**Decision**: nothing is vendored, and the installer does not clone either. Local mode registers
an operator-supplied clone (`TOPOLOGY_DOJO_DIR`) and verifies it; automatic clone-at-install
(precedents: RADKit `install-steps.sh:1476-1484`, Percepxion) is a follow-up gated on the upstream
license. The PR description asks the Topology Dojo maintainer to add one (Apache-2.0 matches
NetClaw and the vendored MCP servers NetClaw already tracks); until then README and SKILL.md
describe local mode as "bring your own clone".

## R10: Batch limits, rate limits and size caps (satisfies FR-005, Edge Cases)

| Surface | Limit | Source |
|---|---|---|
| `edit_topology` operations | 1–200 per call | `src/mcp/tools.ts:1376` |
| workspace batch | 250 ops / 512 KiB | `describe_workspace_operations`, `docs/USER_GUIDE.md:1081-1093` |
| mutating tools (hosted) | 120 per 60 s per user | `src/mcp/rate-limit.ts`, README §Rate limits |
| `share_topology` (hosted) | 8 per 300 s per user | same |
| `render_svg` response | 2 MiB | `MAX_SVG_EXPORT_BYTES` |
| `export_flipbook` response | 6 MiB | `MAX_HTML_EXPORT_BYTES` |

Rate-limit errors are machine-parseable: `rate limited (<bucket>: <n> per <window>s). Retry after
<seconds>s.` The skill reports the interval and does not retry on its own (a write is not
idempotent from the agent's point of view until the batch result is read).

## R11: Offline contract testing without the Topology Dojo code (satisfies FR-020, SC-005)

Topology Dojo tests its MCP handlers by importing `createTools`/`parseToolArgs` directly
(`src/mcp/tools.test.ts:23-26`); there is no JSON-RPC-level e2e test in that repo. NetClaw cannot
import that TypeScript without a clone, and R9 rules out vendoring.

**Decision**: a shell suite `tests/topology-dojo/run-tests.sh` (Globalping's structure —
registration assertions, SKILL.md content assertions, `set -uo pipefail`, exit codes captured
directly) plus stdlib `unittest` files for the converter under `tests/topology-dojo/`. The
converter's output shape is asserted against a hand-copied minimal schema of the document
contract (field names and required keys from `src/pages/model.ts` and `src/vendor/topology-ds.ts`,
recorded in `contracts/topology-dojo-mcp.md`). An opt-in live-local check, gated on
`TOPOLOGY_DOJO_DIR` pointing at a prepared clone, drives `npm run mcp` through
`scripts/mcp-call.py` for `import_topology → validate_topology → render_svg` on a fixture. It is
declared under `live` in `tests/contract-suites.json`, never in the default path.

## R13: A registered bearer-token remote, declared against `docs/ADDING-AN-MCP.md`'s table

`docs/ADDING-AN-MCP.md:30-42` says Remote/OAuth integrations get **no** `config/openclaw.json`
entry and are recorded in `EXTERNAL_INTEGRATIONS` with reason `remote/OAuth`. Repo practice is
different for bearer-token remotes: `globalping-mcp`, `meraki-mcp`, `topolograph-mcp`,
`thousandeyes-official-mcp` and `zscaler-mcp` are registered `url` entries.

**Decision**: register `topology-dojo-mcp` as a `url` + bearer entry, and say so. Reasons: (1) it
is the same shape as those five; (2) one server key must also serve local mode, and only a
registered key can be rewritten by `openclaw mcp set` at install time; (3) the HUD node,
`check-server-startup.py` and the contract suite's registration assertions need a registered key.
The cost: the integration counts as a config entry rather than an external one (which is what
moves the computed MCP count from 172 to 173). Recorded in spec.md (FR-019, Assumptions), in
TOOLS.md's section for the server, and in the PR.

## R12: What this feature deliberately does not do

- Does not add a `TopologyProvider` implementation inside Topology Dojo (the extension point
  `src/connect/types.ts`, ADR `docs/decisions/0002-second-provider-juniper-mist.md`). That would
  expose a NetBox/pyATS credential to every authenticated MCP session on the deployment
  (`src/mcp/README.md` "Blast radius"). NetClaw stays a client.
- Does not add a draw.io export hop; that is a Topology Dojo follow-up (`export_drawio` over MCP).
- Does not change any existing skill's behaviour; every edit to an existing SKILL.md is an
  additive handoff line (Constitution XV).
- Does not wire an iN2N member; the "five more artifacts" in `docs/ADDING-AN-MCP.md` are out of
  scope and documented as such.
