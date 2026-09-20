# Implementation Plan: Topology Dojo Topology Documentation Provider

**Branch**: `124-topology-dojo-provider` | **Date**: 2026-09-20 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/124-topology-dojo-provider/spec.md`

## Summary

Add Topology Dojo (`robertsonc/topology-dojo`) as a second topology-documentation target beside
`drawio-diagram`. One registered MCP server key (`topology-dojo-mcp`) reaches the hosted
deployment with a user-minted Topology Dojo API key by variable reference (the Globalping shape;
Topology Dojo proposal 0005, the only hosted credential path), or — in local mode — a
git-cloned stdio server. One new skill, `topology-dojo-diagram`, owns the discover → convert →
load → validate → tidy → inspect → render → persist loop, and its one piece of real code,
`dojo_document.py` behind an explicit `snapshot_adapter.py`, deterministically converts NetClaw's
existing canonical Topology Snapshot dataclasses into a Topology Dojo document and into
idempotent `upsert_by_source` batches under a stable document identity, so a re-run updates the
same diagram instead of duplicating it. Sharing a public link and writing into a colleague's
shared workspace are opt-in paths with explicit confirmation, GAIT records, and proposal-only
writes. Every other change is documentation coherence: SOUL routing boundaries, reciprocal
handoff lines in the skills that already name draw.io, installer catalog and profiles, HUD
entries, README/TOOLS/.env.example, and an offline contract suite. Nothing from the Topology Dojo
repository is copied into NetClaw, and the installer does not clone it either, because it carries
no license. Registering a Remote/OAuth integration in `config/openclaw.json` is a declared
exception to `docs/ADDING-AN-MCP.md` (research R13).

## Technical Context

**Language/Version**: Python 3.10+ for the converter and tests (stdlib only, matching every
`scripts/*.py`); Bash for the installer step; Markdown for SKILL/SOUL/TOOLS. No TypeScript is
written or vendored.
**Primary Dependencies**: none for the hosted path (a `url` entry; no bridge, no npx package).
Node.js 18+ / npm for local mode only; Topology Dojo's own
`npm ci` in local mode only, run by the operator on their own clone. No new Python packages.
**Storage**: N/A — timestamped artifacts under `workspace/output/topology-dojo/` (gitignored,
spec 046 convention) and GAIT records. The API key lives only in the operator's `.env`.
**Testing**: `tests/topology-dojo/run-tests.sh` (shell suite, offline) wrapping stdlib
`unittest` files for the converter plus registration/SKILL.md assertions; opt-in live-local check
via `TOPOLOGY_DOJO_DIR`. Declared in `tests/contract-suites.json`.
**Target Platform**: Linux/macOS hosts running NetClaw; hosted Topology Dojo on Cloudflare
(maintainer's deployment or self-hosted URL).
**Project Type**: skill + registered bearer-token remote MCP server (local stdio mode as a
secondary form of the same key).
**Performance Goals**: converter under 1 s for 60 devices / 90 links (SC-003); a full sync is one
`edit_topology` call for drafts up to 200 elements.
**Constraints**: hosted rate limits (120 writes/min, 8 shares/5 min); 200-op draft batch,
250-op/512 KiB proposal batch; 2 MiB SVG cap; OAuth login is interactive once per host.
**Scale/Scope**: single-page documents by default; multi-page (per site) when a snapshot carries
site metadata and exceeds ~40 devices.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I/II/VIII (Safety-First, Read-Before-Write, Verify After Every Change)**: No device is
  touched. Within Topology Dojo the same discipline applies: `get_topology`/manifest is read before
  any batch, `validate_topology` and `inspect_render` run after every load, and workspace writes
  are proposals (FR-013).
- **III (ITSM-Gated Changes)**: N/A — no production network change; diagrams are documentation.
- **IV (Immutable Audit Trail)**: Publish and revoke produce `gait_record_turn` entries (FR-012),
  reusing the existing substrate exactly as spec 122 does; no new store.
- **V (MCP-Native Integration)**: `topology-dojo-mcp` is a registered MCP server; the skill calls
  its tools by name. The converter is skill-side helper code, like `comfyui-topology-viz/*.py`.
- **VI (Multi-Vendor Neutrality)**: The converter accepts the vendor-neutral Topology Snapshot
  every source already produces; role mapping is by role, never by vendor.
- **VII (Skill Modularity)**: `topology-dojo-diagram` does one thing (document a snapshot in
  Topology Dojo); discovery stays in the source skills; document embedding stays in
  `document-generation`; verification stays in `browser-viz-verify`.
- **IX (Security by Default)**: Least privilege — hosted identity is the operator's own GitHub
  account via OAuth; NetClaw holds no client secret. Credential-shaped metadata is stripped before
  anything leaves the host (FR-014).
- **X (Observability)**: HUD node + annotation + keyword routing entries in
  `ui/netclaw-visual/server.js` (Polish phase).
- **XI (Full-Stack Artifact Coherence)** — NON-NEGOTIABLE: README (counts, table row, skill row,
  tree, architecture ASCII, capability bullet, discovery workflow), SOUL.md (identity count, new
  section with boundary), SOUL-SKILLS.md, TOOLS.md, `.env.example`, `catalog.sh` + profiles,
  `install-steps.sh`, `verify-catalog-coverage.py`, `config/openclaw.json`, HUD, contract suite.
  Tracked task by task in tasks.md.
- **XII (Documentation-as-Code)**: SKILL.md documents purpose, tools used, workflow, modes,
  required env vars and examples; no `mcp-servers/` directory is created, so
  `mcp-servers/<name>/README.md` is N/A and the operator-facing install notes live in the
  SKILL.md and TOOLS.md sections instead (recorded in Complexity Tracking).
- **XIII (Credential Safety)**: New variables are `TOPOLOGY_DOJO_MCP_URL`, `TOPOLOGY_DOJO_MODE`,
  `TOPOLOGY_DOJO_DIR`, and the one secret, `TOPOLOGY_DOJO_API_KEY`, referenced only by name in
  `config/openclaw.json` and documented in `.env.example` without a value. The SKILL.md names
  where the key is minted and revoked (`/keys`) and which scopes each story needs.
  `.env.example` gets names and descriptions only.
- **XIV (Human-in-the-Loop for External Communications)**: `share_topology` publishes to the
  public internet; it is confirmation-gated per invocation with a code-level `confirmed` guard
  (FR-012), the same two-layer pattern spec 122 applied to credit spend.
- **XV (Backwards Compatibility)**: Purely additive. `drawio-diagram` and every source skill are
  unchanged in behaviour; only handoff lines are added.
- **XVI (Spec-Driven Development)**: this directory.
- **XVII (Milestone Documentation)**: a blog post draft is owed at completion (Polish task), per
  spec 120/121/122 precedent.

**Result**: No violations. One registered server key is the minimum surface: the hosted path is
a plain bearer-token `url` entry (research R2), and local mode reuses the same key so skills and
the HUD see one integration.

## Project Structure

### Documentation (this feature)

```text
specs/124-topology-dojo-provider/
├── spec.md
├── plan.md               # this file
├── research.md           # R1–R12
├── data-model.md
├── quickstart.md
├── tasks.md
├── checklists/requirements.md
└── contracts/topology-dojo-mcp.md   # tool subset used, argument shapes, document projection
```

### Source Code (repository root)

```text
config/openclaw.json                         # + "topology-dojo-mcp" (url + Bearer ${TOPOLOGY_DOJO_API_KEY})

workspace/skills/topology-dojo-diagram/      # NEW skill
├── SKILL.md                                 # modes, loop, routing boundary, share gate, workspace path
├── snapshot_adapter.py                      # canonical TopologySnapshot/Link/LinkEndpoint (+ optional LinkOverlay) → adapted snapshot; recursive sanitizer
├── dojo_document.py                         # adapted snapshot → Dojo document + upsert batches + local diff/counters (stdlib)
└── share_guard.py                           # recursive address scan of the fetched document + confirmed:true guard + GAIT payload

workspace/skills/drawio-diagram/SKILL.md     # + "When to use Topology Dojo instead" boundary lines
workspace/skills/pyats-topology/SKILL.md     # + Topology Dojo handoff (Integration with Diagram Tools)
workspace/skills/netbox-reconcile/SKILL.md   # + reciprocal row (colour semantics preserved)
workspace/skills/document-generation/SKILL.md, network-report-documents/SKILL.md,
  browser-viz-verify/SKILL.md, clab-lab-management/SKILL.md, claroty-ot-topology/SKILL.md,
  msgraph-visio/SKILL.md, uml-diagram/SKILL.md, markmap-viz/SKILL.md   # + one handoff/boundary line each

scripts/lib/catalog.sh                       # + "topology-dojo|Analysis & Diagrams|Topology Dojo|..." + PROFILE_RECOMMENDED/MULTIVENDOR/LABS
scripts/lib/install-steps.sh                 # + component_install_topology_dojo() (hosted: nothing to install, print key guidance; local: verify operator-supplied clone + openclaw mcp set, no clone/install)
scripts/verify-catalog-coverage.py           # + GROUPED_CONFIG_EXACT "topology-dojo-mcp": "topology-dojo"
scripts/in2n-profiles.py                     # + "topology-dojo-diagram" in the viz profile's exact list
ui/netclaw-visual/server.js                  # + node entry, annotation entry, 'diagram'/'topology' keyword routing

README.md, SOUL.md, SOUL-SKILLS.md, TOOLS.md, .env.example   # coherence surfaces (counts: skills 227→228, MCP stays 173 as computed 172→173)

tests/topology-dojo/
├── run-tests.sh                             # offline: registration, SKILL.md language, unit tests; live-local opt-in
├── test_snapshot_adapter.py                 # real-model field names, link identity precedence, overlay, recursive sanitizer
├── test_dojo_document.py                    # mapping, identity, chunking, determinism, local diff + counters
├── test_share_guard.py                      # guard refuses without confirmed=True; recursive address scan incl. link subnet
├── fixtures/                                # serialized from real _build_snapshot() output: small, reconciled(+overlay), large (60/90), sites, parallel-links
└── live_local.sh                            # TOPOLOGY_DOJO_DIR → npm run mcp via scripts/mcp-call.py, asserts no network access
tests/contract-suites.json                   # + "topology-dojo" shell suite (path null, no packages)
```

**Structure Decision**: No `mcp-servers/` directory. The hosted server is remote and the local
server is a user-owned clone (research R9), so the vendored-directory conventions (`.gitignore`
negation, `mcp-servers/<name>/README.md`, `check-dependency-pins.py` scope) do not apply. The
converter lives in the skill directory, the same placement spec 120/122 use for
`topology_model.py`, `prompt_builder.py` and friends.

## Phase 0 outputs → decisions carried into design

| Research | Decision |
|---|---|
| R1 | peer skill, no provider abstraction, boundary prose in SOUL + four SKILL.md files |
| R2 | hosted = `url` + `Bearer ${TOPOLOGY_DOJO_API_KEY}` (Topology Dojo proposal 0005, gated by its `API_KEYS_ENABLED`), the only hosted path; T005 confirms the deployment is there |
| R3 | local = operator-supplied clone (`TOPOLOGY_DOJO_DIR`) + `npm run --silent mcp`, verified and registered by the installer, no network; clone-at-install gated on R9 |
| R4/R5 | explicit adapter over the real dataclasses + optional link overlay; link identity precedence (link_id → interface pair → flagged fallback); stable document identity; diff via the sourced-element listing (`get_topology sources:true` / `get_workspace_elements sourcedOnly:true`, proposal 0006) with `created` from batch results; tier placement; no auto re-layout on sync |
| R6 | share gate: fetch current document → recursive address scan → confirm → publish → GAIT; default deliverable is local files |
| R7 | workspace path is proposal-only and every op is `element.upsert` (proposal 0006, schema revision 2); NetClaw never resolves workspace ids |
| R8 | SVG + JSON (+ flipbook) artifacts; `browser-viz-verify` for raster |
| R9 | nothing vendored; license request in the PR |
| R10 | batch and rate limits are converter/skill constants |
| R11 | offline shell suite + unittest; live-local opt-in |
| R13 | registered bearer-token `url` entry, the Globalping shape, declared against `docs/ADDING-AN-MCP.md`'s table |

## Complexity Tracking

| Item | Why it is needed | Simpler alternative rejected because |
|---|---|---|
| Two connection modes | air-gapped labs and contributors without a GitHub identity (US5) | hosted-only would make the offline contract suite the only way to exercise the converter end to end |
| A Python converter rather than prompt-driven `add_node` calls | 200-op batches, idempotent identities, deterministic tests (R4/R5) | prompt-driven authoring cannot be tested offline and burns the per-turn tool budget Topology Dojo's own README warns about |
| No `mcp-servers/<name>/README.md` | no directory exists to hold it (R9) | a README without a server misleads `verify-catalog-coverage.py`'s vendored-state check; the operator notes live in SKILL.md and TOOLS.md |
| Registered `config/openclaw.json` entry for a remote integration | same shape as the five registered bearer-token remotes; one key must serve both modes; HUD, startup check and contract suite need a registered key (R13) | the guide's table default (external, `EXTERNAL_INTEGRATIONS`) would leave local mode with no key to rewrite and no startup check; recorded as a declared classification |
| Operator-supplied clone instead of clone-at-install | upstream carries no license (R9); air-gapped hosts need a pre-staged clone anyway | clone-at-install becomes the follow-up once a license lands |

## Upstream follow-ups (Topology Dojo repository — not in this PR)

1. ~~Add a `LICENSE`~~ — done in robertsonc/topology-dojo#247 (Apache-2.0). Clone-at-install for
   local mode becomes possible once it merges (still a NetClaw follow-up, not in this spec).
2. Expose the existing browser-only draw.io XML export (`src/editor/drawio.ts`) as an
   `export_drawio` MCP tool, so a Topology Dojo document can be handed to the existing
   `drawio-diagram` pipeline for Confluence/Visio consumers.
3. ~~A headless-friendly credential path~~ — done: proposal 0005 / robertsonc/topology-dojo#247
   (user-tied, scoped API keys behind `API_KEYS_ENABLED`); production activation pending its
   UAT-MCP-04.
4. ~~Workspace `element.upsert`, sourced-element listings, `created` in batch results~~ — done:
   proposal 0006 / robertsonc/topology-dojo#248.
5. Document the MCP client config for the hosted endpoint — done in #247 (`src/mcp/README.md`).
