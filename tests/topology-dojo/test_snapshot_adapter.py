"""Spec 124 — snapshot_adapter.py against fixtures serialized from the REAL source adapters."""

import json
import unittest
from pathlib import Path

from snapshot_adapter import (
    FORBIDDEN_KEYS,
    SnapshotAdapterError,
    adapt,
    document_identity,
    load_overlay,
    sanitize_recursive,
    slug,
)

FIX = Path(__file__).resolve().parent / "fixtures"


def fixture(name):
    return json.loads((FIX / f"{name}.json").read_text())


class TestRealModelShape(unittest.TestCase):
    def test_fixtures_carry_only_canonical_field_names(self):
        snap = fixture("small")
        self.assertEqual(set(snap), {"snapshot_id", "source_kind", "source_label", "created_at", "devices", "links"})
        self.assertEqual(set(snap["links"][0]), {"link_id", "endpoint_a", "endpoint_b", "state", "label"})
        self.assertEqual(set(snap["links"][0]["endpoint_a"]), {"hostname", "interface_name"})
        self.assertEqual(set(snap["devices"][0]), {"hostname", "role", "state", "interfaces", "metadata"})
        invented = {"fetched_at", "a", "b", "a_interface", "b_interface", "src", "dst"}
        for link in snap["links"]:
            self.assertFalse(invented & set(link), link)
        for device in snap["devices"]:
            self.assertFalse(invented & set(device), device["hostname"])

    def test_adapts_every_fixture(self):
        for name in ("small", "reconciled", "large", "sites", "parallel"):
            adapted = adapt(fixture(name))
            self.assertEqual(len(adapted.devices), len(fixture(name)["devices"]), name)
            self.assertEqual(len(adapted.links), len(fixture(name)["links"]), name)

    def test_accepts_dataclass_like_objects_with_enums(self):
        from dataclasses import dataclass, field
        from enum import Enum

        class Role(str, Enum):
            ROUTER = "router"

        @dataclass
        class Endpoint:
            hostname: str
            interface_name: str = None

        @dataclass
        class Link:
            link_id: str
            endpoint_a: Endpoint
            endpoint_b: Endpoint
            state: str = None
            label: str = ""

        @dataclass
        class Device:
            hostname: str
            role: Role = Role.ROUTER
            state: str = None
            interfaces: list = field(default_factory=list)
            metadata: dict = field(default_factory=dict)

        @dataclass
        class Snap:
            snapshot_id: str
            source_kind: Role  # any Enum-like works
            source_label: str
            created_at: object
            devices: list
            links: list

        from datetime import datetime, timezone
        snap = Snap("x", Role.ROUTER, "lab", datetime(2026, 1, 1, tzinfo=timezone.utc),
                    [Device("a"), Device("b")], [Link("l1", Endpoint("a"), Endpoint("b"))])
        adapted = adapt(snap)
        self.assertEqual(adapted.system, "router")
        self.assertEqual(adapted.provenance["created_at"], "2026-01-01T00:00:00+00:00")


class TestIdentity(unittest.TestCase):
    def test_document_identity_is_stable_and_never_uses_snapshot_id(self):
        a = adapt(fixture("small"))
        again = fixture("small"); again["snapshot_id"] = "cml-99991231T235959999999"; again["created_at"] = "2027-01-01T00:00:00+00:00"
        b = adapt(again)
        self.assertEqual(a.document_identity, b.document_identity)
        self.assertEqual(a.document_identity, "netclaw:cml:lab-pod-1")
        self.assertEqual(a.title, "NetClaw — cml — lab-pod-1")
        self.assertNotIn("20260920", a.document_identity)
        self.assertEqual(document_identity("netbox_infrahub", "DC1 Fabric"), "netclaw:netbox-infrahub:dc1-fabric")
        self.assertEqual(slug("Gi0/1 ↔ Gi0/2"), "gi0-1-gi0-2")

    def test_link_identity_precedence(self):
        adapted = adapt(fixture("parallel"))
        by_id = {l.link_id: l for l in adapted.links}
        # rule 2: both interface names known → sorted endpoint:interface pair
        self.assertEqual(by_id["link-0"].identity, "a:e1|b:e1")
        self.assertFalse(by_id["link-0"].ambiguous)
        # rule 1: a real source-supplied id wins even without interfaces
        self.assertEqual(by_id["gns3-link-7"].identity, "gns3-link-7")
        self.assertFalse(by_id["gns3-link-7"].ambiguous)
        # rule 3: positional link-<n> ids are treated as absent; two such links share a pair → ambiguous
        r3 = sorted(l.identity for l in adapted.links if l.ambiguous)
        self.assertEqual(r3, ["a|b#0", "a|b#1"])
        # the reversed-endpoint link got the same pair key (sorted hostnames)
        self.assertTrue(all(i.startswith("a|b#") for i in r3))

    def test_single_interface_less_link_is_not_ambiguous(self):
        adapted = adapt(fixture("sites"))
        l = next(l for l in adapted.links if l.a == "pdx-sw1" and l.b == "pdx-host1")
        self.assertEqual(l.identity, "pdx-host1|pdx-sw1#0")
        self.assertFalse(l.ambiguous)

    def test_endpoint_swap_does_not_change_identity(self):
        snap = fixture("small")
        swapped = json.loads(json.dumps(snap))
        for l in swapped["links"]:
            l["endpoint_a"], l["endpoint_b"] = l["endpoint_b"], l["endpoint_a"]
        a = sorted(l.identity for l in adapt(snap).links)
        b = sorted(l.identity for l in adapt(swapped).links)
        self.assertEqual(a, b)


class TestDerivedFields(unittest.TestCase):
    def test_subnet_only_when_both_interfaces_carry_agreeing_prefixes(self):
        adapted = adapt(fixture("small"))
        by_id = {l.link_id: l for l in adapted.links}
        self.assertEqual(by_id["cml-link-1"].subnet, "10.1.1.0/30")
        sw = next(l for l in adapted.links if "sw1" in (l.a, l.b) and "r1" in (l.a, l.b))
        self.assertIsNone(sw.subnet)  # sw1's interface has no address

    def test_overlay_lands_by_link_id_and_missing_overlay_is_fine(self):
        overlay = load_overlay(json.loads((FIX / "reconciled.overlay.json").read_text()))
        adapted = adapt(fixture("reconciled"), overlay)
        by_id = {l.link_id: l for l in adapted.links}
        self.assertEqual(by_id["cable-101"].reconciliation, "DOCUMENTED")
        self.assertEqual(by_id["cable-101"].vlan, "10")
        self.assertEqual(by_id["cable-103"].transport, "fiber")
        self.assertEqual(by_id["cable-104"].reconciliation, "MISMATCH")
        self.assertIsNone(adapt(fixture("reconciled")).links[0].reconciliation)
        rows = load_overlay([{"link_id": "cable-101", "reconciliation": "missing"}])
        self.assertEqual(adapt(fixture("reconciled"), rows).links[0].reconciliation, "MISSING")

    def test_sites_and_platform(self):
        adapted = adapt(fixture("sites"))
        self.assertEqual(adapted.sites, ["Boston", "Portland"])
        self.assertIsNone(adapted.device("cloud-gw").site)
        self.assertEqual(adapted.device("bos-rtr1").platform, "MX204")

    def test_role_and_state_mapping_inputs(self):
        adapted = adapt(fixture("small"))
        self.assertEqual(adapted.device("sw1").state, "degraded")
        self.assertEqual(adapted.device("host1").state, "unknown")
        self.assertEqual(adapted.device("fw1").role, "firewall")


class TestSanitizer(unittest.TestCase):
    def test_union_denylist_recursive(self):
        self.assertTrue({"credential", "credentials", "running_config", "startup_config", "config",
                         "private_key", "passwd", "community", "password", "secret", "token", "api_key", "apikey"} <= FORBIDDEN_KEYS)
        cleaned = sanitize_recursive({"snmp": {"community": "public", "version": "2c"},
                                      "list": [{"Password": "x", "ok": 1}], "Running_Config": "..."})
        self.assertEqual(cleaned, {"snmp": {"version": "2c"}, "list": [{"ok": 1}]})

    def test_stringified_nested_secrets_are_removed(self):
        # The canonical shallow sanitizer turns nested dicts into `str(dict)` text; the adapter
        # must still strip the credential inside, keeping the harmless sibling keys.
        meta = {
            "serial": "ABC123",
            "snmp": "{'community': 'public', 'version': '2c'}",
            "auth": '{"password": "hunter2", "user": "admin"}',
            "note": "token=abcdef opaque text",
            "vendor": "cisco",
        }
        cleaned = sanitize_recursive(meta)
        self.assertEqual(cleaned["serial"], "ABC123")
        self.assertEqual(cleaned["snmp"], {"version": "2c"})
        self.assertEqual(cleaned["auth"], {"user": "admin"})
        self.assertNotIn("note", cleaned)
        self.assertEqual(cleaned["vendor"], "cisco")
        self.assertNotIn("public", json.dumps(cleaned))
        self.assertNotIn("hunter2", json.dumps(cleaned))

    def test_fixture_secrets_never_survive_adaptation(self):
        adapted = adapt(fixture("small"))
        dumped = json.dumps([d.meta for d in adapted.devices])
        self.assertNotIn("password", dumped.lower())
        self.assertNotIn("community", dumped.lower())
        self.assertNotIn("public", dumped)
        self.assertIn("serial", dumped)


class TestValidation(unittest.TestCase):
    def test_rejects_empty_duplicate_and_dangling(self):
        with self.assertRaises(SnapshotAdapterError):
            adapt({"source_kind": "cml", "source_label": "x", "devices": [], "links": []})
        snap = fixture("small"); snap["devices"].append(dict(snap["devices"][0]))
        with self.assertRaises(SnapshotAdapterError):
            adapt(snap)
        snap = fixture("small"); snap["links"][0]["endpoint_a"]["hostname"] = "ghost"
        with self.assertRaises(SnapshotAdapterError):
            adapt(snap)


if __name__ == "__main__":
    unittest.main()
