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
import hashlib
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
# Topology Dojo's advertised limit is 512 KiB, enforced on the input AND again on the normalized
# operations (`element.upsert` expands into `element.add`/`element.patch`: a minted id and the
# embedded source, ~30 bytes per op). Batches are sized with headroom so the second check can
# never reject what the first accepted.
WORKSPACE_LIMIT_BYTES = 512 * 1024
WORKSPACE_MAX_BYTES = 480 * 1024

# Page scope sentinel: the page holding devices that carry no site when a document is split by site.
UNASSIGNED = "__unassigned__"

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


def short_hash(text: str) -> str:
    """Six hex characters of SHA-1 over the exact original string (case and punctuation kept)."""
    return hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:6]


def element_id(prefix: str, original: str) -> str:
    """`<prefix>-<readable slug>-<hash of the exact original>`.

    The slug is lossy (`edge_1` and `edge-1`, `R1` and `r1` all slug alike), so on its own it
    can collapse distinct canonical objects into one Dojo element id. The hash of the exact
    original keeps ids readable *and* collision-resistant, and stable across discoveries.
    """
    return f"{prefix}-{slug(original)}-{short_hash(original)}"


def node_id(hostname: str) -> str:
    return element_id("n", hostname)


def link_element_id(identity: str) -> str:
    return element_id("l", identity)


def zone_id(site: str) -> str:
    return element_id("z", site)


def _assert_unique_ids(ids: list[str], what: str) -> None:
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            raise ValueError(f"{what} id collision after normalization: {i!r}")
        seen.add(i)


# ── Identity, artifact naming, lookup (FR-004a) ─────────────────────────────────────────────

def identity_stem(adapted: AdaptedSnapshot) -> str:
    """Filename stem derived from the document identity ONLY — the same on every discovery."""
    return slug(adapted.document_identity)


def artifact_glob(adapted: AdaptedSnapshot, ext: str = "json") -> str:
    """Lookup pattern for prior artifacts of this identity. `.` never occurs inside a slug, so
    `netclaw-cml-lab.*.json` cannot match a sibling identity such as `netclaw-cml-lab-pod-1`."""
    return f"{identity_stem(adapted)}.*.{ext}"


def artifact_filename(adapted: AdaptedSnapshot, ext: str = "json", *, page: Optional[str] = None,
                      timestamp: Optional[str] = None) -> str:
    """`<identity_stem>.<snapshot slug>.<UTC timestamp>[.<page>].<ext>` — provenance in the name,
    identity in the stem. Never overwritten: every sync gets a new timestamp."""
    ts = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap = slug(adapted.provenance.get("snapshot_id") or "snapshot")
    suffix = f".{slug(page)}" if page else ""
    return f"{identity_stem(adapted)}.{snap}.{ts}{suffix}.{ext}"


def artifact_timestamp(path: Path, stem: str) -> str:
    """The UTC timestamp segment of `<stem>.<snapshot>.<timestamp>[.<page>].<ext>` ("" if the
    name does not follow the convention). Ordering by the whole name would sort by the snapshot
    slug first, which is exactly the snapshot-id coupling the naming scheme exists to avoid."""
    parts = path.name[len(stem) + 1:].split(".")
    return parts[1] if len(parts) >= 3 else ""


def find_latest_artifact(output_dir: Path, stem: str, ext: str = "json") -> Optional[Path]:
    """Newest prior artifact for `stem`: by timestamp segment (sorts lexically), then mtime."""
    candidates = [p for p in Path(output_dir).glob(f"{stem}.*.{ext}") if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: (artifact_timestamp(p, stem), p.stat().st_mtime, p.name))


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
    """Page scope: `None` = the whole snapshot (single page), `UNASSIGNED` = devices without a
    site, otherwise the devices of that site."""
    if site is None:
        return list(adapted.devices)
    if site == UNASSIGNED:
        return [d for d in adapted.devices if not d.site]
    return [d for d in adapted.devices if d.site == site]


def _links_for(adapted: AdaptedSnapshot, devices: list[AdaptedDevice]) -> list[AdaptedLink]:
    hosts = {d.hostname for d in devices}
    return [lnk for lnk in adapted.links if lnk.a in hosts and lnk.b in hosts]


def cross_site_links(adapted: AdaptedSnapshot) -> list[AdaptedLink]:
    """Links whose endpoints sit on different pages when the document is split by site. A
    Topology Dojo link cannot span pages, so these are drawn on no page and must be reported."""
    site_of = {d.hostname: (d.site or UNASSIGNED) for d in adapted.devices}
    return [lnk for lnk in adapted.links if site_of.get(lnk.a) != site_of.get(lnk.b)]


def page_plan(adapted: AdaptedSnapshot, *, split_by_site: bool) -> list[dict]:
    """The pages a document has, with the scope each one carries — the loop every page-scoped
    workflow step iterates (listing → diff → batches, one page at a time)."""
    if not (split_by_site and adapted.sites):
        return [{"index": 0, "id": "p-0", "name": "Topology", "site": None}]
    plan = [{"index": i, "id": f"p-{i}", "name": site, "site": site} for i, site in enumerate(adapted.sites)]
    if any(not d.site for d in adapted.devices):
        plan.append({"index": len(plan), "id": f"p-{len(plan)}", "name": "Unassigned", "site": UNASSIGNED})
    return plan


def _page(adapted: AdaptedSnapshot, page_id: str, name: str, site: Optional[str]) -> dict:
    fetched = adapted.provenance.get("created_at")
    devices = _devices_for(adapted, site)
    links = _links_for(adapted, devices)
    positions, view_box = place(devices)
    # Source ids are the EXACT canonical identifiers: `R1` and `r1` are different devices to
    # every source NetClaw reads, so they must stay different sources in Topology Dojo too.
    nodes = [
        {"id": node_id(d.hostname), **node_fields(d, positions[d.hostname]),
         "source": _source(adapted.system, "device", d.hostname, fetched)}
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
    _assert_unique_ids([n["id"] for n in nodes], "node")
    _assert_unique_ids([l["id"] for l in link_elems], "link")
    _assert_unique_ids([z["id"] for z in zones], "zone")
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
    pages = [_page(adapted, p["id"], p["name"], p["site"]) for p in page_plan(adapted, split_by_site=split_by_site)]
    if split_by_site and adapted.sites:
        for l in cross_site_links(adapted):
            log.warning("split-by-site: inter-site link %s (%s — %s) is on no page", l.identity, l.a, l.b)
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
        make("node", _source(adapted.system, "device", d.hostname, fetched),
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
    _assert_unique_ids([f'{o["source"]["kind"]}:{o["source"]["id"]}' for o in ops], "operation source")
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


def _intended(adapted: AdaptedSnapshot, site: Optional[str] = None) -> dict[tuple[str, str], dict]:
    """What this page should contain, keyed by (source kind, EXACT source id)."""
    devices = _devices_for(adapted, site)
    links = _links_for(adapted, devices)
    out: dict[tuple[str, str], dict] = {}
    for d in devices:
        out[("device", d.hostname)] = {"kind": "nodes", "label": d.hostname}
    for lnk in links:
        out[("link", lnk.identity)] = {"kind": "links", "label": link_fields(lnk).get("label")}
    if site is None:
        for s in adapted.sites:
            out[("site", s)] = {"kind": "zones", "label": s}
    return out


def diff_sourced(listing: list[dict], adapted: AdaptedSnapshot, *, site: Optional[str] = None) -> SyncDiff:
    """
    Compare a sourced-element listing (`{id, kind, source, label?}` rows from `get_topology
    sources:true` or `get_workspace_elements sourcedOnly:true`; rows may also be `{kind, element}`
    as get_workspace_elements returns) against the adapted snapshot. The listing carries no
    geometry, so a geometry-only change is `unchanged` (FR-008a).

    `site` is the page scope and must match the page the listing came from: `None` for a
    single-page document, a site name or `UNASSIGNED` for a page of a split-by-site document.
    Diffing one page's listing against the whole snapshot would report every other page's
    elements as `to_create`.
    """
    diff = SyncDiff()
    intended = _intended(adapted, site)
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
    scoped_links = _links_for(adapted, _devices_for(adapted, site))
    diff.ambiguous_links = [
        {"identity": lnk.identity, "a": lnk.a, "b": lnk.b, "label": lnk.label} for lnk in scoped_links if lnk.ambiguous
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

    def scope_args(sp: argparse.ArgumentParser) -> None:
        g = sp.add_mutually_exclusive_group()
        g.add_argument("--site", help="page scope of a split-by-site document")
        g.add_argument("--unassigned", action="store_true", help="the 'Unassigned' page of a split-by-site document")

    p = sub.add_parser("pages", help="page plan: index, id, name and scope of every page")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--overlay")
    p.add_argument("--split-by-site", action="store_true")

    p = sub.add_parser("upsert-batches", help="edit_topology batches of upsert_by_source ops for ONE page")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--overlay")
    p.add_argument("--page-index", type=int, required=True)
    scope_args(p)
    p.add_argument("--max-ops", type=int, default=DRAFT_MAX_OPS)

    p = sub.add_parser("workspace-batches", help="propose_workspace_changes batches of element.upsert ops for ONE page")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--overlay")
    p.add_argument("--page-id", required=True)
    scope_args(p)

    p = sub.add_parser("diff", help="Sync Diff of ONE page's sourced-element listing")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--overlay")
    p.add_argument("--listing", required=True, help="JSON: get_topology sources:true result, or a list of rows")
    p.add_argument("--page-index", type=int, help="which page of a multi-page get_topology result to diff")
    scope_args(p)

    p = sub.add_parser("identity", help="stable document identity, identity stem, artifact names")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--output-dir", default="workspace/output/topology-dojo")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    try:
        adapted = _adapted_from_args(args)
        site = UNASSIGNED if getattr(args, "unassigned", False) else getattr(args, "site", None)
        if args.command == "document":
            out: Any = build_document(adapted, split_by_site=args.split_by_site)
        elif args.command == "pages":
            out = {"pages": page_plan(adapted, split_by_site=args.split_by_site),
                   "cross_site_links": [{"identity": lnk.identity, "a": lnk.a, "b": lnk.b}
                                        for lnk in (cross_site_links(adapted) if args.split_by_site else [])]}
        elif args.command == "upsert-batches":
            out = build_upsert_batches(adapted, page_index=args.page_index, site=site, max_ops=args.max_ops)
        elif args.command == "workspace-batches":
            out = build_workspace_batches(adapted, page_id=args.page_id, site=site)
        elif args.command == "diff":
            listing = _load_json(args.listing)
            rows: list[dict] = []
            if isinstance(listing, dict) and "pages" in listing:
                pages = list(listing["pages"])
                if args.page_index is not None:
                    pages = [pg for pg in pages if pg.get("index") == args.page_index]
                    if not pages:
                        raise ValueError(f"listing has no page with index {args.page_index}")
                elif len(pages) > 1:
                    raise ValueError("listing has several pages; pass --page-index to diff one of them")
                for page in pages:
                    rows.extend(page.get("elements") or [])
            elif isinstance(listing, dict) and "elements" in listing:
                rows = list(listing["elements"])
            else:
                rows = list(listing)
            d = diff_sourced(rows, adapted, site=site)
            out = {"counts": d.counts(), **d.__dict__}
        else:
            latest = find_latest_artifact(Path(args.output_dir), identity_stem(adapted))
            out = {"document_identity": adapted.document_identity, "title": adapted.title, "system": adapted.system,
                   "provenance": adapted.provenance,
                   "identity_stem": identity_stem(adapted),
                   "artifact_glob": artifact_glob(adapted),
                   "artifact_json": artifact_filename(adapted, "json"),
                   "latest_artifact": str(latest) if latest else None}
    except Exception as exc:  # noqa: BLE001 — CLI boundary: report what failed and why
        log.error("%s: %s", type(exc).__name__, exc)
        return 2
    json.dump(out, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
