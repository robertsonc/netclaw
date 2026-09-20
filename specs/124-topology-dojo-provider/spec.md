# Feature Specification: Topology Dojo Topology Documentation Provider

**Feature Branch**: `124-topology-dojo-provider`
**Created**: 2026-09-20
**Status**: Draft
**Input**: User description: "Build a Topology Dojo integration for NetClaw, as an additional network topology documentation provider similar to draw.io. Review the NetClaw and Topology Dojo repositories and build a plan to add the integration as a PR that can be contributed to the NetClaw project."

## Clarifications

### Session 2026-09-20

- Q: Is this a new "documentation provider abstraction" (an operator-selectable backend that
  draw.io and Topology Dojo both implement, like spec 070 did for ITSM), or one more diagram skill
  beside `drawio-diagram`? → A: **One more diagram skill, with explicit routing boundaries.**
  NetClaw's diagram handoffs today are prose contracts in `SKILL.md` files (see
  `pyats-topology`, `netbox-reconcile`, `document-generation`); `drawio-diagram` is not behind an
  abstraction either. A formal provider layer would require a Constitution amendment (spec 070
  precedent) and would not change what the agent can do. Reciprocal handoff rows are added to the
  same files that name draw.io today. See research.md R1.
- Q: Topology Dojo's hosted MCP endpoint is OAuth 2.1 with GitHub as the identity provider and has
  no API-key path. How does an unattended NetClaw authenticate? → A: **Two connection modes, one
  registered server key.** Hosted mode (default) authenticates with a user-minted Topology Dojo
  API key sent as a bearer header (Topology Dojo proposal 0005, PR #247), the same shape NetClaw
  uses for Globalping and Topolograph. Until a deployment enables that feature, the `mcp-remote`
  stdio bridge NetClaw already ships for IP Fabric and ThousandEyes is the fallback: it completes
  the OAuth flow once interactively and caches tokens on disk. Local mode runs Topology Dojo's own
  unauthenticated stdio server from a clone the operator supplies. See research.md R2/R3.
- Q: `share_topology` publishes a public, unauthenticated 30-day snapshot. Is that an "external
  communication" under Constitution Principle XIV? → A: **Yes.** Sharing is opt-in, requires
  explicit per-invocation confirmation in the same conversation, produces a GAIT record
  (Principle IV), and is preceded by credential-shaped-metadata stripping and an internal-address
  warning. The default deliverable is a local artifact, never a public link. See research.md R6.
- Q: Topology Dojo has no LICENSE file and `package.json` declares none. Can NetClaw vendor it? →
  A: **No.** Nothing from the Topology Dojo repository is copied into NetClaw. Until the upstream
  repository carries a license, local mode registers a clone the operator supplies
  (`TOPOLOGY_DOJO_DIR`, bring-your-own or pre-staged); the installer never clones automatically.
  Automatic clone-at-install (the Percepxion/RADKit precedent) is a follow-up gated on that
  license. See research.md R9.
- Q: `docs/ADDING-AN-MCP.md` classifies Remote/OAuth integrations as external, with no
  `config/openclaw.json` entry. This plan registers a bridged stdio entry. Which is it? → A: **A
  declared exception.** The integration is Remote/OAuth by that taxonomy, but it is registered
  because one server key must serve both the hosted (bridged) and local (stdio) modes, the HUD and
  startup check need a registered key, and repo precedent is already mixed (Globalping, Meraki and
  ThousandEyes Official are all registered `url` entries). The exception is recorded in research.md
  R13 and FR-019 is worded accordingly; the plan does not claim unqualified adherence.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Document a discovered topology in Topology Dojo (Priority: P1)

A network engineer has just run topology discovery (pyATS CDP/LLDP, a CML or containerlab lab, a
NetBox/Nautobot export, IP Fabric or Forward) and asks NetClaw to "document this in Topology
Dojo". NetClaw converts the discovered devices and links into a Topology Dojo document, loads it,
validates and tidies the layout, and returns a standalone SVG plus the portable document JSON,
both written to NetClaw's persistent output directory. The engineer opens the JSON in the Topology
Dojo editor (hosted or local) and finds every device and link present, correctly typed, with
interface names on the link ends.

**Why this priority**: This is the whole point of the feature — the same "discover → document"
loop `drawio-diagram` serves today, but producing a diagram that is validated for overlap and
legibility before it is handed back, and that a human can keep editing in a real editor.

**Independent Test**: Run discovery against any one source (or use a freeform description), invoke
the skill, and confirm the two artifacts exist, the SVG opens, and the JSON round-trips through
`import_topology` without warnings.

**Acceptance Scenarios**:

1. **Given** a topology snapshot with N devices and M links from any supported source, **When**
   the engineer asks for a Topology Dojo diagram, **Then** the resulting document contains exactly
   N nodes and M links, every node's label is the device hostname character-for-character, and
   every link carries its endpoint interface names when the source supplied them.
2. **Given** the document has been loaded, **When** validation reports layout problems, **Then**
   NetClaw runs the tidy/balance pass and re-validates before rendering, and reports any remaining
   problems verbatim rather than hiding them.
3. **Given** the render succeeds, **When** NetClaw reports back, **Then** it names both artifact
   paths (`.svg` and `.json`), the Topology Dojo topology id, and which connection mode (hosted or
   local) produced them.
4. **Given** the source is unreachable or returns no devices, **When** the skill is invoked,
   **Then** NetClaw says which source failed and why, and creates no empty diagram.

---

### User Story 2 - Re-run discovery and update the same diagram (Priority: P1)

The engineer re-runs discovery a week later after adding a switch and re-cabling two links, and
asks NetClaw to "update the Topology Dojo diagram". NetClaw converges the existing document onto
the new data: the new switch appears, the two links are updated in place, nothing is duplicated,
and devices that disappeared are reported (not silently deleted). Reconciliation status from
`netbox-reconcile` (documented / undocumented / missing / mismatch) is preserved as link colour.

**Why this priority**: Idempotent re-sync is what makes this a *documentation* provider rather than
a one-shot picture generator. Topology Dojo's `upsert_by_source` primitive exists exactly for
this, and draw.io has no equivalent.

**Independent Test**: Load a fixture snapshot twice; the second load must yield the same node and
link counts as the first. Load a modified fixture; only the changed elements differ.

**Acceptance Scenarios**:

1. **Given** a diagram previously produced from source S, **When** the same source is re-read with
   no changes, **Then** a second sync produces zero new elements and zero duplicates.
2. **Given** a device was added at the source, **When** synced, **Then** exactly one new node is
   created, carrying the source identity (system, kind, id) that future syncs will match on.
3. **Given** a device was removed at the source, **When** synced, **Then** NetClaw lists it as
   "present in diagram, absent at source" and removes it only if the engineer asks.
4. **Given** links carry reconciliation status, **When** rendered, **Then** link colours follow
   the existing NetClaw convention (green documented, yellow undocumented, red missing, orange
   mismatch) and the legend is enabled.

---

### User Story 3 - Share a diagram with a stakeholder (Priority: P2)

After reviewing the diagram, the engineer asks NetClaw to "share this with the change board".
NetClaw states that the link will be public to anyone holding it for 30 days, warns if the
document contains RFC 1918 or link-local addresses, and asks for confirmation. On "yes", it
publishes, returns the URL and expiry, and records the action in the GAIT audit trail. The
engineer can later list live links and revoke one.

**Why this priority**: Sharing is the collaboration feature draw.io's MCP cannot offer, but it is
an outward-facing publication of network data and must be gated accordingly.

**Independent Test**: With hosted mode configured, ask to share; confirm the warning and prompt
appear before any publish call; confirm the GAIT record exists after; confirm `list_shares` shows
the link and `unpublish_topology` removes it.

**Acceptance Scenarios**:

1. **Given** the engineer asks to share, **When** NetClaw has not yet received an explicit "yes" in
   this conversation, **Then** no publish call is made.
2. **Given** confirmation, **When** the publish succeeds, **Then** the response includes the URL,
   the expiry date, and a reminder that re-publishing mints a new URL rather than renewing the old.
3. **Given** the deployment rate-limits publishing, **When** the limit is hit, **Then** NetClaw
   reports the retry-after interval and does not retry on its own.
4. **Given** local mode is active, **When** the engineer asks to share, **Then** NetClaw explains
   that sharing needs the hosted deployment and offers the local SVG/JSON instead.

---

### User Story 4 - Propose changes to a shared Agent Workspace (Priority: P2)

A colleague owns a canonical Topology Dojo workspace for the data-centre fabric. The engineer asks
NetClaw to "add the two new leaf switches we discovered to Sam's fabric workspace". NetClaw reads
the workspace manifest, hydrates only the affected page, and submits a named change proposal with
a rationale. It never commits directly unless the owner has granted a live page lease in the
browser, and it says so.

**Why this priority**: This is Topology Dojo's human-and-agent collaboration model; it maps
directly onto NetClaw's read-before-write and human-in-the-loop principles. It depends on the
hosted deployment and on the owner having handed the document off, so it is P2.

**Independent Test**: Against a hosted workspace, submit a proposal from a fixture; confirm it
appears in the owner's review list and that no revision advanced until accepted.

**Acceptance Scenarios**:

1. **Given** a workspace id, **When** NetClaw prepares changes, **Then** it uses the manifest's
   current revision as the base revision and a client-generated idempotent operation id.
2. **Given** the workspace is a legacy draft not yet handed off, **When** NetClaw tries a workspace
   read, **Then** it reports that the owner must open it in the browser first, and stops.
3. **Given** a proposal conflicts with a concurrent browser edit, **When** submitted, **Then**
   NetClaw reports the conflict and re-reads changes since its base revision before retrying once.

---

### User Story 5 - Work offline with a local Topology Dojo (Priority: P3)

Two distinct situations share this story and must not be conflated. (a) An engineer who does not
want to use a GitHub identity, on a host with outbound access: they obtain a Topology Dojo clone
(today by hand, later via the installer once the upstream license lands), the installer verifies
Node.js and the clone's installed dependencies, and registers the stdio server. (b) An engineer on
an air-gapped lab host: they pre-stage the clone with its dependencies already installed (built on
a connected machine of the same platform, since the toolchain carries native binaries) and the
installer registers it performing no network access at all. In both cases Stories 1 and 2 work
unchanged; NetClaw persists every document JSON itself because the local server holds drafts only
in memory.

**Why this priority**: Local mode is the fallback for labs without identity or connectivity; it is
not the primary path, and its install story is constrained by the upstream license (research R9).

**Independent Test**: With `TOPOLOGY_DOJO_MODE=local` and `TOPOLOGY_DOJO_DIR` pointing at a
prepared clone, run Story 1's independent test; confirm the artifacts exist, that no
share/workspace tools are offered, and that the install and the run made no network calls.

**Acceptance Scenarios**:

1. **Given** local mode, **When** Node.js 18+ is missing, **Then** the installer says so and skips
   the component rather than registering a server that cannot start.
2. **Given** local mode, **When** the server process restarts, **Then** previously produced
   diagrams are still available as JSON artifacts and are re-imported before the next sync.
3. **Given** an air-gapped host with a pre-staged clone whose dependencies are installed, **When**
   the installer runs with `TOPOLOGY_DOJO_DIR` set, **Then** it registers the server without any
   network access, and the contract suite's local check proves the sync loop needs none either.
4. **Given** `TOPOLOGY_DOJO_DIR` is unset or points at a directory with no installed
   dependencies, **When** the installer runs, **Then** it explains what to pre-stage and skips;
   it never clones or installs on the operator's behalf while the upstream repository is
   unlicensed.

---

### User Story 6 - Choose the right diagram tool (Priority: P2)

An engineer asks NetClaw to "diagram the network" without naming a tool. NetClaw picks Topology
Dojo when the deliverable is a validated, editable, re-syncable topology document; draw.io when
the engineer needs a `.drawio` file for Confluence, Visio or an existing draw.io library; the
3D visualizers when the ask is exploratory or presentational; Markmap for hierarchy; UML for
protocol and sequence diagrams. When both draw.io and Topology Dojo fit, NetClaw says which it
chose and why, in one sentence.

**Why this priority**: Adding a second topology-documentation skill without a routing boundary
would make the agent's behaviour depend on prompt wording. SOUL.md today has no such boundary
even between draw.io and the 3D tools; this story closes that gap for the new pair.

**Independent Test**: Contract test asserts the boundary language exists in SOUL.md, both SKILL.md
files, and `document-generation`'s routing table.

**Acceptance Scenarios**:

1. **Given** the ask names a `.drawio` deliverable or Confluence/Visio, **When** routing, **Then**
   NetClaw uses `drawio-diagram`.
2. **Given** the ask involves re-sync, validation, collaboration, sharing, or "keep this updated",
   **When** routing, **Then** NetClaw uses `topology-dojo-diagram`.
3. **Given** `document-generation` embeds a diagram, **When** the diagram came from Topology Dojo,
   **Then** it embeds the SVG artifact and never redraws it.

### Edge Cases

- A snapshot larger than one authoring batch (200 operations for a private draft, 250 operations
  or 512 KiB for a workspace proposal): the converter must chunk deterministically and NetClaw must
  report partial application if a later chunk fails.
- The rendered SVG exceeds the 2 MiB response cap: NetClaw must reduce density (split pages by site
  or role tier) or report the cap rather than retrying the same page.
- Mutating-tool rate limit (120 per 60 s per user on the hosted deployment): batches, not
  per-element calls, so a full sync is a handful of quota units.
- The hosted OAuth token expires or was never obtained on a headless host: NetClaw must surface the
  bridge's login URL and the port-forward instruction, not a generic connection error.
- The document was handed off to a workspace after NetClaw last saw it: the private-draft tools
  return a typed error naming the workspace tools; NetClaw switches to the proposal path.
- Page targeting: the `add_*` tools default to the most recently added page while `render_svg`
  defaults to page 0; the skill always passes `pageIndex` explicitly.
- A device hostname or interface name contains characters unsafe for an element id: ids are
  derived deterministically and the human-readable label keeps the original text.
- Parallel links between the same two devices with no interface names and no source-supplied
  link id are inherently ambiguous across discoveries; the fallback ordering is deterministic for
  a given input and the Sync Report flags such links so the engineer knows identities may have
  swapped.
- The source adapter synthesised a positional link id (`link-<n>`): it is treated as absent, not
  as a stable identity.
- Device metadata carries credential-shaped keys (password, secret, token, api_key): stripped
  before anything leaves NetClaw, using the same `sanitize_metadata` rule specs 120–122 apply.
- The shared snapshot contains internal addresses: NetClaw warns before publishing and lists them.
- Local mode server exit: drafts are gone; every document JSON is written to disk at the end of
  every successful sync so nothing is lost.
- The share link has expired (30 days): NetClaw offers to re-publish and notes it will be a new URL.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST consume the existing canonical Topology Snapshot dataclasses as
  they are (`TopologySnapshot`: `snapshot_id`, `source_kind`, `source_label`, `created_at`,
  `devices`, `links`; `Device`: `hostname`, `role`, `state`, `interfaces`, `metadata`;
  `Interface`: `name`, `ip_address`, `state`, `metadata`; `Link`: `link_id`, `endpoint_a`,
  `endpoint_b` each with `hostname` and `interface_name`, `state`, `label`) through an explicit
  adapter that is tested against serialized output of the real source adapters, and MUST accept an
  optional caller-supplied per-link annotation overlay (reconciliation status, VLAN, bandwidth,
  transport) for data the canonical model does not carry. The caller never needs Topology Dojo's
  vocabulary.
- **FR-002**: Every device MUST map to exactly one node whose label is the hostname verbatim, whose
  node type follows a documented role mapping, and whose status follows a documented state mapping.
- **FR-003**: Every link MUST map to exactly one link between the two endpoint nodes, carrying the
  endpoint interface names as the link's from/to labels when known, and VLAN, subnet, bandwidth and
  transport as first-class link metadata when known.
- **FR-004**: Every node and link MUST carry a source identity (system, kind, id, fetched-at) so
  that a repeated sync converges on the existing element instead of creating a duplicate. Link
  identity MUST prefer a source-supplied link id, then the sorted endpoint:interface pair, and only
  then a documented deterministic fallback whose ordering rule is stated and tested.
- **FR-004a**: Document identity MUST be stable across discoveries. It is derived from the source
  kind and source label, never from the per-run snapshot id, which is provenance only. Hosted mode
  locates the existing draft by that identity; local mode re-imports the newest artifact carrying
  that identity before syncing.
- **FR-005**: A sync MUST be expressed as ordered operation batches no larger than the target's
  documented limit, applied atomically per batch, with partial application reported.
- **FR-006**: After loading, the system MUST validate the document, run the tidy/balance pass when
  layout problems are reported, and re-validate; remaining problems are reported verbatim.
- **FR-007**: The system MUST run the visual-quality inspection before rendering and MUST render
  at most once per page per sync.
- **FR-008**: Every successful sync MUST write the canonical document as read back from Topology
  Dojo after the final validate/tidy pass (never the converter's pre-import object, which lacks
  the layout adjustments the render used) and the rendered SVG to the persistent NetClaw output
  directory as timestamped, uniquely named files that are never overwritten (the spec 046
  convention).
- **FR-008a**: Created, updated and unchanged counts in the Sync Report MUST be derived locally by
  diffing the fetched canonical page against the intended element state before the batch is sent,
  because batch results carry only the operation name, element id and page index.
- **FR-009**: Reconciliation status supplied by the source MUST map to link colour using the
  existing NetClaw convention (green documented, yellow undocumented, red missing, orange mismatch)
  and MUST enable the document legend.
- **FR-010**: The system MUST support two connection modes selected by configuration — hosted
  (default, the maintainer's deployment or any self-hosted deployment URL) and local (a stdio
  server run from an operator-supplied clone) — under one registered server key.
- **FR-011**: In hosted mode, authentication MUST use a user-minted Topology Dojo API key
  referenced by variable name (`TOPOLOGY_DOJO_API_KEY`) in a bearer header, never a literal in a
  tracked file. Where the deployment has not enabled API keys, the system MUST fall back to the
  deployment's OAuth flow through the `mcp-remote` bridge and MUST name the bridge's
  cached-credential location so an operator can revoke it. The skill MUST tell the operator which
  scopes the key needs per story (`share` for US3, `workspace` for US4; none for US1/US2).
- **FR-012**: Publishing a public share link MUST require explicit confirmation in the same
  conversation, MUST be preceded by a recursive scan of the current server-side canonical
  document, fetched immediately before the publish call, across every string field (first-class
  link fields such as subnet, interface addresses, labels, sublabels, metadata and annotations
  included) that warns about any private, link-local, loopback or unique-local address found, and
  MUST produce a GAIT audit record naming the topology, the share id, the expiry, and the outcome
  — never the document contents.
- **FR-013**: Writes to a shared Agent Workspace MUST be submitted as named proposals by default;
  direct application MUST only be attempted when the engineer states that a live page lease is
  granted, and a conflict MUST be reported, not retried blindly.
- **FR-014**: Credential-shaped metadata keys MUST be stripped from every device, interface and
  link before any data is sent to Topology Dojo in either mode, using at least the union of the
  existing NetClaw denylist (password, secret, credential, credentials, api_key, apikey, token,
  running_config, startup_config, config, private_key) with passwd and community, applied
  recursively through nested mappings and lists so a secret under an innocent parent key cannot
  survive.
- **FR-015**: When a requested capability is unavailable in the active mode (share, workspace,
  checkpoints, authoring preferences in local mode), the system MUST say so and offer the nearest
  available alternative instead of failing opaquely.
- **FR-016**: The system MUST consult Topology Dojo's authoring guidance and layout guidelines
  once per session (when available) and follow the returned directives when placing elements.
- **FR-017**: SOUL.md, `topology-dojo-diagram/SKILL.md`, `drawio-diagram/SKILL.md`, and
  `document-generation/SKILL.md` MUST each state the routing boundary between Topology Dojo,
  draw.io, the 3D visualizers, Markmap and UML.
- **FR-018**: The skills that today hand off to draw.io for topology output (`pyats-topology`,
  `netbox-reconcile`, `clab-lab-management`, `claroty-ot-topology`, `network-report-documents`,
  `browser-viz-verify`, `msgraph-visio`) MUST gain a reciprocal Topology Dojo handoff line.
- **FR-019**: The integration MUST follow `docs/ADDING-AN-MCP.md` and pass
  `scripts/reconcile-mcp.py` with exit 0, including the documented count claims, with one declared
  exception recorded in research R13: by that guide's taxonomy this is a Remote/OAuth integration
  and would be external, but it is registered as a bridged stdio entry so one key serves both
  modes. The exception MUST be stated in the spec, TOOLS.md and the PR, not implied.
- **FR-020**: An offline contract test suite MUST cover the converter (mapping, idempotent source
  identities, chunking, sanitization, determinism), the registration shape, and the SKILL.md
  safety language, and MUST be declared in `tests/contract-suites.json`.
- **FR-021**: Nothing from the Topology Dojo repository MUST be copied into NetClaw. While the
  upstream repository carries no license, local mode registers an operator-supplied clone and the
  installer MUST NOT clone or install on the operator's behalf; automatic clone-at-install is
  enabled only once a license is present upstream.

### Key Entities

- **Topology Snapshot**: the existing normalized input (devices, links, source kind, snapshot id,
  created-at, as defined by the canonical dataclasses). Consumed, not owned.
- **Dojo Document**: Topology Dojo's native document (title, ordered pages, each with nodes,
  links, anchors, zones, flow paths, policy markers; optional layers, legend, palette). Produced
  by the converter; the portable, canonical artifact.
- **Document Identity**: the stable key (source kind + source label) that names one Topology Dojo
  document across discoveries; the snapshot id is provenance, not identity.
- **Source Identity**: the (system, kind, id, fetchedAt) tuple stamped on every converted element;
  the key `upsert_by_source` converges on.
- **Sync Batch**: an ordered list of authoring operations bounded by the target's limits, with a
  batch index and an outcome.
- **Sync Report**: what NetClaw returns — counts created/updated/unchanged, elements present in
  the diagram but absent at source, validation problems remaining, artifact paths, topology id,
  mode, and (when shared) URL and expiry.
- **Connection Mode**: hosted or local, with the capability set each exposes.
- **Share Record**: the GAIT entry for a publish or revoke.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For every fixture snapshot in the contract suite, node count equals device count and
  link count equals link count, and every hostname appears exactly once as a label — 100%.
- **SC-002**: Syncing the same fixture twice yields zero created elements on the second pass; the
  contract suite asserts this offline against the converter's operation output.
- **SC-003**: A 60-device, 90-link fixture converts and chunks into at most 1 batch for a private
  draft and at most 1 proposal for a workspace, and converter runtime is under one second.
- **SC-004**: No publish call is possible without a confirmation token supplied in the same
  invocation; the contract suite asserts the skill language and the GAIT requirement.
- **SC-005**: `scripts/reconcile-mcp.py` exits 0 on the PR branch; `scripts/verify-spec-artifacts.py`
  passes; `scripts/run-contract-tests.py --suite topology-dojo --prepare` passes offline.
- **SC-006**: `git grep` finds no OAuth token, client secret, `tdk_` API key, or share URL in any
  tracked file.
- **SC-007**: A reviewer reading SOUL.md can state, without opening a SKILL.md, when NetClaw picks
  Topology Dojo over draw.io.
- **SC-008**: `scripts/check-server-startup.py --only topology-dojo-mcp` reports no fatal finding
  in hosted mode when Node.js is present (a timeout waiting on stdio is success).

## Assumptions

- The maintainer's hosted deployment at `https://topology-dojo.harnessed.cloud/mcp` remains the
  default URL; operators can point `TOPOLOGY_DOJO_MCP_URL` at a self-hosted deployment or staging.
- Topology Dojo's API key feature (proposal 0005, robertsonc/topology-dojo#247) is enabled on the
  deployment NetClaw targets; until production activates it, the `mcp-remote` OAuth bridge is the
  documented fallback and the skill does not change between the two.
- OpenClaw's gateway MCP client supports `url` entries with a static `headers.Authorization`
  (precedent: `globalping-mcp`, `meraki-mcp`, `topolograph-mcp`); native OAuth dynamic client
  registration is not assumed.
- Topology Dojo's tool surface as of commit `4dddaca` (57 tool definitions; 34 available on the
  local stdio server) is the contract; the skill uses a documented subset (see
  `contracts/topology-dojo-mcp.md`).
- PNG export is browser-only in Topology Dojo; SVG and flipbook HTML are the delivery artifacts.
  `browser-viz-verify` can screenshot the SVG when a raster is required.
- draw.io XML export exists in Topology Dojo's browser editor only; a Dojo → draw.io hand-over over
  MCP is a Topology Dojo follow-up, not part of this feature.
- Registering a Remote/OAuth integration in `config/openclaw.json` departs from the default in
  `docs/ADDING-AN-MCP.md`; it is a deliberate, recorded exception (research R13), not an oversight.
- The canonical Topology Snapshot carries no per-link VLAN, subnet, bandwidth or reconciliation
  status; those arrive through an optional overlay the calling skill supplies (for example
  `netbox-reconcile`'s categories), and interface subnets are derived from `Interface.ip_address`
  only when it carries a prefix length.
- The pre-existing count drift (docs claim 173 MCP integrations, computed 172) is resolved by this
  feature's single new registered server, which brings the computed value to 173; skills go from
  227 to 228. Both are stated explicitly in the PR so the coincidence is not mistaken for a fix.
- No iN2N member scope changes ship in this PR; `scripts/in2n-profiles.py`'s `viz` profile gains
  the skill name so a future member regeneration picks it up.
