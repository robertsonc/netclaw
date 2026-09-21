"""Spec 124 — dojo_document.py: document, batches, diff, CLI. Offline, deterministic."""

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

from snapshot_adapter import adapt, load_overlay
from dojo_document import (
    summarize_results,
    DOCUMENT_KEYS,
    DRAFT_MAX_OPS,
    LINK_KEYS,
    NODE_KEYS,
    PAGE_KEYS,
    RECONCILIATION_COLOR,
    ROLE_TO_TYPE,
    STATE_TO_STATUS,
    WORKSPACE_MAX_BYTES,
    WORKSPACE_MAX_OPS,
    ZONE_KEYS,
    build_document,
    build_upsert_batches,
    build_workspace_batches,
    count_created,
    cross_site_links,
    diff_sourced,
    find_latest_artifact,
    artifact_filename,
    identity_stem,
    node_id,
    page_plan,
    UNASSIGNED,
)

FIX = Path(__file__).resolve().parent / "fixtures"
SKILL = Path(__file__).resolve().parents[2] / "workspace" / "skills" / "topology-dojo-diagram"


def fixture(name):
    return json.loads((FIX / f"{name}.json").read_text())


def adapted(name, overlay=None):
    return adapt(fixture(name), overlay)


class TestBuildDocument(unittest.TestCase):
    def test_counts_and_labels(self):
        for name in ("small", "reconciled", "large", "sites", "parallel"):
            snap = fixture(name)
            doc = build_document(adapted(name))
            page = doc["pages"][0]
            self.assertEqual(len(page["nodes"]), len(snap["devices"]), name)
            self.assertEqual(len(page["links"]), len(snap["links"]), name)
            self.assertEqual(sorted(n["label"] for n in page["nodes"]), sorted(d["hostname"] for d in snap["devices"]), name)
            self.assertEqual(len({n["id"] for n in page["nodes"]}), len(page["nodes"]), name)

    def test_role_state_interface_and_overlay_mapping(self):
        overlay = load_overlay(json.loads((FIX / "reconciled.overlay.json").read_text()))
        doc = build_document(adapted("reconciled", overlay))
        page = doc["pages"][0]
        by_label = {n["label"]: n for n in page["nodes"]}
        self.assertEqual(by_label["core1"]["type"], ROLE_TO_TYPE["router"])
        self.assertEqual(by_label["leaf1"]["type"], ROLE_TO_TYPE["switch"])
        self.assertEqual(by_label["edge-fw"]["type"], ROLE_TO_TYPE["firewall"])
        self.assertEqual(by_label["core1"]["status"], STATE_TO_STATUS["healthy"])
        self.assertEqual(by_label["core1"]["sublabel"], "MX204")
        self.assertEqual(by_label["core1"]["source"], {"system": "netbox_infrahub", "kind": "device", "id": "core1", "fetchedAt": "2026-09-20T12:00:00+00:00"})
        links = {l["source"]["id"]: l for l in page["links"]}
        l101 = links["cable-101"]
        self.assertEqual((l101["fromLabel"], l101["toLabel"]), ("et-0/0/0", "xe-0/0/0"))
        self.assertEqual(l101["subnet"], "10.10.0.0/31")
        self.assertEqual(l101["vlan"], "10")
        self.assertEqual(l101["bandwidth"], "100G")
        self.assertTrue(l101["showMeta"])
        self.assertEqual(l101["color"], RECONCILIATION_COLOR["DOCUMENTED"])
        self.assertEqual(links["cable-104"]["color"], RECONCILIATION_COLOR["MISMATCH"])
        self.assertEqual(doc["legend"], {"show": True, "position": "br"})
        self.assertNotIn("legend", build_document(adapted("small")))

    def test_emits_only_known_document_fields(self):
        overlay = load_overlay(json.loads((FIX / "reconciled.overlay.json").read_text()))
        for name, ov in (("sites", None), ("reconciled", overlay), ("large", None)):
            doc = build_document(adapted(name, ov))
            self.assertTrue(set(doc) <= DOCUMENT_KEYS, set(doc))
            for page in doc["pages"]:
                self.assertEqual(set(page), PAGE_KEYS)
                for n in page["nodes"]:
                    self.assertTrue(set(n) <= NODE_KEYS, set(n) - NODE_KEYS)
                for l in page["links"]:
                    self.assertTrue(set(l) <= LINK_KEYS, set(l) - LINK_KEYS)
                for z in page["zones"]:
                    self.assertTrue(set(z) <= ZONE_KEYS, set(z) - ZONE_KEYS)

    def test_zones_split_by_site_and_viewbox_growth(self):
        doc = build_document(adapted("sites"))
        page = doc["pages"][0]
        self.assertEqual([z["label"] for z in page["zones"]], ["Boston", "Portland"])
        self.assertEqual(sorted(page["zones"][0]["nodes"]), sorted(node_id(h) for h in ("bos-ap1", "bos-rtr1", "bos-sw1")))
        split = build_document(adapted("sites"), split_by_site=True)
        self.assertEqual([p["name"] for p in split["pages"]], ["Boston", "Portland", "Unassigned"])
        self.assertEqual([n["label"] for n in split["pages"][2]["nodes"]], ["cloud-gw"])
        self.assertEqual(split["pages"][0]["zones"], [])
        big = build_document(adapted("large"))["pages"][0]
        w, h = (int(v) for v in big["viewBox"].split()[2:])
        self.assertGreater(w, 1050)
        self.assertGreaterEqual(h, 700)
        xs = [n["x"] for n in big["nodes"]]
        self.assertTrue(all(0 < x < w for x in xs))
        self.assertTrue(all(n["x"] % 40 == 0 and n["y"] % 40 == 0 for n in big["nodes"]))

    def test_secrets_absent_from_document(self):
        dumped = json.dumps(build_document(adapted("small")))
        self.assertNotIn("password", dumped.lower())
        self.assertNotIn("community", dumped.lower())


class TestBatches(unittest.TestCase):
    def test_deterministic_and_swap_stable(self):
        a = build_upsert_batches(adapted("small"))
        b = build_upsert_batches(adapted("small"))
        self.assertEqual(a, b)
        swapped = fixture("small")
        for l in swapped["links"]:
            l["endpoint_a"], l["endpoint_b"] = l["endpoint_b"], l["endpoint_a"]
        ids = lambda batches: sorted(op["source"]["id"] for batch in batches for op in batch)
        self.assertEqual(ids(a), ids(build_upsert_batches(adapt(swapped))))

    def test_ordering_and_chunking(self):
        batches = build_upsert_batches(adapted("large"), max_ops=DRAFT_MAX_OPS)
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 150)  # 60 nodes + 90 links, no sites
        kinds = [op["kind"] for op in batches[0]]
        self.assertEqual(kinds, ["node"] * 60 + ["link"] * 90)
        small = build_upsert_batches(adapted("large"), max_ops=40)
        self.assertEqual([len(b) for b in small], [40, 40, 40, 30])
        self.assertTrue(all(op["op"] == "upsert_by_source" and op["pageIndex"] == 0 for b in small for op in b))
        node_ops = [op for op in batches[0] if op["kind"] == "node"]
        self.assertTrue(all({"type", "x", "y"} <= set(op["set"]) for op in node_ops))
        self.assertTrue(all("id" not in op["set"] for op in batches[0]))
        link_ops = [op for op in batches[0] if op["kind"] == "link"]
        self.assertTrue(all({"type", "from", "to"} <= set(op["set"]) for op in link_ops))
        self.assertTrue(all(op["source"]["fetchedAt"] for op in batches[0]))

    def test_zone_ops_and_site_filter(self):
        ops = build_upsert_batches(adapted("sites"))[0]
        self.assertEqual([op["kind"] for op in ops][-2:], ["zone", "zone"])
        self.assertEqual(ops[-2]["source"], {"system": "nautobot", "kind": "site", "id": "Boston", "fetchedAt": "2026-09-20T12:00:00+00:00"})
        boston = build_upsert_batches(adapted("sites"), site="Boston", page_index=0)[0]
        self.assertEqual(sorted(op["set"]["label"] for op in boston if op["kind"] == "node"), ["bos-ap1", "bos-rtr1", "bos-sw1"])
        self.assertEqual(len([op for op in boston if op["kind"] == "link"]), 2)

    def test_workspace_batches_are_element_upserts(self):
        batches = build_workspace_batches(adapted("sites"), page_id="p-1")
        self.assertEqual(len(batches), 1)
        ops = batches[0]
        self.assertTrue(all(op["type"] == "element.upsert" and op["pageId"] == "p-1" for op in ops))
        self.assertEqual([op["kind"] for op in ops], ["nodes"] * 7 + ["links"] * 6 + ["zones"] * 2)
        node = ops[0]
        self.assertEqual(set(node), {"type", "pageId", "kind", "source", "element"})
        self.assertTrue({"id", "type", "x", "y", "label"} <= set(node["element"]))
        draft_ids = sorted(op["source"]["id"] for op in build_upsert_batches(adapted("sites"))[0])
        self.assertEqual(sorted(op["source"]["id"] for op in ops), draft_ids)
        big = build_workspace_batches(adapted("large"), page_id="p", max_ops=WORKSPACE_MAX_OPS, max_bytes=WORKSPACE_MAX_BYTES)
        self.assertEqual(len(big), 1)
        self.assertLessEqual(len(json.dumps(big[0]).encode()), WORKSPACE_MAX_BYTES)
        tiny = build_workspace_batches(adapted("large"), page_id="p", max_bytes=8000)
        self.assertGreater(len(tiny), 1)
        self.assertTrue(all(len(json.dumps(b).encode()) <= 8000 for b in tiny))

    def test_performance_60_90(self):
        start = time.perf_counter()
        a = adapted("large")
        build_document(a); build_upsert_batches(a); build_workspace_batches(a, page_id="p")
        self.assertLess(time.perf_counter() - start, 1.0)


def listing_from(document):
    """Emulate `get_topology sources:true` rows from a document (id, kind, source, label)."""
    rows = []
    for page in document["pages"]:
        for kind in ("nodes", "links", "zones"):
            for el in page[kind]:
                if el.get("source"):
                    rows.append({"id": el["id"], "kind": kind, "source": el["source"], **({"label": el["label"]} if "label" in el else {})})
    return rows


class TestDiffSourced(unittest.TestCase):
    def test_unchanged_added_removed_relabelled_geometry(self):
        base = adapted("small")
        listing = listing_from(build_document(base))
        d = diff_sourced(listing, base)
        self.assertEqual(d.counts(), {"to_create": 0, "to_update": 0, "unchanged": 9, "absent_at_source": 0, "ambiguous_links": 0})

        snap = fixture("small")
        snap["devices"].append({"hostname": "r3", "role": "router", "state": None, "interfaces": [], "metadata": {}})
        d = diff_sourced(listing, adapt(snap))
        self.assertEqual(d.counts()["to_create"], 1)
        self.assertEqual(d.to_create[0]["source"], {"system": "cml", "kind": "device", "id": "r3"})

        snap = fixture("small")
        removed = snap["devices"].pop()  # host1
        snap["links"] = [l for l in snap["links"] if removed["hostname"] not in (l["endpoint_a"]["hostname"], l["endpoint_b"]["hostname"])]
        d = diff_sourced(listing, adapt(snap))
        self.assertEqual(d.counts()["absent_at_source"], 2)  # the node and its link
        self.assertIn(node_id("host1"), [e["id"] for e in d.absent_at_source])

        relabelled = json.loads(json.dumps(listing))
        for row in relabelled:
            if row["id"] == node_id("r1"):
                row["label"] = "R1-old"
        d = diff_sourced(relabelled, base)
        self.assertEqual(d.counts()["to_update"], 1)
        self.assertEqual(d.to_update[0]["intended_label"], "r1")

        # geometry-only change: the listing carries no geometry, so nothing to update
        d = diff_sourced(listing, base)
        self.assertEqual(d.counts()["to_update"], 0)

    def test_ignores_foreign_systems_and_accepts_workspace_row_shape(self):
        base = adapted("small")
        listing = listing_from(build_document(base))
        listing.append({"id": "n-x", "kind": "nodes", "source": {"system": "edgeconnect", "kind": "appliance", "id": "x"}})
        d = diff_sourced(listing, base)
        self.assertEqual(d.counts()["absent_at_source"], 0)
        ws_rows = [{"kind": r["kind"], "element": {k: v for k, v in r.items() if k != "kind"}} for r in listing]
        self.assertEqual(diff_sourced(ws_rows, base).counts()["unchanged"], 9)

    def test_ambiguous_links_and_created_count(self):
        d = diff_sourced([], adapted("parallel"))
        self.assertEqual(len(d.ambiguous_links), 2)
        self.assertEqual(d.counts()["to_create"], 6)
        results = [{"op": "upsert_by_source", "id": "a", "created": True}, {"op": "upsert_by_source", "id": "b", "created": False}, {"op": "add_node", "id": "c"}]
        self.assertEqual(count_created(results), 1)


class TestCli(unittest.TestCase):
    def run_cli(self, *args):
        proc = subprocess.run([sys.executable, str(SKILL / "dojo_document.py"), *args], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_subcommands(self):
        snap = str(FIX / "small.json")
        ident = self.run_cli("identity", "--snapshot", snap)
        self.assertEqual(ident["document_identity"], "netclaw:cml:lab-pod-1")
        self.assertEqual(ident["identity_stem"], "netclaw-cml-lab-pod-1")
        self.assertEqual(ident["artifact_glob"], "netclaw-cml-lab-pod-1.*.json")
        self.assertTrue(ident["artifact_json"].startswith("netclaw-cml-lab-pod-1.cml-20260920t120000000000."))
        self.assertIsNone(ident["latest_artifact"])
        plan = self.run_cli("pages", "--snapshot", str(FIX / "sites.json"), "--split-by-site")
        self.assertEqual([p["name"] for p in plan["pages"]], ["Boston", "Portland", "Unassigned"])
        self.assertEqual({(l["a"], l["b"]) for l in plan["cross_site_links"]}, {("bos-rtr1", "pdx-rtr1"), ("pdx-rtr1", "cloud-gw")})
        doc = self.run_cli("document", "--snapshot", snap)
        self.assertEqual(len(doc["pages"][0]["nodes"]), 5)
        batches = self.run_cli("upsert-batches", "--snapshot", snap, "--page-index", "0")
        self.assertEqual(len(batches[0]), 9)
        ws = self.run_cli("workspace-batches", "--snapshot", snap, "--page-id", "p-0")
        self.assertEqual(ws[0][0]["type"], "element.upsert")
        listing_path = FIX.parent / "_listing.tmp.json"
        listing_path.write_text(json.dumps({"title": "x", "pageCount": 1, "pages": [{"index": 0, "elements": listing_from(doc)}]}))
        try:
            diff = self.run_cli("diff", "--snapshot", snap, "--listing", str(listing_path))
        finally:
            listing_path.unlink()
        self.assertEqual(diff["counts"]["unchanged"], 9)

    def test_cli_diff_is_page_scoped(self):
        snap = str(FIX / "sites.json")
        doc = self.run_cli("document", "--snapshot", snap, "--split-by-site")
        listing = {"title": "x", "pageCount": 3,
                   "pages": [{"index": i, "elements": listing_from({"pages": [pg]})} for i, pg in enumerate(doc["pages"])]}
        listing_path = FIX.parent / "_listing.tmp.json"
        listing_path.write_text(json.dumps(listing))
        try:
            proc = subprocess.run([sys.executable, str(SKILL / "dojo_document.py"), "diff", "--snapshot", snap,
                                   "--listing", str(listing_path), "--site", "Boston"], capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 2)  # several pages, no --page-index: refuse rather than mis-diff
            self.assertIn("--page-index", proc.stderr)
            bos = self.run_cli("diff", "--snapshot", snap, "--listing", str(listing_path), "--site", "Boston", "--page-index", "0")
            self.assertEqual(bos["counts"], {"to_create": 0, "to_update": 0, "unchanged": 5, "absent_at_source": 0, "ambiguous_links": 0})
            un = self.run_cli("diff", "--snapshot", snap, "--listing", str(listing_path), "--unassigned", "--page-index", "2")
            self.assertEqual(un["counts"]["unchanged"], 1)
            wrong = self.run_cli("diff", "--snapshot", snap, "--listing", str(listing_path), "--site", "Portland", "--page-index", "0")
            self.assertEqual(wrong["counts"]["absent_at_source"], 5)  # Boston's listing against Portland's scope
        finally:
            listing_path.unlink()

    def test_cli_reports_failures(self):
        proc = subprocess.run([sys.executable, str(SKILL / "dojo_document.py"), "identity", "--snapshot", "/nonexistent.json"], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("FileNotFoundError", proc.stderr)


class TestSummarizeResults(unittest.TestCase):
    def test_exact_counts_when_changed_is_present(self):
        results = [
            {"op": "upsert_by_source", "id": "a", "created": True, "changed": True},
            {"op": "upsert_by_source", "id": "b", "created": False, "changed": True},
            {"op": "upsert_by_source", "id": "c", "created": False, "changed": False},
            {"op": "add_node", "id": "z"},
        ]
        self.assertEqual(summarize_results(results), {"created": 1, "updated": 1, "unchanged": 1})

    def test_falls_back_when_an_older_deployment_omits_changed(self):
        results = [
            {"op": "upsert_by_source", "id": "a", "created": True},
            {"op": "upsert_by_source", "id": "b", "created": False},
        ]
        self.assertEqual(summarize_results(results), {"created": 1, "updated": None, "unchanged": None})
        self.assertEqual(summarize_results([]), {"created": 0, "updated": 0, "unchanged": 0})


class TestIdentityCollisions(unittest.TestCase):
    """Review round 2: lossy slugs (finding 4) and lowercased source ids (finding 5)."""

    def test_distinct_devices_keep_distinct_ids_and_exact_source_ids(self):
        snap = fixture("collisions")
        page = build_document(adapt(snap))["pages"][0]
        self.assertEqual(len(page["nodes"]), 4)
        self.assertEqual(len({n["id"] for n in page["nodes"]}), 4)
        self.assertEqual(sorted(n["source"]["id"] for n in page["nodes"]), ["R1", "edge-1", "edge_1", "r1"])
        self.assertEqual(len(page["links"]), 4)
        self.assertEqual(len({l["id"] for l in page["links"]}), 4)
        self.assertEqual(len({l["source"]["id"] for l in page["links"]}), 4)
        for n in page["nodes"]:
            self.assertRegex(n["id"], r"^n-[a-z0-9-]+-[0-9a-f]{6}$")

    def test_ids_stable_across_discoveries_and_readable(self):
        self.assertEqual(node_id("R1"), node_id("R1"))
        self.assertNotEqual(node_id("R1"), node_id("r1"))
        self.assertNotEqual(node_id("edge_1"), node_id("edge-1"))
        self.assertTrue(node_id("bos-rtr1").startswith("n-bos-rtr1-"))

    def test_diff_does_not_merge_case_variants(self):
        base = adapt(fixture("collisions"))
        listing = listing_from(build_document(base))
        d = diff_sourced(listing, base)
        self.assertEqual(d.counts()["unchanged"], 8)
        only_upper = [row for row in listing if row["source"]["id"] != "r1" and "r1:" not in row["source"]["id"]]
        d = diff_sourced(only_upper, base)
        self.assertEqual({e["source"]["id"] for e in d.to_create if e["kind"] == "nodes"}, {"r1"})


class TestMultiPageSync(unittest.TestCase):
    """Review round 2, finding 2: split-by-site re-sync must be page-scoped end to end."""

    def test_page_plan_and_cross_site_links(self):
        base = adapted("sites")
        self.assertEqual(page_plan(base, split_by_site=False), [{"index": 0, "id": "p-0", "name": "Topology", "site": None}])
        plan = page_plan(base, split_by_site=True)
        self.assertEqual([(p["index"], p["id"], p["site"]) for p in plan],
                         [(0, "p-0", "Boston"), (1, "p-1", "Portland"), (2, "p-2", UNASSIGNED)])
        cross = {(l.a, l.b) for l in cross_site_links(base)}
        self.assertEqual(cross, {("bos-rtr1", "pdx-rtr1"), ("pdx-rtr1", "cloud-gw")})
        doc = build_document(base, split_by_site=True)
        drawn = {l["source"]["id"] for pg in doc["pages"] for l in pg["links"]}
        for l in cross_site_links(base):
            self.assertNotIn(l.identity, drawn)
        self.assertEqual(sum(len(pg["links"]) for pg in doc["pages"]), 4)

    def test_per_page_round_trip_after_a_change(self):
        base = adapted("sites")
        doc = build_document(base, split_by_site=True)
        listings = {pg["site"]: listing_from({"pages": [doc["pages"][pg["index"]]]}) for pg in page_plan(base, split_by_site=True)}
        for site, rows in listings.items():
            d = diff_sourced(rows, base, site=site)
            self.assertEqual(d.counts()["to_create"], 0, site)
            self.assertEqual(d.counts()["absent_at_source"], 0, site)
        # add a Boston switch and link it; nothing else changes
        snap = fixture("sites")
        snap["devices"].append({"hostname": "bos-sw2", "role": "switch", "state": None, "interfaces": [], "metadata": {"site": "Boston"}})
        snap["links"].append({"link_id": None, "endpoint_a": {"hostname": "bos-sw1", "interface_name": "ge-0/0/2"},
                              "endpoint_b": {"hostname": "bos-sw2", "interface_name": "ge-0/0/0"}, "state": None, "label": None})
        changed = adapt(snap)
        bos = diff_sourced(listings["Boston"], changed, site="Boston")
        self.assertEqual({e["source"]["id"] for e in bos.to_create if e["kind"] == "nodes"}, {"bos-sw2"})
        self.assertEqual(bos.counts()["to_create"], 2)
        self.assertEqual(bos.counts()["absent_at_source"], 0)
        for site in ("Portland", UNASSIGNED):
            d = diff_sourced(listings[site], changed, site=site)
            self.assertEqual(d.counts()["to_create"], 0, site)
            self.assertEqual(d.counts()["absent_at_source"], 0, site)
        # whole-snapshot diff of one page's listing is exactly the mistake the scope guards against
        wrong = diff_sourced(listings["Boston"], changed)
        self.assertGreater(wrong.counts()["to_create"], 2)

    def test_batches_per_page_are_disjoint_and_cover_everything(self):
        base = adapted("sites")
        seen: list[str] = []
        for pg in page_plan(base, split_by_site=True):
            ops = [op for batch in build_upsert_batches(base, page_index=pg["index"], site=pg["site"]) for op in batch]
            self.assertTrue(all(op["pageIndex"] == pg["index"] for op in ops), pg)
            self.assertTrue(all(op["kind"] != "zone" for op in ops), pg)
            seen.extend(op["source"]["id"] for op in ops)
            ws = [op for batch in build_workspace_batches(base, page_id=pg["id"], site=pg["site"]) for op in batch]
            self.assertEqual({op["pageId"] for op in ws}, {pg["id"]})
            self.assertEqual(len(ws), len(ops))
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(len(seen), 7 + 4)  # every device, every intra-page link; cross-site links on no page


class TestArtifactLookup(unittest.TestCase):
    """Review round 2, finding 1: the local artifact lookup must key on identity, not snapshot id."""

    def test_stem_ignores_snapshot_id_and_lookup_finds_prior_run(self):
        import tempfile
        a = adapted("small")
        snap_b = fixture("small")
        snap_b["snapshot_id"] = "cml-20260921T090000000000"
        b = adapt(snap_b)
        self.assertEqual(identity_stem(a), identity_stem(b))
        name_a = artifact_filename(a, timestamp="20260920T120000Z")
        name_b = artifact_filename(b, timestamp="20260921T090000Z")
        self.assertNotEqual(name_a, name_b)
        self.assertTrue(name_a.startswith("netclaw-cml-lab-pod-1.cml-20260920t120000000000.20260920T120000Z"))
        self.assertTrue(artifact_filename(a, page="Boston", timestamp="t").endswith(".t.boston.json"))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertIsNone(find_latest_artifact(out, identity_stem(b)))
            (out / name_a).write_text("{}")
            (out / "netclaw-cml-lab.cml-x.20260922T000000Z.json").write_text("{}")  # sibling identity, later date
            (out / "netclaw-cml-lab-pod-1.cml-x.20260919T000000Z.json").write_text("{}")  # older run
            found = find_latest_artifact(out, identity_stem(b))
            self.assertEqual(found.name, name_a)


class TestWorkspaceHeadroom(unittest.TestCase):
    def test_workspace_batches_stay_under_the_headroom_cap(self):
        for batch in build_workspace_batches(adapted("large"), page_id="p-0"):
            self.assertLessEqual(len(batch), WORKSPACE_MAX_OPS)
            self.assertLessEqual(len(json.dumps(batch).encode("utf-8")), WORKSPACE_MAX_BYTES)


if __name__ == "__main__":
    unittest.main()
