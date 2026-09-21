#!/usr/bin/env bash
# Offline contract harness for the Topology Dojo integration (spec 124).
#
# TWO RULES
#
# 1. **No network, no account.** Hosted Topology Dojo needs a user-minted API key and is never
#    touched here. The optional local check (`live_local.sh`) runs the operator's OWN clone over
#    stdio and only when TOPOLOGY_DOJO_DIR points at one — still no network.
#
# 2. **Exit codes are captured DIRECTLY, never through a pipe.** `cmd | tail` reports tail's
#    status, not cmd's — that mistake misdiagnosed spec 075's central premise.
#
# What is tested: the converter/adapter/share-guard code (unit, from fixtures serialized by the
# REAL source adapters), the registration shape, and the SKILL.md safety language — for a remote
# MCP the skill *is* the implementation, so its prose is asserted the same way Globalping's is.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${NETCLAW_PY:-python3}"
SKILL_DIR="$REPO_ROOT/workspace/skills/topology-dojo-diagram"
SKILL="$SKILL_DIR/SKILL.md"
CONFIG="$REPO_ROOT/config/openclaw.json"
PASS=0
FAIL=0

check() {  # check <label> <rc>
    if [ "$2" -eq 0 ]; then
        echo "  ok   $1"; PASS=$((PASS + 1))
    else
        echo "  FAIL $1"; FAIL=$((FAIL + 1))
    fi
}

echo "### Unit: adapter, converter, share guard (FR-001..005, FR-008a, FR-012, FR-014) ###"
PYTHONPATH="$SKILL_DIR:${PYTHONPATH:-}" "$PY" -m unittest discover -s "$REPO_ROOT/tests/topology-dojo" -p 'test_*.py' -q
check "unittest suite (fixtures serialized from the real _build_snapshot())" $?
echo

echo "### Registration (FR-010, FR-011, FR-019, R13) ###"
"$PY" -c "
import json
e = json.load(open('$CONFIG'))['mcpServers']['topology-dojo-mcp']
assert e['url'].startswith('\${TOPOLOGY_DOJO_MCP_URL:-https://'), e['url']
assert e['headers']['Authorization'] == 'Bearer \${TOPOLOGY_DOJO_API_KEY}', e['headers']
assert 'command' not in e and 'args' not in e, e
" >/dev/null 2>&1
check "url + bearer by variable reference, no command/args" $?

! grep -qE '"Authorization"[^,]*Bearer (tdk_|[A-Za-z0-9]{16,})' "$CONFIG"
check "no literal key in config (FR-011, SC-006)" $?

! git -C "$REPO_ROOT" grep -qE 'tdk_[a-z0-9]{10,}_[A-Za-z0-9_-]{43}' -- . 2>/dev/null
check "no literal tdk_ API key in any tracked file (SC-006)" $?

[ ! -d "$REPO_ROOT/mcp-servers/topology-dojo" ] && [ ! -d "$REPO_ROOT/mcp-servers/topology-dojo-mcp" ]
check "nothing vendored from the Topology Dojo repository (FR-021, R9)" $?

! grep -rq "mcp-remote" "$SKILL_DIR" "$REPO_ROOT/specs/124-topology-dojo-provider/contracts" 2>/dev/null
check "no OAuth bridge anywhere in the skill or contract (R2, decision 2026-09-20)" $?
echo

echo "### The skill exists and documents the loop (FR-006..008, FR-015, FR-016) ###"
[ -f "$SKILL" ]
check "SKILL.md present" $?
for word in "pageIndex" "get_topology" "validate_topology" "balance_topology" "inspect_render" "render_svg" "import_topology" "edit_topology" "upsert_by_source" "sources"; do
    grep -qF "$word" "$SKILL"
    check "names $word" $?
done
grep -qi "render once\|once per page" "$SKILL"
check "renders once per page per sync (FR-007)" $?
grep -qF "workspace/output/topology-dojo/" "$SKILL"
check "writes artifacts to the persistent output directory (FR-008)" $?
grep -qi "read back\|read-back" "$SKILL"
check "persists the read-back document, not the pre-import object (FR-008)" $?
grep -qF "/keys" "$SKILL"
check "points at /keys for minting and revoking the API key (FR-011)" $?
grep -qi "tools/list" "$SKILL"
check "reads a scope gap from tools/list, not a failed call (FR-011)" $?
grep -qF "TOPOLOGY_DOJO_API_KEY" "$SKILL"
check "names the key variable (FR-011)" $?
grep -qi "local mode" "$SKILL" && grep -qi "no sharing\|cannot share\|not available in local" "$SKILL"
check "documents local-mode capability gaps (FR-015)" $?
grep -qF "layout_guidelines" "$SKILL" && grep -qF "get_authoring_guidance" "$SKILL"
check "consults layout guidelines and authoring guidance (FR-016)" $?
echo

echo "### Re-sync semantics (FR-004, FR-004a, FR-008a, FR-009) ###"
grep -qF "document_identity\|document identity" "$SKILL" || grep -qi "stable identity" "$SKILL"
check "locates documents by stable identity, never the snapshot id (FR-004a)" $?
grep -qF "identity_stem" "$SKILL" && grep -qF "latest_artifact" "$SKILL"
check "artifact lookup keys on identity_stem / latest_artifact, not a snapshot-derived stem" $?
grep -qi "MUST omit" "$SKILL" && grep -qi "pre-share scan" "$SKILL"
check "full read-back and pre-share scan omit pageIndex (whole document)" $?
grep -qF -- "--site" "$SKILL" && grep -qF -- "--unassigned" "$SKILL" && grep -qi "once per page" "$SKILL"
check "split-by-site re-sync is scoped page by page" $?
grep -qi "cross-site link" "$SKILL"
check "cross-site links are reported, never silently dropped" $?
grep -qF "R1" "$SKILL" && grep -qF "edge_1" "$SKILL"
check "source ids exact-case, element ids hashed (no slug/case merges)" $?
grep -qi "absent at source" "$SKILL"
check "reports absent-at-source and never removes without confirmation" $?
grep -qF "created" "$SKILL" && grep -qi "summary.byType\|byType" "$SKILL"
check "takes created counts from batch results / summary.byType (FR-008a)" $?
grep -qF "set_legend" "$SKILL" && grep -qi "DOCUMENTED" "$SKILL" && grep -qi "MISMATCH" "$SKILL"
check "reconciliation colours + legend (FR-009)" $?
echo

echo "### Share gate — the one outward publication (FR-012, XIV) ###"
grep -qi "30 days\|30-day" "$SKILL"
check "says the link is public for 30 days" $?
grep -qi "confirmed=True\|confirmed: true\|assert_confirmed" "$SKILL"
check "code-level confirmation guard named" $?
grep -qi "scan_internal_addresses\|internal address" "$SKILL"
check "internal-address scan before publishing" $?
grep -qi "immediately before" "$SKILL"
check "scan runs on the document fetched immediately before share_topology" $?
grep -qF "gait_record_turn" "$SKILL"
check "GAIT record for publish and revoke (Principle IV)" $?
grep -qi "new URL\|new link\|does not renew" "$SKILL"
check "re-publishing mints a new URL" $?
grep -qi "retry after\|rate.limit" "$SKILL"
check "rate limit is reported, not retried" $?
echo

echo "### Workspace path (FR-013, R7) ###"
grep -qF "element.upsert" "$SKILL"
check "workspace writes are element.upsert operations" $?
grep -qi "operationSchemaRevision" "$SKILL"
check "checks operationSchemaRevision >= 2" $?
grep -qF "propose_workspace_changes" "$SKILL" && grep -qi "proposal" "$SKILL"
check "proposals are the default" $?
grep -qi "lease" "$SKILL" && grep -qF "apply_workspace_changes" "$SKILL"
check "direct apply only with a stated live lease" $?
grep -qi "migrated" "$SKILL"
check "legacy drafts are refused with the browser hand-off instruction" $?
grep -qi "conflict" "$SKILL"
check "conflicts re-read changes before one retry" $?
grep -qF "sourcedOnly" "$SKILL"
check "workspace diff uses sourcedOnly listings" $?
echo

echo "### Routing boundary (FR-017, SC-007) ###"
grep -qi "drawio-diagram" "$SKILL" && grep -qi "Confluence\|Visio" "$SKILL"
check "states when draw.io is the right tool" $?
for other in "threejs-network-viz" "markmap-viz" "uml-diagram"; do
    grep -qF "$other" "$SKILL"
    check "names the $other boundary" $?
done
for f in SOUL.md workspace/skills/drawio-diagram/SKILL.md workspace/skills/document-generation/SKILL.md; do
    grep -qF "topology-dojo" "$REPO_ROOT/$f"
    check "$f carries the boundary/handoff" $?
done
echo

if [ -n "${TOPOLOGY_DOJO_DIR:-}" ]; then
    echo "### LOCAL — operator-supplied clone over stdio (US5) ###"
    bash "$REPO_ROOT/tests/topology-dojo/live_local.sh"
    check "local stdio loop: import → validate → sources → render, no network" $?
else
    echo "### LOCAL — SKIPPED (set TOPOLOGY_DOJO_DIR to a prepared Topology Dojo clone) ###"
fi
echo

echo "======================================"
echo " PASS: $PASS   FAIL: $FAIL"
echo "======================================"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
