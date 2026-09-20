"""Spec 124 — share_guard.py: recursive address scan, confirmation gate, GAIT payload."""

import unittest

from share_guard import ShareNotConfirmed, assert_confirmed, gait_payload, scan_internal_addresses


class TestScan(unittest.TestCase):
    def test_link_subnet_alone_is_reported(self):
        doc = {"title": "t", "pages": [{"id": "p", "nodes": [{"id": "n", "label": "core1"}],
                                       "links": [{"id": "l", "from": "n", "to": "n", "subnet": "10.1.1.0/30"}]}]}
        hits = scan_internal_addresses(doc)
        self.assertEqual(len(hits), 1)
        self.assertIn("$.pages[0].links[0].subnet: 10.1.1.0 (10.0.0.0/8)", hits[0])

    def test_every_internal_family_and_no_documentation_ranges(self):
        doc = {"a": "mgmt 172.16.5.9", "b": {"c": ["169.254.1.1", "127.0.0.1"]}, "d": "fe80::1", "e": "fd00::1",
               "f": "192.168.0.10/24", "g": "100.64.1.1", "h": "::1",
               "public": "203.0.113.1 and 2001:db8::1 and 8.8.8.8", "text": "v1.2.3.4 is not an address"}
        hits = scan_internal_addresses(doc)
        found = {h.split(": ")[1].split(" ")[0] for h in hits}
        self.assertEqual(found, {"172.16.5.9", "169.254.1.1", "127.0.0.1", "fe80::1", "fd00::1", "192.168.0.10", "100.64.1.1", "::1"})
        self.assertNotIn("203.0.113.1", found)
        self.assertNotIn("2001:db8::1", found)
        self.assertNotIn("8.8.8.8", found)

    def test_paths_and_dedupe(self):
        doc = {"meta": {"mgmt": "10.0.0.1"}, "caption": "10.0.0.1 twice 10.0.0.1"}
        hits = scan_internal_addresses(doc)
        self.assertEqual(len(hits), 2)
        self.assertTrue(hits[0].startswith("$.meta.mgmt: "))


class TestGate(unittest.TestCase):
    def test_assert_confirmed(self):
        for bad in (False, None, "yes", 1):
            with self.assertRaises(ShareNotConfirmed):
                assert_confirmed(bad)
        assert_confirmed(True)

    def test_gait_payload_has_identifiers_only(self):
        payload = gait_payload("share", "netclaw:cml:lab", "t123", {"id": "abcdefghijkl", "url": "https://x/v/abcdefghijkl", "expiresAt": 1}, "snap-1", "ok", "cml")
        self.assertEqual(payload["share_id"], "abcdefghijkl")
        self.assertNotIn("url", payload)
        self.assertNotIn("tdk_", str(payload))
        self.assertEqual(payload["feature"], "topology-dojo")
        with self.assertRaises(ValueError):
            gait_payload("publish", "x", "t", None, "s", "ok")


if __name__ == "__main__":
    unittest.main()
