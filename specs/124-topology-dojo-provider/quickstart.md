# Quickstart: Topology Dojo Topology Documentation Provider

## Prerequisites

- Node.js 18+ and npm (`npx` is how the bridge and the local server both start).
- **Hosted mode** (default): sign in to Topology Dojo with GitHub once, open `/keys`, mint a key
  with the scopes you need (`share` for public links, `workspace` for proposals), and put it in
  `.env` as `TOPOLOGY_DOJO_API_KEY`. No browser is needed on the NetClaw host. If the deployment
  has not enabled API keys, the `mcp-remote` fallback applies: the first tool call opens a browser
  for the OAuth flow once and caches tokens under `~/.mcp-auth/`; on a headless host, forward the
  callback port first (`ssh -L 3334:localhost:3334 <host>` then
  `npx -y mcp-remote@0.14.2 https://topology-dojo.harnessed.cloud/mcp 3334`).
- **Local mode**: `TOPOLOGY_DOJO_MODE=local` and `TOPOLOGY_DOJO_DIR` pointing at your own clone
  of `robertsonc/topology-dojo` with `npm ci` already run (on an air-gapped host, pre-stage the
  clone with its `node_modules` from a connected machine of the same platform). The installer
  verifies and registers it; it does not clone or install for you while upstream carries no
  license. No account, no sharing, no workspaces.
- A topology from any existing source (pyATS discovery, CML, containerlab, NetBox/Nautobot,
  IP Fabric, Forward) or a freeform description.

## 1. Document a discovered topology

```
"Run topology discovery on the lab testbed and document it in Topology Dojo"
```

Expected flow:
1. `pyats-topology` (or the named source) produces the Topology Snapshot.
2. `dojo_document.build_document()` converts it — role → node type, state → status, interface
   names → link labels, reconciliation status → link colour, source identity on every element.
3. `import_topology` → `validate_topology` → `balance_topology` (if needed) → `validate_topology`
   → `inspect_render` → `render_svg`.
4. NetClaw reads the document back with `get_topology` (so the saved JSON matches what was
   rendered after tidy), writes `workspace/output/topology-dojo/<identity>-<ts>.json` and `.svg`,
   and reports the topology id, mode, counts, and any remaining validation problems verbatim.

## 2. Update the same diagram after the network changed

```
"Re-run discovery and update the Topology Dojo diagram"
```

NetClaw finds the document by its stable identity (source kind + label, never the per-run
snapshot id), fetches the affected page with `get_topology(pageIndex)`, diffs it locally, and
emits one `edit_topology` call of `upsert_by_source` operations. Existing elements are patched in
place, new ones created, nothing duplicated. Devices that vanished at the source are listed as
"absent at source"; NetClaw removes them only if you say so.

## 3. Share with a stakeholder (hosted only)

```
"Share this diagram with the change board"
```

NetClaw fetches the current document, scans every field in it (link subnets included) for
internal addresses, lists what it found, states the link is public for 30 days, and asks.
Only on "yes" does it call `share_topology`, then returns the URL and expiry and writes a GAIT
record. `"list my Topology Dojo shares"` / `"revoke that link"` map to `list_shares` /
`unpublish_topology`.

## 4. Propose changes to a colleague's workspace (hosted only)

```
"Add the two new leaf switches to Sam's fabric workspace"
```

Manifest → changes since last seen → elements on the affected page → `propose_workspace_changes`
with a title and rationale. The owner reviews in the browser. NetClaw only uses
`apply_workspace_changes` if you say the page lease is live.

## 5. Choosing draw.io instead

Ask for a `.drawio` file, Confluence, Visio or an existing draw.io library and NetClaw routes to
`drawio-diagram`. Ask for validation, re-sync, sharing or collaboration and it routes here. When
both fit it says which it picked, in one sentence.

## Verify the integration

```bash
python3 scripts/reconcile-mcp.py                                   # exit 0
python3 scripts/run-contract-tests.py --suite topology-dojo --prepare
python3 scripts/check-server-startup.py --only topology-dojo-mcp   # timeout on stdio = success
TOPOLOGY_DOJO_DIR=$HOME/.openclaw/mcp-servers/topology-dojo bash tests/topology-dojo/live_local.sh   # optional
```
