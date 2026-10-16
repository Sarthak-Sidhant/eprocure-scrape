#!/usr/bin/env python3
"""Register both projects with scrape-hub and seed them from the per-organisation, per-year counts in data/.

  eprocure-tenders  one queue item per (organisation, date window) to scrape
  eprocure-plan     month-by-month count tasks for org-years too big to scrape as one chunk

The portal's organisation ids shift when organisations are added, so the saved counts are re-keyed by name against
today's dropdown. Safe to re-run: existing queue items are left alone.
"""
import argparse
import json
import os

from scrape_hub_client import register_project, seed_queue

import orgs
import windows

TENDERS = "eprocure-tenders"
PLAN = "eprocure-plan"
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "org_year_counts.json")


def remap_by_name(saved, live):
    """saved: {old_id: {name, years}}, live: {id: label}. Returns ({live_id: entry}, ids_changed, skipped)."""
    by_name = {}
    for oid, label in live.items():
        by_name.setdefault(orgs.norm(label), []).append(oid)
    out, moved, skipped = {}, 0, []
    for old, v in saved.items():
        ids = by_name.get(orgs.norm(v["name"]), [])
        if len(ids) != 1:
            skipped.append((old, v["name"], sum(v["years"].values()), len(ids)))
            continue
        moved += ids[0] != old
        out[ids[0]] = v
    return out, moved, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-year", type=int, default=2011)
    ap.add_argument("--to-year", type=int, default=2026)
    ap.add_argument("--split-over", type=int, default=600, help="org-years with more tenders than this are counted by month first")
    ap.add_argument("--chunk-max", type=int, default=1200, help="a window with more tenders than this is halved until it fits")
    ap.add_argument("--only", default="", help="comma-separated live org ids (smoke tests)")
    ap.add_argument("--reset-failed", action="store_true")
    a = ap.parse_args()

    saved = json.load(open(DATA))
    remapped, moved, skipped = remap_by_name(saved, orgs.live_options())
    print(f"{len(remapped)} organisations matched, {moved} ids changed since the counts, {len(skipped)} unmatched or ambiguous")
    for sk in skipped:
        print("  SKIPPED", sk)
    only = {x for x in a.only.split(",") if x}
    chosen = {k: v for k, v in remapped.items() if not only or k in only}
    crawl, counts, summary = windows.build_plan(chosen, a.from_year, a.to_year, a.split_over, a.chunk_max)
    print(summary)
    expected = summary["direct_tenders"] + summary["split_tenders"]
    register_project(TENDERS, title=f"eProcure tenders {a.from_year}-{a.to_year}", unit_label="window", record_label="tender",
                     expected_units=len(crawl), expected_records=expected)
    register_project(PLAN, title="eProcure monthly plan", unit_label="count task", record_label="count",
                     expected_units=len(counts))
    print("crawl queue:", seed_queue(TENDERS, crawl, reset_failed=a.reset_failed))
    print("count queue:", seed_queue(PLAN, counts, reset_failed=a.reset_failed))


if __name__ == "__main__":
    main()
