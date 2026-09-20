# Specification Quality Checklist: Topology Dojo Topology Documentation Provider

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-20
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs) in spec.md beyond named tool
      surfaces the user stories depend on
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain (four clarifications resolved in-session)
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic where possible; SC-005/SC-008 name the repo's own
      gates by design
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded (research R12)
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Review round 1 (2026-09-20, owner's adversarial review of PR #1)

All eleven findings verified against primary sources and addressed in the artifacts:

- [x] data-model.md now consumes the real canonical dataclasses (`link_id`, `endpoint_a/b`,
      `interface_name`, `source_label`, `created_at`) through an explicit adapter + optional overlay
- [x] stable document identity replaces the per-run `snapshot_id` in titles and lookups (FR-004a)
- [x] Sync Diff fetches pages with `get_topology(pageIndex)`; summary form never used for diffs
- [x] created/updated/unchanged derived locally, never from `edit_topology` results (FR-008a)
- [x] the `.json` artifact is the read-back canonical document after tidy (FR-008)
- [x] share scan is recursive over the fetched document, link `subnet` included (FR-012)
- [x] sanitizer is the union denylist, applied recursively (FR-014)
- [x] link identity prefers a real `link_id`; `link-<n>` treated as absent; fallback flagged
- [x] "no GitHub identity" and "air-gapped" separated; T030a no-network acceptance test
- [x] installer never clones/installs while upstream is unlicensed (FR-021, T029)
- [x] registered Remote/OAuth entry declared as an exception to `docs/ADDING-AN-MCP.md` (R13, FR-019)
- [ ] CI corroboration: the fork has GitHub Actions disabled (no workflow runs exist on any
      branch), so `verify-spec-artifacts.py` is only verified locally until the branch is opened
      against a repository where the workflow runs

## Rework round 2 (2026-09-20, after Topology Dojo #247 and #248)

- [x] hosted auth = user-minted API key by variable reference, the only hosted path; `mcp-remote`
      bridge, headless recipe and token-cache guidance removed (FR-011, R2, R13)
- [x] workspace writes = `element.upsert` operations; NetClaw never resolves workspace ids
      (FR-013, R7, T006/T025/T027/T028)
- [x] Sync Diff input = `get_topology sources:true` / `get_workspace_elements sourcedOnly:true`;
      `created` taken from batch results (FR-008a, R5, T017/T018/T019)

## Open items carried into implementation

- [ ] research R2/R7: the target deployment runs Topology Dojo with #247 (API keys) and #248
      (`element.upsert`, sourced listings) merged and `API_KEYS_ENABLED` active — verified by T005;
      hosted mode is unavailable until then, by design (no bridge fallback)
- [ ] Topology Dojo license — requested in the PR (research R9); not a blocker for the hosted
      mode or for the converter, a blocker for calling local mode a first-class install

## Gate results (T043, 2026-09-20, implementation session)

- [x] `scripts/verify-spec-artifacts.py` — PASS (111 specs checked)
- [x] `scripts/reconcile-mcp.py` — `docs` surface now PASS (claims 173, computed 173: the
      pre-existing 172-vs-173 drift is closed by this registration, not by editing the claim);
      `catalog`, `dependencies`, `meraki-ids`, `packages`, `portability` PASS. Overall exit is 1
      **only** because the `startup` surface reports servers whose Python modules are absent in
      this container (`mcp`, `fastmcp`, `httpx`, `networkx` …) — identical on the pre-change tree;
      `topology-dojo-mcp` itself is not among them
- [x] `scripts/run-contract-tests.py --suite topology-dojo --prepare` — PASS (offline, 0.8 s);
      live block reports `NEEDS_LIVE_CREDENTIALS: TOPOLOGY_DOJO_DIR` as designed
- [x] `tests/topology-dojo/run-tests.sh` — 50 checks, 0 failures (35 unit tests + registration +
      SKILL.md language + routing boundary)
- [x] `tests/runner/test_run_contract_tests.py` — 17 passed
- [x] `scripts/check-server-startup.py --only topology-dojo-mcp` — PASS (remote entry, skipped by
      design; recorded exception)
- [x] `scripts/verify-catalog-coverage.py` — PASS (108 catalog entries, 110 registered)
- [x] `scripts/verify-inventory-counts.py` — PASS (228 skills, 173 MCP integrations)
- [x] `scripts/trace-skill.py topology-dojo-diagram` — `topology-dojo-mcp` registered and
      installable (installer component `topology-dojo`)
- [x] `scripts/check-package-references.py --refresh` — no new package reference (the skill
      invokes nothing via `npx`/`uvx`); the refreshed timestamp was not committed
- [ ] T005 (hosted verification against the target deployment) — **not run here**: needs a
      user-minted key and `API_KEYS_ENABLED` on production, which is the operator's action after
      Topology Dojo #247/#248 are deployed. The offline suite and local mode are what this branch
      proves; hosted mode is unavailable until then, by design
