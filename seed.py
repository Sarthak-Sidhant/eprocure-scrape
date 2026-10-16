#!/usr/bin/env python3
"""Register the project with scrape-hub and fill its queue: one item per organisation that has tenders in the window.

The portal's organisation ids shift when organisations are added (320 of 428 changed between September and
October 2026), so the September counts in data/ are re-keyed by name against today's dropdown.
Safe to re-run: existing queue items are left alone. Use --reset-failed to requeue failed ones.
"""
import argparse
import json
import os

from scrape_hub_client import register_project, seed_queue

import orgs

PROJECT = "eprocure-fy2526"
COUNTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "org_counts_fy2025_2026.json")


def remap_counts(counts, live):
    """counts: {old_id: {name, tenders_count}}, live: {id: label}. Returns ({new_id: entry}, ids_changed, skipped)."""
    by_name = {}
    for oid, label in live.items():
        by_name.setdefault(orgs.norm(label), []).append(oid)
    out, moved, skipped = {}, 0, []
    for old, v in counts.items():
        if v["tenders_count"] <= 0:
            continue
        ids = by_name.get(orgs.norm(v["name"]), [])
        if len(ids) != 1:
            skipped.append((old, v["name"], v["tenders_count"], len(ids)))
            continue
        moved += ids[0] != old
        out[ids[0]] = v
    return out, moved, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated live org ids (smoke tests)")
    ap.add_argument("--reset-failed", action="store_true")
    a = ap.parse_args()
    counts = json.load(open(COUNTS))
    remapped, moved, skipped = remap_counts(counts, orgs.live_options())
    print(f"{len(remapped)} orgs with tenders, {moved} ids changed since the counts, {len(skipped)} unmatched or ambiguous")
    for sk in skipped:
        print("  SKIPPED", sk)
    only = {x for x in a.only.split(",") if x}
    chosen = sorted(((k, v) for k, v in remapped.items() if not only or k in only), key=lambda kv: -kv[1]["tenders_count"])
    register_project(PROJECT, title="eProcure FY 2025-26 tenders", unit_label="organisation", record_label="tender",
                     expected_units=len(chosen), expected_records=sum(v["tenders_count"] for _, v in chosen))
    items = [{"key": k, "partition_id": i, "payload": {"org_id": k, "org_name": v["name"], "expected": v["tenders_count"]}}
             for i, (k, v) in enumerate(chosen)]
    print("queue:", seed_queue(PROJECT, items, reset_failed=a.reset_failed))


if __name__ == "__main__":
    main()
