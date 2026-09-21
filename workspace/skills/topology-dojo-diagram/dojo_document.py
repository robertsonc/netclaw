#!/usr/bin/env python3
"""
dojo_document.py — spec 124 (Topology Dojo topology documentation provider).

Deterministic converter from an AdaptedSnapshot (see snapshot_adapter.py) into:

  * a native Topology Dojo document for `import_topology` (first sync),
  * `edit_topology` batches of `upsert_by_source` operations (private-draft re-sync),
  * `propose_workspace_changes` batches of `element.upsert` operations (shared workspace,
    Topology Dojo proposal 0006, operationSchemaRevision 2),
  * a Sync Diff computed from the sourced-element listing (`get_topology sources:true` or
    `get_workspace_elements sourcedOnly:true`) before any batch is sent.

The LLM never hand-writes element operations: it runs this module (see the CLI at the bottom)
and forwards the JSON it prints to the MCP tools. Stdlib only. No network.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from snapshot_adapter import (
    AdaptedDevice,
    AdaptedLink,
    AdaptedSnapshot,
    adapt,
    load_overlay,
    slug,
)

log = logging.getLogger("topology_dojo.dojo_document")

# Canonical NetClaw role → Topology Dojo built-in node type (research R4).
ROLE_TO_TYPE = {
    "router": "router",
    "switch": "switch",
    "firewall": "firewall",
    "load_balancer": "loadbalancer",
    "client": "host",
    "unclassified": "server",
}
# Canonical operational state → Topology Dojo node status.
STATE_TO_STATUS = {"healthy": "ok", "degraded": "warn", "down": "down", "unknown": "unknown"}
# netbox-reconcile categories → link colour (FR-009; NetClaw's existing draw.io convention).
RECONCILIATION_COLOR = {
    "DOCUMENTED": "#2e7d32",
    "UNDOCUMENTED": "#f9a825",
    "MISSING": "#c62828",
    "MISMATCH": "#ef6c00",
}
# Role tiers for the initial, stable placement (top → bottom).
ROLE_TIER = {"firewall": 0, "router": 0, "load_balancer": 1, "switch": 1, "client": 2, "unclassified": 2}

DRAFT_MAX_OPS = 200
WORKSPACE_MAX_OPS = 250
WORKSPACE_MAX_BYTES = 512 * 1024

# Layout constants aligned with Topology Dojo's layout_guidelines grid (40 px) and minimum gap.
_GRID = 40
_COL = 160
_ROW = 180
_MARGIN = 120
_BASE_W, _BASE_H = 1050, 700

# Public projection of the document contract this converter emits (schema drift check).
DOCUMENT_KEYS = {"title", "pages", "customNodes", "legend"}
PAGE_KEYS = {"id", "name", "viewBox", "nodes", "links", "anchors", "zones", "flowPaths", "policyMarkers"}
NODE_KEYS = {"id", "type", "x", "y", "label", "sublabel", "status", "meta", "source"}
LINK_KEYS = {"id", "type", "from", "to", "label", "fromLabel", "toLabel", "vlan", "subnet", "bandwidth", "transport", "showMeta", "color", "source"}
ZONE_KEYS = {"id", "nodes", "label", "source"}


def node_id(hostname: str) -> str:
    return f"n-{slug(hostname)}"


def link_element_id(identity: str) -> str:
    return f"l-{slug(identity)}"


def zone_id(site: str) -> str:
    return f"z-{slug(site)}"


def _source(system: str, kind: str, ident: str, fetched_at: Optional[str]) -> dict:
    src = {"system": system, "kind": kind, "id": ident}
    if fetched_at:
        src["fetchedAt"] = str(fetched_at)
    return src


def place(devices: list[AdaptedDevice]) -> tuple[dict[str, tuple[int, int]], str]:
    """Role-tiered rows on the guideline grid; returns positions and the viewBox."""
    rows: dict[int, list[AdaptedDevice]] = {0: [], 1: [], 2: []}
    for d in devices:
        rows[ROLE_TIER.get(d.role, 2)].append(d)
    widest = max((len(r) for r in rows.values()), default=1)
    width = max(_BASE_W, _MARGIN * 2 + max(1, widest) * _COL)
    used_rows = [t for t in (0, 1, 2) if rows[t]]
    height = max(_BASE_H, _MARGIN * 2 + max(1, len(used_rows)) * _ROW)
    positions: dict[str, tuple[int, int]] = {}
    for row_index, tier in enumerate(used_rows):
        members = sorted(rows[tier], key=lambda d: d.hostname)
        span = len(members) * _COL
        start = (width - span) // 2 + _COL // 2
        y = _MARGIN + row_index * _ROW
        for i, d in enumerate(members):
            x = start + i * _COL
            positions[d.hostname] = (round(x / _GRID) * _GRID, round(y / _GRID) * _GRID)
    return positions, f"0 0 {width} {height}"


def node_fields(dev: AdaptedDevice, pos: tuple[int, int]) -> dict:
    fields: dict = {
        "type": ROLE_TO_TYPE.get(dev.role, "server"),
        "x": pos[0],
        "y": pos[1],
        "label": dev.hostname,
    }
    if dev.platform:
        fields["sublabel"] = dev.platform
    if dev.state:
        fields["status"] = STATE_TO_STATUS[dev.state]
    meta = {k: v for k, v in dev.meta.items() if k not in ("platform", "model")}
    if meta:
        fields["meta"] = meta
    return fields


def link_fields(link: AdaptedLink) -> dict:
    fields: dict = {"type": "line", "from": node_id(link.a), "to": node_id(link.b)}
    if link.label and not link.label.startswith(f"{link.a}"):  # skip the model's auto-label
        fields["label"] = link.label
    if link.a_interface:
        fields["fromLabel"] = link.a_interface
    if link.b_interface:
        fields["toLabel"] = link.b_interface
    show_meta = False
    for key in ("vlan", "subnet", "bandwidth", "transport"):
        value = getattr(link, key)
        if value:
            fields[key] = value
            show_meta = True
    if show_meta:
        fields["showMeta"] = True
    if link.reconciliation:
        fields["color"] = RECONCILIATION_COLOR[link.reconciliation]
    return fields


def _devices_for(adapted: AdaptedSnapshot, site: Optional[str]) -> list[AdaptedDevice]:
    if site is None:
        return list(adapted.devices)
    return [d for d in adapted.devices if d.site == site]


def _links_for(adapted: AdaptedSnapshot, devices: list[AdaptedDevice]) -> list[AdaptedLink]:
    hosts = {d.hostname for d in devices}
    return [l for l in adapted.links if l.a in hosts and l.b in hosts]


def _page(adapted: AdaptedSnapshot, page_id: str, name: str, site: Optional[str]) -> dict:
    fetched = adapted.provenance.get("created_at")
    devices = _devices_for(adapted, site)
    links = _links_for(adapted, devices)
    positions, view_box = place(devices)
    nodes = [
        {"id": node_id(d.hostname), **node_fields(d, positions[d.hostname]),
         "source": _source(adapted.system, "device", d.hostname.lower(), fetched)}
        for d in devices
    ]
    link_elems = [
        {"id": link_element_id(l.identity), **link_fields(l),
         "source": _source(adapted.system, "link", l.identity, fetched)}
        for l in links
    ]
    zones = []
    if site is None:
        for s in adapted.sites:
            members = [node_id(d.hostname) for d in devices if d.site == s]
            if members:
                zones.append({"id": zone_id(s), "nodes": members, "label": s,
                              "source": _source(adapted.system, "site", s, fetched)})
    return {
        "id": page_id,
        "name": name,
        "viewBox": view_box,
        "nodes": nodes,
        "links": link_elems,
        "anchors": [],
        "zones": zones,
        "flowPaths": [],
        "policyMarkers": [],
    }


def build_document(adapted: AdaptedSnapshot, *, split_by_site: bool = False) -> dict:
    """The native document sent on first import. Never what is saved (FR-008: save the read-back)."""
    if split_by_site and adapted.sites:
        pages = [_page(adapted, f"p-{i}", site, site) for i, site in enumerate(adapted.sites)]
        orphans = [d for d in adapted.devices if not d.site]
        if orphans:
            pages.append(_page(adapted, f"p-{len(pages)}", "Unassigned", None))
            pages[-1]["nodes"] = [n for n in pages[-1]["nodes"] if n["id"] in {node_id(d.hostname) for d in orphans}]
            keep = {n["id"] for n in pages[-1]["nodes"]}
            pages[-1]["links"] = [l for l in pages[-1]["links"] if l["from"] in keep and l["to"] in keep]
            pages[-1]["zones"] = []
    else:
        pages = [_page(adapted, "p-0", "Topology", None)]
    has_reconciliation = any(l.reconciliation for l in adapted.links)
    doc: dict = {"title": adapted.title, "pages": pages, "customNodes": []}
    if has_reconciliation:
        doc["legend"] = {"show": True, "position": "br"}
    return doc


def _chunk(ops: list[dict], max_ops: int, max_bytes: Optional[int]) -> list[list[dict]]:
    batches: list[list[dict]] = []
    current: list[dict] = []
    for op in ops:
        candidate = current + [op]
        too_many = len(candidate) > max_ops
        too_big = max_bytes is not None and len(json.dumps(candidate).encode("utf-8")) > max_bytes
        if current and (too_many or too_big):
            batches.append(current)
            current = [op]
        else:
            current = candidate
    if current:
        batches.append(current)
    return batches


def _ordered_ops(adapted: AdaptedSnapshot, site: Optional[str], make) -> list[dict]:
    """Nodes, then links, then zones — so chunking at any boundary keeps references valid."""
    fetched = adapted.provenance.get("created_at")
    devices = _devices_for(adapted, site)
    links = _links_for(adapted, devices)
    positions, _ = place(devices)
    ops = [
        make("node", _source(adapted.system, "device", d.hostname.lower(), fetched),
             {"id": node_id(d.hostname), **node_fields(d, positions[d.hostname])})
        for d in devices
    ]
    ops += [
        make("link", _source(adapted.system, "link", l.identity, fetched),
             {"id": link_element_id(l.identity), **link_fields(l)})
        for l in links
    ]
    if site is None:
        for s in adapted.sites:
            members = [node_id(d.hostname) for d in devices if d.site == s]
            if members:
                ops.append(make("zone", _source(adapted.system, "site", s, fetched),
                                {"id": zone_id(s), "nodes": members, "label": s}))
    return ops


def build_upsert_batches(adapted: AdaptedSnapshot, *, page_index: int = 0, site: Optional[str] = None,
                         max_ops: int = DRAFT_MAX_OPS, max_bytes: Optional[int] = None) -> list[list[dict]]:
    """`edit_topology` batches of `upsert_by_source` ops for a private draft (kind is singular)."""
    def make(kind: str, source: dict, fields: dict) -> dict:
        set_fields = {k: v for k, v in fields.items() if k != "id"}
        return {"op": "upsert_by_source", "pageIndex": page_index, "kind": kind, "source": source, "set": set_fields}
    return _chunk(_ordered_ops(adapted, site, make), max_ops, max_bytes)


def build_workspace_batches(adapted: AdaptedSnapshot, *, page_id: str, site: Optional[str] = None,
                            max_ops: int = WORKSPACE_MAX_OPS, max_bytes: int = WORKSPACE_MAX_BYTES) -> list[list[dict]]:
    """`propose_workspace_changes` batches of `element.upsert` ops (kind is the plural collection)."""
    plural = {"node": "nodes", "link": "links", "zone": "zones"}
    def make(kind: str, source: dict, fields: dict) -> dict:
        return {"type": "element.upsert", "pageId": page_id, "kind": plural[kind], "source": source, "element": fields}
    return _chunk(_ordered_ops(adapted, site, make), max_ops, max_bytes)


@dataclass
class SyncDiff:
    to_create: list[dict] = field(default_factory=list)
    to_update: list[dict] = field(default_factory=list)
    unchanged: list[dict] = field(default_factory=list)
    absent_at_source: list[dict] = field(default_factory=list)
    ambiguous_links: list[dict] = field(default_factory=list)

    def counts(self) -> dict:
        return {
            "to_create": len(self.to_create),
            "to_update": len(self.to_update),
            "unchanged": len(self.unchanged),
            "absent_at_source": len(self.absent_at_source),
            "ambiguous_links": len(self.ambiguous_links),
        }


def _intended(adapted: AdaptedSnapshot) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for d in adapted.devices:
        out[("device", d.hostname.lower())] = {"kind": "nodes", "label": d.hostname}
    for l in adapted.links:
        out[("link", l.identity)] = {"kind": "links", "label": link_fields(l).get("label")}
    for s in adapted.sites:
        out[("site", s)] = {"kind": "zones", "label": s}
    return out


def diff_sourced(listing: list[dict], adapted: AdaptedSnapshot) -> SyncDiff:
    """
    Compare a sourced-element listing (`{id, kind, source, label?}` rows from `get_topology
    sources:true` or `get_workspace_elements sourcedOnly:true`; rows may also be `{kind, element}`
    as get_workspace_elements returns) against the adapted snapshot. The listing carries no
    geometry, so a geometry-only change is `unchanged` (FR-008a).
    """
    diff = SyncDiff()
    intended = _intended(adapted)
    seen: set[tuple[str, str]] = set()
    for row in listing:
        el = row.get("element") if isinstance(row.get("element"), dict) else row
        src = el.get("source") or {}
        if src.get("system") != adapted.system:
            continue
        key = (str(src.get("kind")), str(src.get("id")))
        entry = {"id": el.get("id"), "kind": row.get("kind") or el.get("kind"), "source": src, "label": el.get("label")}
        want = intended.get(key)
        if not want:
            diff.absent_at_source.append(entry)
            continue
        seen.add(key)
        if (want.get("label") or None) != (el.get("label") or None):
            diff.to_update.append({**entry, "intended_label": want.get("label")})
        else:
            diff.unchanged.append(entry)
    for key, want in intended.items():
        if key not in seen:
            diff.to_create.append({"kind": want["kind"], "source": {"system": adapted.system, "kind": key[0], "id": key[1]}, "label": want.get("label")})
    diff.ambiguous_links = [
        {"identity": l.identity, "a": l.a, "b": l.b, "label": l.label} for l in adapted.links if l.ambiguous
    ]
    return diff


def summarize_results(results: list[dict]) -> dict[str, Optional[int]]:
    """Created / updated / unchanged counts from ``edit_topology`` result rows.

    ``created`` is authoritative for creations. ``changed`` (Topology Dojo proposal 0006, review
    round 1) is false when an upsert was a logical no-op apart from ``source.fetchedAt``; when
    every upsert row carries it, ``updated`` and ``unchanged`` are exact. When any row lacks it
    (an older deployment), both are ``None`` and the caller falls back to the local Sync Diff.
    Absent-at-source and ambiguous links never come from results; only the diff can see them.
    """
    upserts = [r for r in results if isinstance(r, dict) and r.get("op") == "upsert_by_source"]
    created = sum(1 for r in upserts if r.get("created") is True)
    if any(not isinstance(r.get("changed"), bool) for r in upserts):
        return {"created": created, "updated": None, "unchanged": None}
    updated = sum(1 for r in upserts if r.get("changed") is True and r.get("created") is not True)
    unchanged = sum(1 for r in upserts if r.get("changed") is False)
    return {"created": created, "updated": updated, "unchanged": unchanged}


def count_created(results: list[dict]) -> int:
    """`created` per upsert op from an `edit_topology` result (Topology Dojo proposal 0006)."""
    return sum(1 for r in results if r.get("op") == "upsert_by_source" and r.get("created") is True)


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────

def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _adapted_from_args(args: argparse.Namespace) -> AdaptedSnapshot:
    overlay = load_overlay(_load_json(args.overlay)) if getattr(args, "overlay", None) else None
    return adapt(_load_json(args.snapshot), overlay)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Topology Snapshot → Topology Dojo converter (spec 124)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("document", help="native document for import_topology")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--overlay")
    p.add_argument("--split-by-site", action="store_true")

    p = sub.add_parser("upsert-batches", help="edit_topology batches of upsert_by_source ops")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--overlay")
    p.add_argument("--page-index", type=int, default=0)
    p.add_argument("--site")
    p.add_argument("--max-ops", type=int, default=DRAFT_MAX_OPS)

    p = sub.add_parser("workspace-batches", help="propose_workspace_changes batches of element.upsert ops")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--overlay")
    p.add_argument("--page-id", required=True)
    p.add_argument("--site")

    p = sub.add_parser("diff", help="Sync Diff from a sourced-element listing")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--overlay")
    p.add_argument("--listing", required=True, help="JSON: get_topology sources:true result, or a list of rows")

    p = sub.add_parser("identity", help="stable document identity + title")
    p.add_argument("--snapshot", required=True)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    try:
        adapted = _adapted_from_args(args)
        if args.command == "document":
            out: Any = build_document(adapted, split_by_site=args.split_by_site)
        elif args.command == "upsert-batches":
            out = build_upsert_batches(adapted, page_index=args.page_index, site=args.site, max_ops=args.max_ops)
        elif args.command == "workspace-batches":
            out = build_workspace_batches(adapted, page_id=args.page_id, site=args.site)
        elif args.command == "diff":
            listing = _load_json(args.listing)
            rows: list[dict] = []
            if isinstance(listing, dict) and "pages" in listing:
                for page in listing["pages"]:
                    rows.extend(page.get("elements") or [])
            elif isinstance(listing, dict) and "elements" in listing:
                rows = list(listing["elements"])
            else:
                rows = list(listing)
            d = diff_sourced(rows, adapted)
            out = {"counts": d.counts(), **d.__dict__}
        else:
            out = {"document_identity": adapted.document_identity, "title": adapted.title, "system": adapted.system,
                   "provenance": adapted.provenance, "artifact_stem": f"{slug(adapted.document_identity)}-{slug(adapted.provenance.get('snapshot_id') or 'snapshot')}"}
    except Exception as exc:  # noqa: BLE001 — CLI boundary: report what failed and why
        log.error("%s: %s", type(exc).__name__, exc)
        return 2
    json.dump(out, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
