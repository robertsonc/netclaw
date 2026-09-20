#!/usr/bin/env python3
"""
share_guard.py — spec 124 (FR-012). Guards `share_topology`, the one outward publication in the
Topology Dojo integration (Constitution Principle XIV):

  * scan_internal_addresses(document): recursive walk of the CURRENT server-side document (fetched
    with get_topology immediately before publishing) — every string at any depth, so first-class
    link fields such as `subnet`, `fromLabel`/`toLabel`, node `meta`, zone descriptions and page
    captions are all covered. Reports RFC 1918, CGNAT, loopback, link-local, unique-local and ::1.
    Documentation ranges (TEST-NET, 2001:db8::/32) are deliberately not reported.
  * assert_confirmed(confirmed): the code-level half of the two-layer gate (the conversational
    "yes" is the other half).
  * gait_payload(...): the Principle IV audit record — never the document, never a token.

Stdlib only. No network.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from typing import Any, Iterator, Optional

INTERNAL_NETWORKS = [
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "fe80::/10",
        "fc00::/7",
        "::1/128",
    )
]

_IPV4 = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?:/\d{1,2})?(?![\w.])")
_IPV6 = re.compile(r"(?<![\w:])((?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4})(?:/\d{1,3})?(?![\w:])")


class ShareNotConfirmed(PermissionError):
    """Raised when a publish is attempted without the explicit confirmation argument."""


def _strings(value: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            yield from _strings(v, f"{path}[{i}]")


def _is_internal(text: str) -> Optional[str]:
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return None
    for net in INTERNAL_NETWORKS:
        if addr.version == net.version and addr in net:
            return str(net)
    return None


def scan_internal_addresses(document: Any) -> list[str]:
    """Return `path: address (network)` strings for every internal address found, de-duplicated."""
    found: list[str] = []
    seen: set[tuple[str, str]] = set()
    for path, text in _strings(document):
        candidates = [m.group(1) for m in _IPV4.finditer(text)]
        candidates += [m.group(1) for m in _IPV6.finditer(text) if ":" in m.group(1)]
        for candidate in candidates:
            net = _is_internal(candidate)
            if net and (path, candidate) not in seen:
                seen.add((path, candidate))
                found.append(f"{path}: {candidate} ({net})")
    return found


def assert_confirmed(confirmed: bool) -> None:
    if confirmed is not True:
        raise ShareNotConfirmed(
            "share_topology publishes a public 30-day link; it needs an explicit confirmation "
            "(confirmed=True) given in this conversation after the internal-address scan was shown"
        )


def gait_payload(action: str, document_identity: str, topology_id: str, share: Optional[dict],
                 snapshot_id: str, outcome: str, source_kind: str = "") -> dict:
    """Audit record for `gait_record_turn`. Contains identifiers only."""
    if action not in ("share", "unpublish"):
        raise ValueError("action must be 'share' or 'unpublish'")
    payload = {
        "feature": "topology-dojo",
        "action": action,
        "document_identity": document_identity,
        "topology_id": topology_id,
        "source_kind": source_kind,
        "snapshot_id": snapshot_id,
        "outcome": outcome,
    }
    if share:
        payload["share_id"] = str(share.get("id") or "")
        expires = share.get("expiresAt") or share.get("expires_at")
        if expires is not None:
            payload["expires_at"] = expires
    return payload


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Share guard for the Topology Dojo integration (spec 124)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("scan", help="list internal addresses in a document JSON file")
    p.add_argument("--document", required=True)
    args = parser.parse_args(argv)
    with open(args.document, "r", encoding="utf-8") as fh:
        document = json.load(fh)
    hits = scan_internal_addresses(document)
    json.dump({"internal_addresses": hits, "count": len(hits)}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
