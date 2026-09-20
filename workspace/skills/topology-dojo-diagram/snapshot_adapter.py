"""
snapshot_adapter.py — spec 124 (Topology Dojo topology documentation provider).

Consumes NetClaw's canonical Topology Snapshot exactly as every source adapter produces it
(`workspace/skills/comfyui-topology-viz/topology_model.py`, spec 120, from spec 046):

    TopologySnapshot(snapshot_id, source_kind, source_label, created_at, devices, links)
    Device(hostname, role, state, interfaces, metadata)
    Interface(name, parent_hostname, ip_address, state, metadata)
    LinkEndpoint(hostname, interface_name)
    Link(link_id, endpoint_a, endpoint_b, state, label)

accepted either as those dataclasses or as their `dataclasses.asdict` / JSON form (the contract
fixtures are serialized from the real `_build_snapshot()`), plus an optional per-link overlay for
data the canonical model does not carry (reconciliation status, VLAN, bandwidth, transport).

Nothing here imports another skill's module — the repo's copy-and-trim convention — and nothing
here talks to Topology Dojo. Pure, deterministic, stdlib only.
"""

from __future__ import annotations

import ast
import dataclasses
import ipaddress
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

log = logging.getLogger("topology_dojo.snapshot_adapter")

# The union of NetClaw's existing denylist (spec 120/122 FORBIDDEN_METADATA_KEYS) with two keys a
# network discovery routinely carries (FR-014). Matched case-insensitively at every depth.
FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "credential",
        "credentials",
        "api_key",
        "apikey",
        "token",
        "running_config",
        "startup_config",
        "config",
        "private_key",
        "community",
    }
)

CANONICAL_ROLES = ("router", "switch", "firewall", "load_balancer", "client", "unclassified")
CANONICAL_STATES = ("healthy", "degraded", "down", "unknown")
RECONCILIATION_STATUSES = ("DOCUMENTED", "UNDOCUMENTED", "MISSING", "MISMATCH")

_SYNTHETIC_LINK_ID = re.compile(r"^link-\d+$")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


class SnapshotAdapterError(ValueError):
    """Raised when the canonical snapshot violates its own validation rules."""


_DROPPED = object()
# A forbidden key name used as a mapping key inside serialized text: `'community': ...`,
# `"password": ...`, `token=...`. The canonical `sanitize_metadata` in the topology model is
# shallow and stringifies nested values with `str()`, so a nested credential arrives here as
# text, not as a key. Matched case-insensitively.
_SERIALIZED_SECRET = re.compile(
    r"(?<![a-z0-9_])(?:" + "|".join(sorted(FORBIDDEN_KEYS)) + r")(?![a-z0-9_])['\"]?\s*[:=]",
    re.IGNORECASE,
)


def _parse_serialized(text: str) -> Any:
    """Best-effort decode of a string that looks like a serialized mapping or list."""
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        return json.loads(stripped)
    except ValueError:
        pass
    try:
        return ast.literal_eval(stripped)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return None


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if str(k).strip().lower() in FORBIDDEN_KEYS:
                continue
            cleaned = _sanitize(v)
            if cleaned is not _DROPPED:
                out[str(k)] = cleaned
        return out
    if isinstance(value, (list, tuple)):
        return [c for c in (_sanitize(v) for v in value) if c is not _DROPPED]
    if isinstance(value, str):
        parsed = _parse_serialized(value)
        if isinstance(parsed, (dict, list, tuple)):
            # Re-serialize through the sanitizer so nested secrets are removed, not just hidden.
            return _sanitize(parsed)
        if _SERIALIZED_SECRET.search(value):
            log.debug("dropping string metadata value that embeds a credential-shaped key")
            return _DROPPED
    return value


def sanitize_recursive(value: Any) -> Any:
    """Strip credential-shaped keys at any depth, including inside stringified mappings.

    Mappings and lists are walked structurally. A string value that decodes as a mapping or
    list (JSON or Python literal — the shape `str(dict)` produces) is decoded and sanitized
    structurally. Any other string that still names a forbidden key in mapping position is
    dropped outright: it is cheaper to lose one opaque value than to leak a community string.
    Returns a new value; the input is not mutated.
    """
    cleaned = _sanitize(value)
    return None if cleaned is _DROPPED else cleaned


def slug(text: str) -> str:
    """Deterministic `[a-z0-9-]` component for element ids and filenames."""
    s = _SLUG_STRIP.sub("-", str(text).strip().lower()).strip("-")
    return s or "x"


def document_identity(source_kind: str, source_label: str) -> str:
    """Stable across discoveries (FR-004a): never derived from the per-run snapshot id."""
    return f"netclaw:{slug(source_kind)}:{slug(source_label or source_kind)}"


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _as_dict(obj: Any) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    raise SnapshotAdapterError(f"unsupported snapshot object: {type(obj).__name__}")


@dataclass
class AdaptedDevice:
    hostname: str
    role: str
    state: Optional[str]
    meta: dict
    site: Optional[str]
    platform: Optional[str]
    interfaces: dict = field(default_factory=dict)  # name -> ip_address (may be None)


@dataclass
class AdaptedLink:
    identity: str
    ambiguous: bool
    a: str
    b: str
    a_interface: Optional[str]
    b_interface: Optional[str]
    label: str
    state: Optional[str]
    link_id: str
    subnet: Optional[str] = None
    vlan: Optional[str] = None
    bandwidth: Optional[str] = None
    transport: Optional[str] = None
    reconciliation: Optional[str] = None


@dataclass
class AdaptedSnapshot:
    document_identity: str
    title: str
    system: str
    provenance: dict
    devices: list[AdaptedDevice]
    links: list[AdaptedLink]
    sites: list[str]

    def device(self, hostname: str) -> Optional[AdaptedDevice]:
        return next((d for d in self.devices if d.hostname == hostname), None)


def _subnet_for(dev_a: Optional[AdaptedDevice], if_a: Optional[str],
                dev_b: Optional[AdaptedDevice], if_b: Optional[str]) -> Optional[str]:
    """Only when both endpoint interfaces carry a prefix length and agree on the network."""
    nets = []
    for dev, name in ((dev_a, if_a), (dev_b, if_b)):
        if not dev or not name:
            return None
        ip = dev.interfaces.get(name)
        if not ip or "/" not in str(ip):
            return None
        try:
            nets.append(ipaddress.ip_interface(str(ip)).network)
        except ValueError:
            return None
    return str(nets[0]) if nets[0] == nets[1] else None


def _endpoint(raw: Any) -> tuple[str, Optional[str]]:
    d = _as_dict(raw)
    hostname = str(d.get("hostname") or "")
    iface = d.get("interface_name")
    return hostname, (str(iface) if iface else None)


def link_identity(link: dict, ordinal: int, siblings: int) -> tuple[str, bool]:
    """
    Precedence (FR-004, research R5): a real source-supplied link_id; else the sorted
    endpoint:interface pair; else sorted hostnames + a deterministic ordinal, flagged ambiguous
    when more than one interface-less link joins the same pair.
    """
    link_id = str(link.get("link_id") or "")
    a, if_a = _endpoint(link.get("endpoint_a"))
    b, if_b = _endpoint(link.get("endpoint_b"))
    if link_id and not _SYNTHETIC_LINK_ID.match(link_id):
        return link_id, False
    if if_a and if_b:
        pair = sorted([f"{a}:{if_a}", f"{b}:{if_b}"])
        return f"{pair[0]}|{pair[1]}", False
    hosts = sorted([a, b])
    return f"{hosts[0]}|{hosts[1]}#{ordinal}", siblings > 1


def adapt(snapshot: Any, overlay: Optional[dict] = None) -> AdaptedSnapshot:
    """
    Validate + adapt a canonical snapshot. `overlay` is `{link_id: {reconciliation, vlan,
    bandwidth, transport}}`, every key optional. Raises SnapshotAdapterError on an empty snapshot,
    duplicate hostnames, or a link endpoint that names no declared device.
    """
    snap = _as_dict(snapshot)
    system = str(_enum_value(snap.get("source_kind")) or "").strip()
    if not system:
        raise SnapshotAdapterError("snapshot has no source_kind")
    source_label = str(snap.get("source_label") or system)
    created_at = snap.get("created_at")
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    provenance = {"snapshot_id": str(snap.get("snapshot_id") or ""), "created_at": created_at}

    devices: list[AdaptedDevice] = []
    seen: set[str] = set()
    for raw in snap.get("devices") or []:
        d = _as_dict(raw)
        hostname = str(d.get("hostname") or "").strip()
        if not hostname:
            raise SnapshotAdapterError("device without hostname")
        if hostname in seen:
            raise SnapshotAdapterError(f"duplicate hostname {hostname!r}")
        seen.add(hostname)
        role = str(_enum_value(d.get("role")) or "unclassified")
        if role not in CANONICAL_ROLES:
            log.warning("device %s has non-canonical role %r; treating as unclassified", hostname, role)
            role = "unclassified"
        state = _enum_value(d.get("state"))
        state = str(state) if state in CANONICAL_STATES else None
        meta = sanitize_recursive(d.get("metadata") or {})
        interfaces: dict = {}
        for iface in d.get("interfaces") or []:
            i = _as_dict(iface)
            name = str(i.get("name") or "")
            if name:
                interfaces[name] = i.get("ip_address")
        site = meta.get("site") or meta.get("location")
        platform = meta.get("platform") or meta.get("model")
        devices.append(
            AdaptedDevice(
                hostname=hostname,
                role=role,
                state=state,
                meta={k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool))},
                site=str(site) if site else None,
                platform=str(platform) if platform else None,
                interfaces=interfaces,
            )
        )
    if not devices:
        raise SnapshotAdapterError("snapshot has no devices — nothing to document")
    by_host = {d.hostname: d for d in devices}

    # Ordinals for rule-3 identities: per unordered pair, sorted by (label, state) — deterministic.
    raw_links = [_as_dict(l) for l in snap.get("links") or []]
    rule3: dict[tuple[str, str], list[int]] = {}
    for idx, l in enumerate(raw_links):
        link_id = str(l.get("link_id") or "")
        a, if_a = _endpoint(l.get("endpoint_a"))
        b, if_b = _endpoint(l.get("endpoint_b"))
        if (not link_id or _SYNTHETIC_LINK_ID.match(link_id)) and not (if_a and if_b):
            rule3.setdefault(tuple(sorted([a, b])), []).append(idx)
    ordinal_of: dict[int, tuple[int, int]] = {}
    for idxs in rule3.values():
        ordered = sorted(idxs, key=lambda i: (str(raw_links[i].get("label") or ""), str(_enum_value(raw_links[i].get("state")) or "")))
        for n, i in enumerate(ordered):
            ordinal_of[i] = (n, len(ordered))

    overlay = sanitize_recursive(overlay or {})
    links: list[AdaptedLink] = []
    for idx, l in enumerate(raw_links):
        a, if_a = _endpoint(l.get("endpoint_a"))
        b, if_b = _endpoint(l.get("endpoint_b"))
        for h in (a, b):
            if h not in by_host:
                raise SnapshotAdapterError(f"link {l.get('link_id')!r} references unknown device {h!r}")
        ordinal, siblings = ordinal_of.get(idx, (0, 1))
        identity, ambiguous = link_identity(l, ordinal, siblings)
        link_id = str(l.get("link_id") or "")
        ov = _as_dict(overlay.get(link_id)) if link_id else {}
        reconciliation = str(ov.get("reconciliation") or "").upper() or None
        if reconciliation and reconciliation not in RECONCILIATION_STATUSES:
            log.warning("link %s overlay reconciliation %r unknown; ignored", link_id, reconciliation)
            reconciliation = None
        state = _enum_value(l.get("state"))
        links.append(
            AdaptedLink(
                identity=identity,
                ambiguous=ambiguous,
                a=a,
                b=b,
                a_interface=if_a,
                b_interface=if_b,
                label=str(l.get("label") or ""),
                state=str(state) if state in CANONICAL_STATES else None,
                link_id=link_id,
                subnet=_subnet_for(by_host.get(a), if_a, by_host.get(b), if_b),
                vlan=(str(ov["vlan"]) if ov.get("vlan") not in (None, "") else None),
                bandwidth=(str(ov["bandwidth"]) if ov.get("bandwidth") else None),
                transport=(str(ov["transport"]) if ov.get("transport") else None),
                reconciliation=reconciliation,
            )
        )

    sites = sorted({d.site for d in devices if d.site})
    return AdaptedSnapshot(
        document_identity=document_identity(system, source_label),
        title=f"NetClaw — {system} — {source_label}",
        system=system,
        provenance=provenance,
        devices=devices,
        links=links,
        sites=sites,
    )


def adapted_to_dict(adapted: AdaptedSnapshot) -> dict:
    return dataclasses.asdict(adapted)


def load_overlay(rows: Iterable[dict]) -> dict:
    """Accept either `{link_id: {...}}` or a list of `{link_id, ...}` rows."""
    if isinstance(rows, dict):
        return dict(rows)
    out: dict = {}
    for row in rows:
        r = dict(row)
        key = str(r.pop("link_id", "") or "")
        if key:
            out[key] = r
    return out
