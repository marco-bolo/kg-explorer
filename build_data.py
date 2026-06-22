#!/usr/bin/env python3
"""
build_data.py  —  Bundle MARCO-BOLO JSON-LD into data.json for KG Explorer.

Adapted from sdiggs/kg-explorer's build_data.py. The input is now the
schema.org-compacted JSON-LD output of the marco-bolo/csv-to-json-ld
pipeline (one file per entity, plus one *-input-metadata.json sidecar
per entity) rather than the per-interview JSON files Steve's tool was
built around.

Usage:
    python build_data.py                              # default: ./schema-jsonld/
    python build_data.py --src path/to/schema-jsonld  # custom location
    python build_data.py --check                      # dry run, no write
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

MBO_PREFIX = "https://w3id.org/marco-bolo/"

TYPE_TO_KIND = {
    "CreateAction": "action", "Action": "action",
    "Dataset": "dataset",
    "DataDownload": "datadownload",
    "DigitalDocument": "document", "Document": "document",
    "HowTo": "howto", "HowToStep": "howto", "HowToTip": "howto",
    "Person": "person", "Researcher": "person",
    "Organization": "org", "ResearchOrganization": "org",
    "EducationalOrganization": "org", "CollegeOrUniversity": "org",
    "GovernmentOrganization": "org", "ResearchProject": "org",
    "ArchiveOrganization": "org", "ProfessionalService": "org",
    "ContactPoint": "contact",
    "Place": "place", "GeoShape": "place",
    "PropertyValue": "property",
    "SoftwareApplication": "software", "WebApplication": "software",
    "SoftwareSourceCode": "software",
    "Service": "service",
    "Thing": "instrument",
    "Vehicle": "platform",
    "DefinedTerm": "term",
    "Statement": "embargo",
    "MonetaryGrant": "grant", "MonetaryAmount": "grant",
    "Audience": "audience", "EducationalAudience": "audience",
    "Comment": "comment",
    "CreativeWork": "license",
    "Taxon": "taxon",
}

def refine_action_kind(name: str) -> str:
    n = (name or "").lower()
    if "deliverable" in n: return "deliverable"
    if "task" in n: return "task"
    return "action"

PRODUCTION_EDGES = {"result", "step", "itemListElement", "distribution",
                    "encodesCreativeWork"}

WP_NAME_RE = re.compile(
    r"(?:WP|Work\s*Package|Task|Deliverable|^T|^D)\s*(\d)\b", re.I)


def strip_uri(u) -> str:
    if isinstance(u, dict):
        u = u.get("@id", "")
    if not isinstance(u, str):
        return ""
    if u.startswith(MBO_PREFIX):
        return u[len(MBO_PREFIX):]
    return u


def first(x):
    if isinstance(x, list):
        return x[0] if x else None
    return x


def label_for(doc: dict) -> str:
    n = first(doc.get("name"))
    if n: return str(n).strip()
    g, f = doc.get("givenName"), doc.get("familyName")
    if g or f:
        return f"{(g or '').strip()} {(f or '').strip()}".strip()
    for key in ("title", "termCode", "legalName", "description", "abstract"):
        v = first(doc.get(key))
        if v: return str(v)[:80].strip()
    return strip_uri(doc.get("@id", "")) or "(no label)"


def kind_for(doc: dict) -> str:
    t = doc.get("@type", "Thing")
    if isinstance(t, list): t = t[0]
    k = TYPE_TO_KIND.get(t, "other")
    if k == "action":
        return refine_action_kind(label_for(doc))
    return k


def _flatten_value(v):
    """Reduce a JSON-LD value to a plain scalar for the property bag.

    - {"@value": x, "@type": _}   → x  (typed literals like xsd:decimal)
    - {"@id": ...}                → None (it's an edge, not a scalar)
    - {nested dict without @id}   → JSON-encoded string (rare; keep info)
    - [list]                      → list of flattened elements (None-filtered)
    - plain scalar                → unchanged
    """
    if isinstance(v, list):
        out = [_flatten_value(x) for x in v]
        out = [x for x in out if x is not None]
        if not out: return None
        return out[0] if len(out) == 1 else out
    if isinstance(v, dict):
        if "@id" in v:
            return None      # this is an edge, handled elsewhere
        if "@value" in v:
            return v["@value"]
        try:
            return json.dumps(v, ensure_ascii=False)
        except Exception:
            return str(v)
    return v


def _scalar_props(doc: dict) -> dict:
    """Return the property bag: every non-@ key whose value is a scalar
    (not an @id reference). Properties already surfaced as first-class fields
    on the node (name, abstract, description) are skipped to avoid duplication."""
    skip = {"name", "abstract", "description"}
    out = {}
    for k, v in doc.items():
        if k.startswith("@") or k in skip:
            continue
        scalar = _flatten_value(v)
        if scalar is not None and scalar != "":
            out[k] = scalar
    return out


def load_pair_dir(src: Path):
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    skipped = []

    entity_files = sorted(f for f in src.glob("*.json")
                          if "-input-metadata" not in f.name)
    sidecar_files = sorted(src.glob("*-input-metadata.json"))

    for fp in entity_files:
        try:
            data = json.loads(fp.read_text())
        except Exception as ex:
            skipped.append((fp.name, str(ex))); continue

        docs = data["@graph"] if isinstance(data, dict) and "@graph" in data else [data]
        for doc in docs:
            uid = strip_uri(doc.get("@id"))
            if not uid or "#" in uid:
                continue
            t = doc.get("@type", "Thing")
            if isinstance(t, list): t = t[0]
            node = {
                "id": uid,
                "uri": doc.get("@id", ""),
                "type": t,
                "label": label_for(doc),
                "kind": kind_for(doc),
                "wp": None,
                "wp_via": None,
                "name": first(doc.get("name")) or "",
                "abstract": first(doc.get("abstract")) or "",
                "description": first(doc.get("description")) or "",
                "src_file": fp.name,
                # Full scalar property bag for the side-panel detail view.
                # Excludes @-properties and {"@id": ...} reference-shaped values
                # (those become edges). Typed-literal {"@type":..., "@value":...}
                # values are flattened to their @value string.
                "props": _scalar_props(doc),
            }
            nodes[uid] = node

            for prop, val in doc.items():
                if prop.startswith("@"): continue
                for tgt in (val if isinstance(val, list) else [val]):
                    if isinstance(tgt, dict) and tgt.get("@id"):
                        t_uid = strip_uri(tgt["@id"])
                        if t_uid and "#" not in t_uid and t_uid != uid:
                            edges.append({"from": uid, "to": t_uid, "kind": prop})

    parent_via_sidecar: dict[str, str] = {}
    for fp in sidecar_files:
        try:
            sc = json.loads(fp.read_text())
        except Exception as ex:
            skipped.append((fp.name, str(ex))); continue

        described = strip_uri(sc.get("@id", "")).replace("-input-metadata", "")
        if not described:
            continue
        rev = sc.get("@reverse", {}) or {}
        parent_action = strip_uri(rev.get("result"))
        if parent_action and parent_action != described:
            parent_via_sidecar[described] = parent_action
            edges.append({"from": described, "to": parent_action,
                          "kind": "wasResultOf"})
        creator = strip_uri(sc.get("creator"))
        if creator and creator != described:
            edges.append({"from": described, "to": creator,
                          "kind": "metadataEnteredBy"})

    return nodes, edges, skipped, parent_via_sidecar


def attribute_wps(nodes, edges, parent_via_sidecar):
    """Annotate every node with `wp` (primary), `wps` (all WPs the node touches),
    and `wp_via` (inference path).

    Attribution rules, tried in order:
      1. Parse the node's own name/abstract for "WP N", "Task N", "Deliverable N".
      2. Walk up via the sidecar's parent Action.
      3. Walk up via any inbound `result` edge (someone listed me as a result).
      4. (NEW) For people/orgs/anything else without their own WP: inherit
         from inbound credit edges (`author`, `agent`, `participant`,
         `contributor`, `funder`, `sponsor`, `provider`, `maintainer`). A
         Person credited as author of D1.1 and D1.2 picks up WP1 from both.
         Persons working across multiple WPs end up with a multi-WP `wps`
         list; `wp` is the most-cited one (ties broken by lowest WP number).
    """
    def parse_wp(text):
        if not text: return None
        m = WP_NAME_RE.search(text)
        return f"WP{m.group(1)}" if m else None

    inverse_result = {}
    for e in edges:
        if e["kind"] == "result":
            inverse_result.setdefault(e["to"], e["from"])

    def resolve_single(uid, depth=0, seen=None):
        """Rules 1–3: try to find a single WP via the upward walk."""
        if seen is None: seen = set()
        if uid in seen or depth > 6 or uid not in nodes:
            return None, "depth-limit"
        seen.add(uid)
        n = nodes[uid]
        wp = parse_wp(n.get("name") or n.get("abstract") or n.get("description"))
        if wp: return wp, "self-name"
        p = parent_via_sidecar.get(uid)
        if p:
            wp, via = resolve_single(p, depth+1, seen)
            if wp: return wp, f"sidecar->{via}"
        p = inverse_result.get(uid)
        if p:
            wp, via = resolve_single(p, depth+1, seen)
            if wp: return wp, f"result-of->{via}"
        return None, "no-parent"

    # Pass 1 — apply rules 1–3.
    for uid, n in nodes.items():
        wp, via = resolve_single(uid)
        n["wp"] = wp
        n["wp_via"] = via
        n["wps"] = [wp] if wp else []

    # Pass 2 (NEW, rule 4) — for any node still without a WP, inherit from
    # inbound credit-edges. The crediting entity must itself have a WP
    # (from pass 1). Build the inverse credit-edge map first.
    CREDIT_EDGES = {"author", "agent", "participant", "contributor",
                    "funder", "sponsor", "provider", "maintainer", "creator"}
    inbound_credits = defaultdict(list)   # node_uid -> [(crediting_uid, edge_kind)]
    for e in edges:
        if e["kind"] in CREDIT_EDGES and e["to"] in nodes and e["from"] in nodes:
            inbound_credits[e["to"]].append((e["from"], e["kind"]))

    for uid, n in nodes.items():
        if n["wp"]:
            continue   # already attributed by rules 1–3
        wp_counter = Counter()
        kinds_per_wp = defaultdict(set)
        for from_uid, kind in inbound_credits.get(uid, []):
            from_wp = nodes[from_uid].get("wp")
            if from_wp:
                wp_counter[from_wp] += 1
                kinds_per_wp[from_wp].add(kind)
        if not wp_counter:
            continue
        # Multi-WP attribution: keep every WP this node is credited under;
        # primary = most-cited (ties broken by lowest WP number).
        all_wps = sorted(wp_counter.keys(),
                         key=lambda w: (-wp_counter[w], w))
        n["wp"] = all_wps[0]
        n["wps"] = all_wps
        n["wp_via"] = "credited-by->" + "+".join(
            sorted(kinds_per_wp[all_wps[0]]))

    # Multi-WP enrichment for nodes that DID get a primary WP from rule 1-3
    # but are also credited under other WPs (e.g. an Org that is itself
    # named "MARCO-BOLO WP4" but whose members are credited in WP3 too).
    # Cheap pass — only adds extras to `wps`, doesn't change `wp`.
    for uid, n in nodes.items():
        if not n["wp"]:
            continue
        extra = set(n["wps"])
        for from_uid, _ in inbound_credits.get(uid, []):
            from_wp = nodes[from_uid].get("wp")
            if from_wp:
                extra.add(from_wp)
        n["wps"] = sorted(extra, key=lambda w: (w != n["wp"], w))


def compute_stats(nodes, edges):
    wp_stats = defaultdict(Counter)
    for n in nodes.values():
        if n["wp"]:
            wp_stats[n["wp"]][n["kind"]] += 1

    out_production = defaultdict(set)
    for e in edges:
        if e["kind"] in PRODUCTION_EDGES:
            out_production[e["from"]].add(e["kind"])

    orphans = {"tasks": [], "deliverables": []}
    for uid, n in nodes.items():
        if n["kind"] == "task" and not out_production.get(uid):
            orphans["tasks"].append(uid)
        elif n["kind"] == "deliverable" and not out_production.get(uid):
            orphans["deliverables"].append(uid)

    return {
        "wp_stats": {wp: dict(c) for wp, c in sorted(wp_stats.items())},
        "orphans": orphans,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default="schema-jsonld")
    ap.add_argument("--out", default="data.json")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.is_dir():
        print(f"ERROR: {src} not found.")
        sys.exit(1)

    print(f"Walking {src}/ ...")
    nodes, edges, skipped, parent_via_sidecar = load_pair_dir(src)
    if skipped:
        print(f"  {len(skipped)} files failed to parse")

    known = set(nodes.keys())
    pre_edge = len(edges)
    edges = [e for e in edges if e["from"] in known and e["to"] in known]
    dropped = pre_edge - len(edges)

    attribute_wps(nodes, edges, parent_via_sidecar)
    stats = compute_stats(nodes, edges)

    wp_summary = {wp: sum(c.values()) for wp, c in stats["wp_stats"].items()}
    unattributed = sum(1 for n in nodes.values() if not n["wp"])

    print()
    print(f"  nodes:     {len(nodes)}")
    print(f"  edges:     {len(edges)}  (dropped {dropped} dangling)")
    print(f"  per-WP:    {wp_summary}")
    print(f"  unattributed: {unattributed}")
    print(f"  orphan tasks:        {len(stats['orphans']['tasks'])}")
    print(f"  orphan deliverables: {len(stats['orphans']['deliverables'])}")

    if args.check:
        print("\nDry run; no file written.")
        return 0

    bundle = {
        "version": "2.0-mbo-jsonld",
        "built":    dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source":   str(src),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes":    sorted(nodes.values(), key=lambda n: n["id"]),
        "edges":    edges,
        "wp_stats": stats["wp_stats"],
        "orphans":  stats["orphans"],
    }
    Path(args.out).write_text(json.dumps(bundle, ensure_ascii=False,
                                         separators=(",", ":")))
    size_kb = os.path.getsize(args.out) / 1024
    print(f"\nWrote {args.out}  ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
