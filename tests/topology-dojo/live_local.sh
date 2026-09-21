#!/usr/bin/env bash
# Spec 124 US5 / T030 / T030a — drive the operator's OWN Topology Dojo clone over stdio through
# scripts/mcp-call.py with the network forced off: import the small fixture's converted document,
# validate it, list its sourced elements, render it. Proves the local mode needs no connectivity
# once the clone is pre-staged (node_modules present). Never part of the default suite path.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIR="${TOPOLOGY_DOJO_DIR:-}"
[ -n "$DIR" ] || { echo "TOPOLOGY_DOJO_DIR unset"; exit 2; }
[ -f "$DIR/package.json" ] && [ -d "$DIR/node_modules" ] || { echo "clone at $DIR is not prepared (need package.json + node_modules)"; exit 2; }
command -v npm >/dev/null || { echo "npm missing"; exit 2; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
PYTHONPATH="$REPO_ROOT/workspace/skills/topology-dojo-diagram" python3 "$REPO_ROOT/workspace/skills/topology-dojo-diagram/dojo_document.py" \
    document --snapshot "$REPO_ROOT/tests/topology-dojo/fixtures/small.json" > "$TMP/doc.json" || exit 1

# Force any accidental network use to fail loudly (T030a).
export npm_config_offline=true HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 NO_PROXY=""
SERVER="npm --prefix $DIR run --silent mcp"
CALL="python3 $REPO_ROOT/scripts/mcp-call.py"

IMPORT_ARGS="$(python3 -c "import json,sys; print(json.dumps({'json': json.load(open(sys.argv[1])), 'format': 'topology-dojo'}))" "$TMP/doc.json")"
OUT="$($CALL "$SERVER" import_topology "$IMPORT_ARGS" 2>"$TMP/err")" || { cat "$TMP/err"; exit 1; }
ID="$(python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('id') or json.loads(d['content'][0]['text'])['id'])" <<<"$OUT" 2>/dev/null)" || { echo "no id in: $OUT"; exit 1; }
echo "imported topology $ID"
# The local stdio server holds drafts per process; each mcp-call.py spawn is a new process, so
# the remaining checks re-import and run inside one call chain via a tiny driver instead.
python3 - "$SERVER" "$TMP/doc.json" <<'PY' || exit 1
import json, os, subprocess, sys, shlex
server, doc_path = sys.argv[1], sys.argv[2]
proc = subprocess.Popen(shlex.split(server), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
def rpc(i, method, params):
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params}) + "\n"); proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line: raise SystemExit("server closed")
        try: msg = json.loads(line)
        except ValueError: continue
        if msg.get("id") == i: return msg
rpc(1, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "netclaw-test", "version": "0"}})
proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"); proc.stdin.flush()
def tool(i, name, args):
    r = rpc(i, "tools/call", {"name": name, "arguments": args})
    text = r["result"]["content"][0]["text"]
    if r["result"].get("isError"): raise SystemExit(f"{name}: {text}")
    try: return json.loads(text)
    except ValueError: return text
doc = json.load(open(doc_path))
tid = tool(2, "import_topology", {"json": doc, "format": "topology-dojo"})["id"]
v = tool(3, "validate_topology", {"topologyId": tid})
assert v["valid"] is True, v
listing = tool(4, "get_topology", {"topologyId": tid, "sources": True})
n = sum(len(p["elements"]) for p in listing["pages"])
assert n == 9, n
svg = tool(5, "render_svg", {"topologyId": tid, "pageIndex": 0})
assert svg.lstrip().startswith("<svg"), svg[:80]
print(f"validated, {n} sourced elements listed, svg {len(svg)} bytes — no network")
proc.stdin.close(); proc.terminate()
PY
