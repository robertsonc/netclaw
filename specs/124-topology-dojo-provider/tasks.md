# Tasks: Topology Dojo Topology Documentation Provider

**Input**: Design documents from `/specs/124-topology-dojo-provider/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md,
data-model.md, contracts/topology-dojo-mcp.md, quickstart.md

**Tests**: Included — plan.md commits to an offline contract suite (converter unit tests,
registration and SKILL.md assertions) and an opt-in live-local check. Tests for a story are
written before that story's implementation.

**Organization**: Grouped by user story (spec.md: US1/US2 are P1; US3/US4/US6 are P2; US5 is P3).
Two research-verification tasks sit in Phase 2 because their answers change the wiring (research
R2 and R7 each carry one unverified item).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1–US6 from spec.md
- Exact file paths are included in every description

## Path Conventions

- `workspace/skills/topology-dojo-diagram/` — new skill (SKILL.md + three stdlib Python modules)
- `tests/topology-dojo/` — new contract suite
- No `mcp-servers/` directory (plan.md Structure Decision, research R9)

---

## Phase 1: Setup

**Purpose**: The registration, catalog and skill stub exist so every later task edits a real file.

- [x] T001 Add `"topology-dojo-mcp"` to `config/openclaw.json` in the hosted API-key form from
  `contracts/topology-dojo-mcp.md` (`url` + `headers.Authorization: Bearer ${TOPOLOGY_DOJO_API_KEY}`
  + mirrored `env`), no literal secret (`docs/ADDING-AN-MCP.md` step 2; research R2 update)
- [x] T002 [P] Create `workspace/skills/topology-dojo-diagram/SKILL.md` stub with frontmatter
  (`name`, `description`, `license: Apache-2.0`, `user-invocable: true`,
  `metadata.openclaw.requires.bins: ["npx"]`, block-YAML form as in
  `workspace/skills/worldlabs-topology-viz/SKILL.md`)
- [x] T003 [P] Add `.env.example` block (rule style, "spec 124"): `TOPOLOGY_DOJO_MCP_URL`
  (default noted), `TOPOLOGY_DOJO_MODE` (`hosted`|`local`), `TOPOLOGY_DOJO_DIR` (local clone
  path), `TOPOLOGY_DOJO_API_KEY` (minted at `<deployment>/keys`; which scopes each story needs)
  — names and descriptions only, never a value
- [x] T004 [P] Add the catalog entry to `scripts/lib/catalog.sh`
  (`"topology-dojo|Analysis & Diagrams|Topology Dojo|Validated, re-syncable, shareable topology documents (hosted API key, or local clone)"`)
  and add `topology-dojo` to `PROFILE_RECOMMENDED`, `PROFILE_MULTIVENDOR`, `PROFILE_LABS`
  (`docs/ADDING-AN-MCP.md` "two artifacts that are easy to miss", item 1)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Settle the two unverified research items and lay down the model + fixtures every
story's tests use.

- [ ] T005 Verify against the target deployment that proposals 0005 and 0006 are live: mint a key
  with no extra scopes, confirm a `url` + bearer registration reaches `tools/list`, that
  `share_topology` is absent for that key, that `describe_workspace_operations` reports
  `operationSchemaRevision: 2`, and that `get_topology` accepts `sources: true`. Record the
  outcome in `research.md` R2/R7. Until the deployment is there, hosted mode is unavailable by
  design (no fallback); the offline suite and local mode are how the rest of the tasks are
  exercised. Also run `python3 scripts/check-server-startup.py --only topology-dojo-mcp`
- [x] T006 Record the `element.upsert` operation shape from the target deployment's
  `describe_workspace_operations` (`upsertExample`) into `contracts/topology-dojo-mcp.md` and
  assert `build_workspace_batches()` output against it in T025 (research R7; resolved upstream by
  Topology Dojo proposal 0006 — no NetClaw-side id resolution exists)
- [x] T007 [P] Create `workspace/skills/topology-dojo-diagram/snapshot_adapter.py` consuming
  the **real** canonical model (`TopologySnapshot`/`Device`/`Interface`/`LinkEndpoint`/`Link`
  from `workspace/skills/comfyui-topology-viz/topology_model.py`, accepted as dataclasses or
  `asdict` output — no invented fields such as `fetched_at`, `a`/`b`, `a_interface`): recursive
  sanitizer over the union denylist, link identity precedence (`link_id` unless it is a positional
  `link-<n>` → sorted interface pair → flagged ordinal fallback), stable `document_identity`,
  optional `LinkOverlay` by `link_id`, subnet derivation from endpoint `Interface.ip_address`
  prefixes (data-model.md, research R4/R5)
- [x] T008 [P] Create `tests/topology-dojo/fixtures/*.json` by serializing real
  `_build_snapshot()` output (`dataclasses.asdict`, enums as values, `created_at` ISO) so field
  names cannot drift: `small` (5/4), `reconciled` (+ a `LinkOverlay` file with the four
  statuses), `large` (60/90, SC-003), `sites` (two sites via `metadata.site`), `parallel`
  (two interface-less links between the same pair, one with a real `link_id`, one without)
- [x] T009 [P] Create `tests/topology-dojo/run-tests.sh` skeleton in the Globalping style
  (`set -uo pipefail`, `REPO_ROOT` from `BASH_SOURCE`, `check()` helper, exit codes captured
  directly, `PASS`/`FAIL` banner) and declare the suite in `tests/contract-suites.json` as
  `kind: shell`, `environment.path: null`, no packages, `timeout_seconds: 120`, with a `live`
  block naming `TOPOLOGY_DOJO_DIR` and `tests/topology-dojo/live_local.sh`

---

## Phase 3: User Story 1 — Document a discovered topology (Priority: P1) 🎯 MVP

### Tests for User Story 1

- [x] T010 [P] [US1] Write `tests/topology-dojo/test_snapshot_adapter.py` (contracts §Adapter:
  real-model field names only, `link-<n>` treated as absent, identity precedence, endpoint-swap
  stability, `ambiguous` flag, overlay placement, nested-secret removal with the union denylist)
  and `test_dojo_document.py::TestBuildDocument` — node/link counts equal device/link counts,
  labels equal hostnames verbatim, role → type and state → status tables applied, interface names
  land in `fromLabel`/`toLabel`, overlay VLAN/bandwidth and derived subnet land in link fields with
  `showMeta: true`, every emitted key is in the recorded projection (contracts §Converter)
  (FR-001..004, FR-014, SC-001)
- [x] T011 [P] [US1] Add registration assertions to `tests/topology-dojo/run-tests.sh` — key
  present, `url` set, `headers.Authorization == 'Bearer ${TOPOLOGY_DOJO_API_KEY}'` by variable
  reference, no `command`/`args`, no `mcp-remote` anywhere in the skill or config, no literal
  `tdk_` key anywhere in tracked files, no `mcp-servers/topology-dojo*` directory exists
  (FR-011, FR-021, SC-006)

### Implementation for User Story 1

- [x] T012 [US1] Implement `workspace/skills/topology-dojo-diagram/dojo_document.py`:
  `slug()`, `ROLE_TO_TYPE`, `STATE_TO_STATUS`, `RECONCILIATION_COLOR`, tier placement on the
  layout-guideline grid with a viewBox that grows past 20 devices, `build_document()`
  (single page; `split_by_site=True` → one page per site), source identity on every element
  (research R4/R5, data-model.md). Stdlib only, type hints, `logging` for diagnostics, no bare
  `except`
- [x] T013 [US1] Write the SKILL.md workflow section: discover → `describe_capabilities` +
  `layout_guidelines` (+ `get_authoring_guidance` hosted) → convert → `import_topology` →
  `validate_topology` → `balance_topology`/`tidy_topology` → re-validate → `inspect_render` →
  `render_svg` once per page → `get_topology` (full) read-back → write
  `workspace/output/topology-dojo/<document_identity>-<ts>.{json,svg}` where the `.json` is the
  read-back document, never the converter's pre-import object → Sync Report. State the page-index
  rule (always explicit) and the "never render after every edit" rule (FR-006..008, FR-016)
- [x] T014 [US1] Write the SKILL.md "Connection modes" section — hosted with a Topology Dojo API
  key (mint at `/keys`, scopes per story, revoke there; never paste the key in chat or files; a
  missing tool in `tools/list` means a missing scope, not an outage; the deployment must have
  `API_KEYS_ENABLED`); local mode capabilities table from data-model.md (FR-010/011/015)
- [x] T015 [US1] Add SKILL.md content assertions to `run-tests.sh` for T013/T014 language
  (`pageIndex`, "render once", artifact directory, `/keys`, scopes per story, "local mode"
  capability gaps) and asserts the words `mcp-remote` and `~/.mcp-auth` are absent

---

## Phase 4: User Story 2 — Re-sync without duplicates (Priority: P1)

### Tests for User Story 2

- [x] T016 [P] [US2] `test_dojo_document.py::TestUpsertBatches` — same fixture twice → identical
  operation lists; endpoint swap → same link identity; `large.json` → exactly one batch at
  `max_ops=200`; `max_ops=250, max_bytes=524288` respected; batches close at node boundaries so no
  link precedes its endpoints (FR-004/005, SC-002/003)
- [x] T017 [P] [US2] `test_dojo_document.py::TestDiffSourced` — fed a fixture **sourced-element
  listing** (the `get_topology(sources: true)` row shape `{id, kind, source, label?}`): unchanged
  → all `unchanged`; added device → one `to_create`; removed device → one `absent_at_source`
  (foreign-system rows ignored); changed label → one `to_update`; geometry-only change →
  `unchanged`; the parallel fixture → `ambiguous_links` populated (US2 scenario 3, FR-008a)

### Implementation for User Story 2

- [x] T018 [US2] Implement `build_upsert_batches()` and `diff_sourced()` in `dojo_document.py`;
  `set` includes `type/x/y` (node) and `type/from/to` (link) so creation succeeds when no match
  exists; `fetchedAt` refreshed every sync; `created` is read from each result's `created` flag
  and cross-checked against `to_create`, updated/unchanged/absent come from `diff_sourced`
  (FR-008a)
- [x] T019 [US2] SKILL.md "Update an existing diagram" section: locate the document by its stable
  identity — hosted: `list_topologies` title match; local: newest
  `<document_identity>-*.json` artifact re-imported first — then `get_topology(sources: true,
  system: <source_kind>)`, `diff_sourced`, one `edit_topology` batch per chunk, report
  created (from the results' `created` flags) / updated / unchanged / absent / ambiguous, removal
  only on confirmation via `remove_element`; overlay reconciliation colours + `set_legend`
  (FR-004a, FR-009)
- [x] T020 [US2] Reciprocal handoff lines: `workspace/skills/pyats-topology/SKILL.md`
  ("Integration with Diagram Tools" + a "Topology Dojo diagram" subsection beside the draw.io
  one), `workspace/skills/netbox-reconcile/SKILL.md` table row, `clab-lab-management/SKILL.md`
  (FR-018)

---

## Phase 5: User Story 3 — Share with confirmation (Priority: P2)

### Tests for User Story 3

- [x] T021 [P] [US3] `tests/topology-dojo/test_share_guard.py` — `assert_confirmed(False)`
  raises; `scan_internal_addresses` walks a fetched document recursively and reports a link whose
  only internal value is `subnet: "10.1.1.0/30"`, plus link-local, loopback and ULA strings at any
  depth, and nothing for documentation-range addresses; `gait_payload` never contains a URL body
  or token (FR-012, SC-004)
- [x] T022 [P] [US3] `run-tests.sh` asserts the SKILL.md states: public for 30 days, explicit
  confirmation before `share_topology`, internal-address warning, GAIT record, re-publish mints a
  new URL, rate-limit "retry after" is reported not retried

### Implementation for User Story 3

- [x] T023 [US3] Implement `workspace/skills/topology-dojo-diagram/share_guard.py`
  (contracts §Share guard)
- [x] T024 [US3] SKILL.md "Share, list, revoke" section: `get_topology` (full) immediately
  before publishing → recursive scan → show the list → two-layer gate (conversational "yes" +
  `confirmed: true`) → `share_topology` → `gait_record_turn` payload; `list_shares`/
  `unpublish_topology`; the local-mode refusal with the SVG/JSON alternative (FR-012, FR-015)

---

## Phase 6: User Story 4 — Propose to a shared workspace (Priority: P2)

### Tests for User Story 4

- [x] T025 [P] [US4] `test_dojo_document.py::TestWorkspaceBatches` — proposal batches respect
  250 ops / 512 KiB; every op is `element.upsert` with plural `kind`, `pageId`, `source` and
  `element` matching the `upsertExample` recorded by T006; identities equal the draft batches';
  a client `operationId` is deterministic per (workspace, base revision, batch index)
- [x] T026 [P] [US4] `run-tests.sh` asserts SKILL.md says proposals are the default, `apply`
  only with a stated live lease, legacy drafts (`migrated: false`) are refused with the browser
  hand-off instruction, and conflicts re-read changes before one retry

### Implementation for User Story 4

- [x] T027 [US4] Add `build_workspace_batches()` to `dojo_document.py` emitting
  `element.upsert` operations (research R7)
- [x] T028 [US4] SKILL.md "Propose changes to a workspace" section: manifest (stop if
  `operationSchemaRevision < 2`) → `describe_workspace_operations` (cached per revision) →
  changes since → `get_workspace_elements(sourcedOnly: true)` for the affected page →
  `diff_sourced` → `propose_workspace_changes` of `element.upsert` ops with title + rationale →
  add/patch counts from `summary.byType`; `create_checkpoint` before a large proposal when asked
  (FR-013)

---

## Phase 7: User Story 5 — Local mode (Priority: P3)

- [x] T029 [US5] Add `component_install_topology_dojo()` to `scripts/lib/install-steps.sh`:
  `read -r -p` gate; hosted branch installs nothing (a `url` entry) and prints where to mint the
  key and which scopes each story needs; local branch requires `node` ≥ 18 and `npm` (skip
  with a warning otherwise) and an operator-supplied clone at `TOPOLOGY_DOJO_DIR` with
  `package.json` and an installed `node_modules` — it **never** runs `git clone` or `npm ci`
  itself while upstream is unlicensed (research R9; FR-021), and prints what to pre-stage when the
  directory is missing or incomplete; on success `openclaw mcp set topology-dojo-mcp
  '{"command":"npm","args":["run","--silent","mcp"],"cwd":"<TOPOLOGY_DOJO_DIR>"}'` guarded by
  `command -v openclaw`; echoes the `.env` lines (`docs/ADDING-AN-MCP.md` step 4). Prerequisite
  for any future auto-clone branch: a LICENSE in `robertsonc/topology-dojo`
- [x] T030 [P] [US5] Create `tests/topology-dojo/live_local.sh` — when `TOPOLOGY_DOJO_DIR` is
  set and `node_modules` exists, drive `npm run --silent mcp` through `scripts/mcp-call.py`:
  `import_topology(small.json)` → `validate_topology` → `render_svg`, assert `valid: true` and an
  `<svg` prefix; otherwise print the skip reason. Never in the default suite path
- [x] T030a [P] [US5] Air-gapped acceptance: `live_local.sh` runs the loop above under an
  environment that makes network access fail loudly (`npm_config_offline=true`,
  `HTTP_PROXY`/`HTTPS_PROXY` pointed at an unroutable address, `--network-family` where
  supported) and asserts it still passes — proving install-time registration plus the sync loop
  need no connectivity once the clone is pre-staged (US5 scenario 3)
- [x] T031 [US5] SKILL.md local-mode notes: drafts are process-lifetime, the JSON artifact is the
  record, re-import path (`import_topology` with `format: "topology-dojo"`)

---

## Phase 8: User Story 6 — Routing boundary (Priority: P2)

- [x] T032 [US6] SOUL.md: bump the identity line to **228 skills** backed by 173 MCP servers
  (computed 173 after T001 — state in the PR that the prior 172-vs-173 drift is closed by this
  addition, not by editing the claim) and line ~765's "all 228 skills"; add a
  `### Topology Dojo Visualization Skills (1)` section in the spec 122 form with the boundary:
  Topology Dojo for validated, re-syncable, shareable, collaborative topology documents; draw.io
  for `.drawio`/Confluence/Visio; three.js/UE5/Blender/World Labs for exploration and
  presentation; Markmap for hierarchy; UML for protocol/sequence (FR-017, SC-007)
- [x] T033 [P] [US6] `workspace/skills/drawio-diagram/SKILL.md`: add a "When to use Topology Dojo
  instead" row to "When to Use Each Mode" and a bullet in "Integration with Other Skills"
- [x] T034 [P] [US6] `workspace/skills/document-generation/SKILL.md:122` and
  `network-report-documents/SKILL.md:84,109`: add `topology-dojo-diagram` to the embed-never-redraw
  routing rows (embeds the `.svg` artifact); `browser-viz-verify/SKILL.md:15,116`: add Topology
  Dojo SVG to the producers list; `msgraph-visio`, `claroty-ot-topology`, `uml-diagram:379-402`,
  `markmap-viz:76`: one boundary line each (FR-017/018)
- [x] T035 [P] [US6] `run-tests.sh` asserts the boundary language exists in SOUL.md, both
  SKILL.md files and `document-generation/SKILL.md`

---

## Phase 9: Polish & Cross-Cutting Concerns

- [x] T036 [P] `README.md`: capability bullet (~292), architecture ASCII UTILITIES block (~489),
  MCP Servers table row appended (`Topology Dojo | robertsonc/topology-dojo | Remote HTTP (API key) or stdio (local clone) | Validated, re-syncable, shareable topology documents`),
  `## Skills (228)`, skill table row under Reference & Utility (and fix that heading's count to
  the real row count), project tree line, Topology Discovery workflow block (~1910),
  `browser-viz-verify` row (~1161); leave `## MCP Servers (173)` and the two 173 prose claims as
  they are (computed value now matches)
- [x] T037 [P] `SOUL-SKILLS.md`: `### topology-dojo-diagram` operational paragraph beside
  `### drawio-diagram` (~929) and an index-table row (~1493)
- [x] T038 [P] `TOOLS.md`: `## Topology Dojo (topology-dojo-mcp)` section — modes, tool table
  (contracts §Tools), rate limits, `### Boundaries`, and a one-paragraph note that the registered
  entry is a declared exception to `docs/ADDING-AN-MCP.md`'s Remote/OAuth default (research R13);
  add `topology-dojo-diagram` to the four-name diagram list at ~616
- [x] T039 [P] `scripts/verify-catalog-coverage.py`: `GROUPED_CONFIG_EXACT["topology-dojo-mcp"] = "topology-dojo"`
- [x] T040 [P] `ui/netclaw-visual/server.js`: node entry
  (`{ id: 'topology-dojo', name: 'Topology Dojo', category: 'Visualization', prefixes: ['topology-dojo-'], color: '#4cc9f0', transport: 'mixed', toolEstimate: 34, description: '…' }`),
  annotation entry (`env: ['TOPOLOGY_DOJO_MCP_URL','TOPOLOGY_DOJO_MODE','TOPOLOGY_DOJO_DIR']`,
  `files: ['workspace/skills/topology-dojo-diagram/']`), and add `'topology-dojo'` to the
  `'diagram'` and `'topology'` keyword arrays (~1812/1825)
- [x] T041 [P] `scripts/in2n-profiles.py`: add `"topology-dojo-diagram"` to the `viz` profile's
  `exact` list
- [x] T042 `python3 scripts/check-package-references.py --refresh` — expected to find no new
  package reference (the skill invokes nothing via `npx`/`uvx`; local mode runs the operator's
  own `npm run mcp`)
- [x] T043 Run the gates and record results in `checklists/requirements.md`:
  `python3 scripts/verify-spec-artifacts.py`, `python3 scripts/reconcile-mcp.py` (exit 0),
  `python3 scripts/run-contract-tests.py --suite topology-dojo --prepare`,
  `python3 tests/runner/test_run_contract_tests.py`, `python3 scripts/trace-skill.py topology-dojo-diagram`,
  `python3 scripts/check-server-startup.py --only topology-dojo-mcp` (timeout = success)
- [x] T044 GAIT session log for the implementation session (constitution checklist)
- [x] T045 Draft the WordPress milestone post (Principle XVII) — one paragraph on why a validated,
  re-syncable document beats a one-shot picture, with the hosted/local split
- [ ] T046 PR description: file the four Topology Dojo follow-ups from plan.md (license, MCP
  `export_drawio`, headless credential path, hosted client-config docs) as issues on
  `robertsonc/topology-dojo` and link them

---

## Dependencies & Execution Order

### Phase Dependencies

- Phase 1 has no dependencies; T002–T004 run in parallel with T001.
- Phase 2: T005/T006 need a gateway and a hosted login respectively and can run while T007–T009
  proceed offline. T012 and T027 depend on T006's answer; T001's final shape depends on T005.
- Phase 3 (US1) depends on T007–T009; T010/T011 before T012–T015.
- Phase 4 (US2) depends on T012; T016/T017 before T018–T020.
- Phase 5 (US3) depends on T013 (artifact path language) only; independent of US2.
- Phase 6 (US4) depends on T006 and T018.
- Phase 7 (US5) depends on T001; T030 can be written any time after T008.
- Phase 8 (US6) depends on T013/T014 existing so the boundary text references real sections.
- Phase 9 after all stories; T043 last.

### Parallel Opportunities

- T002, T003, T004 with T001
- T007, T008, T009 with T005/T006
- All "Tests for User Story N" tasks within a phase
- T033–T035, T036–T041 across files

## Implementation Strategy

### MVP First (US1 + US2)

1. Phases 1–2, then US1 (T010–T015) and US2 (T016–T020). At that point NetClaw can document any
   discovered topology and keep it updated, in either mode, with an offline-tested converter.
2. Validate against a hosted login and, separately, a local clone (T030).

### Incremental Delivery

- US3 (share) and US4 (workspace) are independent of each other and each adds one SKILL.md
  section plus one helper.
- US5 is installer-only once the converter exists.
- US6 and Polish are documentation coherence and are what `reconcile-mcp.py` gates; do them
  before the PR leaves draft.

## Notes

- Total tasks: 47. Two are research verifications (T005, T006) whose outcomes are written back
  into `research.md` before the dependent tasks start.
- Revision note 2 (2026-09-20, after Topology Dojo #247/#248): hosted auth is the API key only
  (bridge dropped: T001/T003/T005/T011/T014/T015/T029/T036/T042); US4 batches are
  `element.upsert` (T006/T025/T027/T028); the Sync Diff reads the sourced-element listing and
  `created` from batch results (T017/T018/T019).
- Revision note (2026-09-20, after the owner's adversarial review of PR #1): T007/T008/T010
  now target the real canonical model through an adapter with fixtures serialized from
  `_build_snapshot()`; T013 persists the read-back document; T017–T019 diff from
  `get_topology(pageIndex)` with counters derived locally and a stable document identity;
  T021/T024 scan the fetched document recursively; T029 no longer clones or installs; T030a
  added for the air-gapped path; T038 records the ADDING-AN-MCP exception.
- `docs/ADDING-AN-MCP.md`'s "five more artifacts" for iN2N members are out of scope (research R12);
  T041 keeps a future member regeneration correct.
