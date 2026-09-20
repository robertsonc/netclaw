#!/usr/bin/env python3
"""
Regenerate the spec 124 contract fixtures from the REAL canonical source adapters
(`workspace/skills/comfyui-topology-viz/sources.py::_build_snapshot`), so the field names the
Topology Dojo adapter consumes can never drift from what discovery actually produces (review
round 1, finding "this is not the existing canonical snapshot shape").

Run from the repo root:  python3 tests/topology-dojo/fixtures/generate_fixtures.py
Provenance (snapshot_id, created_at) is pinned after building so the files are deterministic.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SKILL = REPO / "workspace" / "skills" / "comfyui-topology-viz"
sys.path.insert(0, str(SKILL))
import sources  # noqa: E402  (the real adapters)

PINNED_AT = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
OUT = Path(__file__).resolve().parent


def _plain(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def dump(name: str, snapshot, pinned_id: str) -> None:
    snapshot.snapshot_id = pinned_id
    snapshot.created_at = PINNED_AT
    data = _plain(dataclasses.asdict(snapshot))
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"{name}.json: {len(data['devices'])} devices, {len(data['links'])} links")


def dev(hostname, role, model="", status="healthy", ifaces=(), **meta):
    d = {"hostname": hostname, "role": role, "model": model, "status": status,
         "interfaces": [{"name": n, "ip_address": ip} for n, ip in ifaces]}
    d.update(meta)
    return d


def link(a, ia, b, ib, id=None, status=None):
    l = {"source_device": a, "target_device": b}
    if ia:
        l["source_interface"] = ia
    if ib:
        l["target_interface"] = ib
    if id:
        l["id"] = id
    if status:
        l["status"] = status
    return l


def small():
    raw = {
        "source": "lab-pod-1",
        "devices": [
            dev("r1", "router", "C8000V", ifaces=[("Gi1", "10.1.1.1/30"), ("Gi2", "10.1.2.1/24")], platform="IOS-XE", serial="ABC123", password="never"),
            dev("r2", "router", "ISR4431", ifaces=[("Gi1", "10.1.1.2/30"), ("Gi2", "10.2.1.1/24")], platform="IOS-XE"),
            dev("sw1", "switch", "C9300", "degraded", ifaces=[("Gi0/1", None), ("Gi0/2", None)], platform="IOS-XE"),
            dev("fw1", "firewall", "FTD", ifaces=[("eth0", "10.1.2.254/24")], snmp={"community": "public", "version": "2c"}),
            dev("host1", "client", "", "unknown", ifaces=[("eth0", "10.2.1.10/24")]),
        ],
        "links": [
            link("r1", "Gi1", "r2", "Gi1", id="cml-link-1"),
            link("r1", "Gi2", "sw1", "Gi0/1"),
            link("sw1", "Gi0/2", "fw1", "eth0", status="down"),
            link("r2", "Gi2", "host1", "eth0"),
        ],
    }
    dump("small", sources.from_cml(raw), "cml-20260920T120000000000")


def reconciled():
    raw = {
        "source": "dc1-fabric",
        "devices": [
            dev("core1", "router", "MX204", ifaces=[("et-0/0/0", "10.10.0.1/31"), ("et-0/0/1", None)], site="dc1"),
            dev("leaf1", "switch", "QFX5120", ifaces=[("xe-0/0/0", "10.10.0.0/31"), ("xe-0/0/1", None)], site="dc1"),
            dev("leaf2", "switch", "QFX5120", ifaces=[("xe-0/0/0", None)], site="dc1"),
            dev("edge-fw", "firewall", "SRX4600", ifaces=[("ge-0/0/0", None)], site="dc1"),
        ],
        "links": [
            link("core1", "et-0/0/0", "leaf1", "xe-0/0/0", id="cable-101"),
            link("core1", "et-0/0/1", "leaf2", "xe-0/0/0", id="cable-102"),
            link("leaf1", "xe-0/0/1", "edge-fw", "ge-0/0/0", id="cable-103"),
            link("leaf2", None, "edge-fw", None, id="cable-104"),
        ],
    }
    dump("reconciled", sources.from_netbox_infrahub(raw), "netbox_infrahub-20260920T120000000000")
    overlay = {
        "cable-101": {"reconciliation": "DOCUMENTED", "vlan": "10", "bandwidth": "100G"},
        "cable-102": {"reconciliation": "UNDOCUMENTED", "bandwidth": "100G"},
        "cable-103": {"reconciliation": "MISSING", "transport": "fiber"},
        "cable-104": {"reconciliation": "MISMATCH"},
    }
    (OUT / "reconciled.overlay.json").write_text(json.dumps(overlay, indent=2) + "\n", encoding="utf-8")


def large():
    devices, links = [], []
    fws = [f"fw{i}" for i in range(1, 3)]
    routers = [f"r{i}" for i in range(1, 5)]
    switches = [f"sw{i:02d}" for i in range(1, 15)]
    hosts = [f"host{i:02d}" for i in range(1, 41)]
    for h in fws:
        devices.append(dev(h, "firewall", "FTD", ifaces=[("eth0", None), ("eth1", None)]))
    for h in routers:
        devices.append(dev(h, "router", "C8000V", ifaces=[(f"Gi{i}", None) for i in range(1, 20)]))
    for h in switches:
        devices.append(dev(h, "switch", "C9300", ifaces=[(f"Gi0/{i}", None) for i in range(1, 8)]))
    for h in hosts:
        devices.append(dev(h, "client", "", ifaces=[("eth0", None)]))
    # 40 host→switch + 28 switch→router (two uplinks each) + 8 router→fw + 6 router↔router
    # + 8 extra fw/router cross-links = 90.
    for i, h in enumerate(hosts):
        links.append(link(h, "eth0", switches[i % 14], f"Gi0/{(i // 14) + 1}"))
    for i, s in enumerate(switches):
        links.append(link(s, "Gi0/6", routers[i % 4], f"Gi{i + 1}"))
        links.append(link(s, "Gi0/7", routers[(i + 1) % 4], f"Gi{i + 1}"))
    for r in routers:
        for f in fws:
            links.append(link(r, "Gi15", f, "eth0"))
    pairs = [("r1", "r2"), ("r2", "r3"), ("r3", "r4"), ("r4", "r1"), ("r1", "r3"), ("r2", "r4")]
    for a, b in pairs:
        links.append(link(a, "Gi16", b, "Gi17"))
    extras = [("fw1", "eth1", "fw2", "eth1"), ("r1", "Gi18", "fw1", "eth1"), ("r2", "Gi18", "fw2", "eth1"),
              ("r3", "Gi18", "fw1", "eth1"), ("r4", "Gi18", "fw2", "eth1"), ("r1", "Gi19", "fw2", "eth1"),
              ("r2", "Gi19", "fw1", "eth1"), ("r3", "Gi19", "fw2", "eth1")]
    for a, ia, b, ib in extras:
        links.append(link(a, ia, b, ib))
    assert len(devices) == 60 and len(links) == 90, (len(devices), len(links))
    dump("large", sources.from_ip_fabric({"source": "enterprise", "devices": devices, "links": links}), "ip_fabric-20260920T120000000000")


def sites():
    raw = {
        "source": "campus",
        "devices": [
            dev("bos-rtr1", "router", "MX204", ifaces=[("ge-0/0/0", None), ("ge-0/0/1", None)], site="Boston"),
            dev("bos-sw1", "switch", "EX4400", ifaces=[("ge-0/0/0", None), ("ge-0/0/1", None)], site="Boston"),
            dev("bos-ap1", "unclassified", "AP45", ifaces=[("eth0", None)], site="Boston"),
            dev("pdx-rtr1", "router", "MX204", ifaces=[("ge-0/0/0", None), ("ge-0/0/1", None)], site="Portland"),
            dev("pdx-sw1", "switch", "EX4400", ifaces=[("ge-0/0/0", None)], site="Portland"),
            dev("pdx-host1", "client", "", ifaces=[("eth0", None)], site="Portland"),
            dev("cloud-gw", "router", "vMX", ifaces=[("ge-0/0/0", None)]),
        ],
        "links": [
            link("bos-rtr1", "ge-0/0/0", "bos-sw1", "ge-0/0/0"),
            link("bos-sw1", "ge-0/0/1", "bos-ap1", "eth0"),
            link("pdx-rtr1", "ge-0/0/0", "pdx-sw1", "ge-0/0/0"),
            link("pdx-sw1", None, "pdx-host1", "eth0"),
            link("bos-rtr1", "ge-0/0/1", "pdx-rtr1", "ge-0/0/1"),
            link("pdx-rtr1", None, "cloud-gw", "ge-0/0/0"),
        ],
    }
    dump("sites", sources.from_nautobot(raw), "nautobot-20260920T120000000000")


def parallel():
    raw = {
        "source": "parallel-links",
        "devices": [
            dev("a", "switch", "X", ifaces=[("e1", None), ("e2", None)]),
            dev("b", "switch", "X", ifaces=[("e1", None), ("e2", None)]),
        ],
        "links": [
            link("a", "e1", "b", "e1"),                       # rule 2: interface pair
            link("a", None, "b", None, id="gns3-link-7"),     # rule 1: real id, no interfaces
            link("a", None, "b", None),                       # rule 3 (positional link-2) — ambiguous with the next
            link("b", None, "a", None),                       # rule 3 (positional link-3), reversed endpoints
        ],
    }
    dump("parallel", sources.from_gns3(raw), "gns3-20260920T120000000000")


if __name__ == "__main__":
    small(); reconciled(); large(); sites(); parallel()
