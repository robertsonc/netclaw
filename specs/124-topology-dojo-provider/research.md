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

## R2: Hosted authentication is OAuth 2.1 + GitHub, with no API-key path (satisfies FR-010/011)

`worker/index.ts:50-57` wraps the whole Worker in Cloudflare's `workers-oauth-provider` with
`apiRoute: '/mcp'`, `/authorize`, `/token`, `/register` (dynamic client registration) and
discovery at `/.well-known/oauth-authorization-server`. `worker/default-handler.ts:473-550`
redirects to GitHub (`scope=read:user`) and completes authorization with the GitHub numeric uid as
the tenancy key. `scripts/smoke.mjs:378-386` asserts an unauthenticated `POST /mcp` returns 401.
`src/mcp/README.md:41-47`: "no token to paste". Every non-MCP `/api/*` route authenticates with a
browser session cookie, not a bearer token, so a REST fallback does not avoid the OAuth dance.

**Consequence**: NetClaw's `url` + `headers.Authorization: Bearer ${VAR}` entry shape (Globalping,
ThousandEyes, Topolograph) cannot be used as-is; there is no static bearer to reference.

**Decision**: register a stdio entry that runs the `mcp-remote` bridge:

```json
"topology-dojo-mcp": {
  "command": "npx",
  "args": ["-y", "mcp-remote@0.14.2", "${TOPOLOGY_DOJO_MCP_URL:-https://topology-dojo.harnessed.cloud/mcp}"],
  "env": { "TOPOLOGY_DOJO_MCP_URL": "${TOPOLOGY_DOJO_MCP_URL:-https://topology-dojo.harnessed.cloud/mcp}" }
}
```

`mcp-remote` (MIT, 0.14.2 verified on npm in this session) performs discovery, dynamic client
registration, PKCE, opens the browser once, and caches tokens under `~/.mcp-auth/`. NetClaw already
ships it for IP Fabric (`scripts/ipfabric-enable.sh:190`) and ThousandEyes
(`install-steps.sh:1452-1457`), and `scripts/check-package-references.py:58` names it as a
package that passes the registry check. Pin the version: an `@latest` bridge is the one moving part
between NetClaw and a remote OAuth server.

**Unverified**: whether OpenClaw's gateway MCP client performs OAuth DCR natively for a bare
`url` entry. If it does, the entry can become `{"url": "..."}` with no bridge; the skill does not
change. Task T-research-1 in tasks.md checks this once, on a real gateway, before implementation.

**Headless hosts**: the bridge's callback lands on `http://localhost:<port>/oauth/callback`. On a
server with no browser, the operator runs the login once through an SSH port-forward
(`ssh -L <port>:localhost:<port> host`, `npx mcp-remote <url> <port>`), or performs the first run on
a workstation and treats `~/.mcp-auth` as a credential store (0700). Both paths are documented in
the SKILL.md and installer output; neither is automated.

## R3: Local stdio mode exists, is unauthenticated, and is in-memory only (satisfies FR-010/015, US5)

`npm run mcp` → `tsx src/mcp/server.ts` (`package.json:14`) registers the 34 core tools with a
`StdioServerTransport` and no auth (`src/mcp/server.ts:39-46`). Share, workspace, checkpoint and
authoring-preference tools are registered only when the Worker supplies their dependencies
(`src/mcp/tools.ts:1447,1583,1784,1874-1896`), so they are absent locally. Drafts live in the
process (`docs/USER_GUIDE.md:118-141`, "Treat as temporary. Export or retrieve the JSON before
stopping the process"). The renderer loads the vendored engine with `createRequire`
(`src/server/render.ts:24-26`), so no `npm run build` is needed; `tsx` is a devDependency, so
`npm ci` (not `--omit=dev`) is required. Node 22 and npm 10 are present on this host.

**Decision**: the installer's local branch clones `https://github.com/robertsonc/topology-dojo`
into `$MCP_DIR/topology-dojo`, runs `npm ci`, and registers via `openclaw mcp set` with
`command: npm`, `args: ["run","--silent","mcp"]`, `cwd: <clone>` — the documented client config
(`src/mcp/README.md:19-29`). The repo's tracked `config/openclaw.json` keeps the hosted (bridge)
form because the clone path is user-specific (the Percepxion precedent in
`verify-inventory-counts.py:100-104`). FR-008 (always write the JSON) is what makes local mode
safe: NetClaw, not the server, is the store of record.

## R4: The input is the existing Topology Snapshot; the converter is pure Python (satisfies FR-001..005)

Every NetClaw topology source since spec 046 normalizes to `{"devices": [...], "links": [...]}`
(`workspace/skills/comfyui-topology-viz/sources.py:1-9` lists CML, GNS3, containerlab, EVE-NG,
Nautobot, NetBox/Infrahub, IP Fabric, Forward, freeform). Spec 122 ports a trimmed
`topology_model.py` (Device: hostname/role/state; Link: a/b/label; `sanitize_metadata`). The
`pyats-topology` skill's model (`SKILL.md:114-142`) adds interfaces, subnets, routing adjacencies
and FHRP as prose; the NetBox reconciliation categories are DOCUMENTED / UNDOCUMENTED / MISSING /
MISMATCH.

Topology Dojo's document contract (`src/pages/model.ts:25-89`, `src/vendor/topology-ds.ts`)
has a home for all of it: `NodeConfig.meta` (serial, version, site), `NodeConfig.status`
(`ok|warn|down|maintenance|unknown`), `LinkConfig.fromLabel/toLabel` (interface names),
`LinkConfig.vlan/subnet/bandwidth/transport/showMeta`, `ZoneConfig` (site or VRF grouping),
`source` on every sourced element.

**Decision**: `workspace/skills/topology-dojo-diagram/dojo_document.py` (stdlib only, matching
the repo's Python-tooling convention) converts a snapshot into (a) a native document for
`import_topology` and (b) an `edit_topology` batch of `upsert_by_source` operations for re-sync.
It is a deterministic function of its input so it can be tested offline with fixtures. The LLM
never hand-writes 200 `add_node` calls.

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

**Decision** — identity scheme:

- node: `{system: <snapshot.source_kind>, kind: "device", id: <hostname lowercased>}`
- link: `{system: <source_kind>, kind: "link", id: "<a>:<ifA>|<b>:<ifB>"}` with endpoints
  sorted so A–B and B–A are the same link; when interfaces are unknown, `"<a>|<b>#<n>"` with a
  stable ordinal.
- zone (site/VRF): `{system: <source_kind>, kind: "site"|"vrf", id: <name>}`

Element ids are derived from the same strings (`n-<slug>`, `l-<slug>`) so the first sync's
`import_topology` document and later `upsert_by_source` batches agree. Matching is per page, so
the skill always passes `pageIndex` and single-page documents are the default; multi-page
(per-site) documents put the site name in the page name and sync each page separately.

Removed-at-source elements: the converter diffs the document returned by `get_topology`
(elements whose `source.system` matches) against the snapshot and reports them; removal is a
separate, engineer-confirmed `remove_element` batch (US2 scenario 3).

## R6: Sharing is an outward publication and is gated (satisfies FR-012, Clarification Q3)

`share_topology` writes a KV snapshot readable by anyone at `${PUBLIC_BASE_URL}/v/<id>` for 30
days (`worker/share.ts:99-128`, `SHARE_TTL_SECONDS`), rate-limited 8 per 300 s per user, and the
tool's own description says "Do not publish internal addresses, credentials, or other sensitive
content". Re-publishing mints a new id; nothing renews an old one. Revocation is
`unpublish_topology(shareId)` or `DELETE /api/topology/<id>` as the owner.

**Decision**: same shape as spec 122's credit-spending gate — explicit conversational "yes" in the
same turn sequence, a code-level `confirmed: true` argument on the skill helper that assembles the
call, a pre-publish scan for RFC 1918 / link-local / loopback strings in labels and metadata, and a
`gait_record_turn` entry (topology id, share id, expiry, outcome). The default deliverable is the
local SVG + JSON; the URL is only produced on request.

## R7: Workspace writes are proposals by default (satisfies FR-013, US4)

`src/mcp/README.md:237-244`: agents are "Suggest only" by default; only the browser grants a
ten-minute, page-scoped lease; `apply_workspace_changes` without one fails. Batches carry
`baseRevision` and a client `operationId`; the coordinator rebases disjoint fields and rejects
same-field overlap as a conflict. Limits: 250 operations / 512 KiB per batch, ≤20 unresolved
proposals. Legacy drafts (`migrated: false` in `list_workspaces`) reject agent workspace reads
until the owner opens them in the browser; `worker/mcp.ts:296-301` forbids agent-triggered
migration.

**Decision**: the skill's workspace path is manifest → (`describe_workspace_operations` once per
`operationSchemaRevision`) → `get_workspace_changes` since last revision → `get_workspace_elements`
for the affected page only → `propose_workspace_changes` with a title and rationale. Direct
`apply_workspace_changes` is used only when the engineer states the lease is live. **Unverified**:
whether `upsert_by_source` is among the 9 workspace operation types; if not, the converter emits
`add_*`/`update_element` operations against ids read from `get_workspace_elements`, using the
element `source` field for matching on the NetClaw side. Task T-research-2 settles this against
a hosted workspace.

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

**Decision**: nothing is vendored. Local mode clones at install time into the user's `$MCP_DIR`
(precedents: RADKit `install-steps.sh:1476-1484`, Percepxion). The PR description asks the
Topology Dojo maintainer to add a license (Apache-2.0 matches NetClaw and the vendored MCP servers
NetClaw already tracks); until then the README describes local mode as "clone your own copy".

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
