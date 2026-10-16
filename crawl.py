#!/usr/bin/env python3
"""FY 2025-26 eprocure crawler for GitHub Actions, reporting to scrape-hub.

Each runner claims its slice of organisations from the hub queue, lists every tender in the date window,
fetches the status/details/summary pages for each, and uploads one record per tender. Documents (PDF/ZIP)
are not downloaded; the metadata and links are stored in the record.
"""
import argparse
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "captcha"))

import requests  # noqa: E402
from requests.adapters import HTTPAdapter  # noqa: E402
from scrape_hub_client import HubClient  # noqa: E402

import orgs as orgs_mod  # noqa: E402
import scrape_organization as so  # noqa: E402

PROJECT = "eprocure-fy2526"
FROM_DATE, TO_DATE = "01/04/2025", "31/03/2026"

_seen = {}
_seen_lock = threading.Lock()

MAX_POOL = 16  # worker threads we can ever use; the hub's `threads` setting decides how many run at once


class Gate:
    """A concurrency limit that can be raised or lowered while work is running."""

    def __init__(self, limit):
        self.limit, self.active, self.cv = max(1, limit), 0, threading.Condition()

    def set_limit(self, n):
        with self.cv:
            self.limit = max(1, min(MAX_POOL, int(n)))
            self.cv.notify_all()

    def __enter__(self):
        with self.cv:
            while self.active >= self.limit:
                self.cv.wait(1.0)
            self.active += 1

    def __exit__(self, *exc):
        with self.cv:
            self.active -= 1
            self.cv.notify_all()


class SessionPool:
    """Authenticated portal sessions for one organisation, shared by the worker threads.

    The scraper normally keeps one session per *thread*, and each new session costs a captcha. With a 16-thread pool that
    meant up to 16 captchas per organisation whatever the speed setting. Borrowing from this pool keeps the number of
    sessions at the number actually in use at once (the gate's limit), and each is reused for many tenders.
    """

    def __init__(self):
        self.free, self.lock, self.created = [], threading.Lock(), 0

    def take(self):
        with self.lock:
            return self.free.pop() if self.free else None

    def give(self, session):
        if session is not None:
            with self.lock:
                self.free.append(session)


def fetch_pooled(pool, gate, view_link, tender_id, **kw):
    """fetch_tender_details through a borrowed session; a new one (one captcha) is only made when none is free."""
    with gate:
        so.thread_local.session = pool.take()      # None makes the scraper authenticate a fresh session
        ok = False
        try:
            out = so.fetch_tender_details(view_link, tender_id, **kw)
            ok = True
            return out
        finally:
            sess, so.thread_local.session = getattr(so.thread_local, "session", None), None
            if ok:                                  # a session that raised may be broken, so it is dropped, not reused
                pool.give(sess)


def obey_hub(hub, gate):
    """Apply the dashboard's speed settings: pause while asked to, resize the gate, and space requests out."""
    while hub.settings.get("paused"):
        time.sleep(2)
    gate.set_limit(hub.settings.get("threads", 4))
    delay = hub.settings.get("delay_ms", 0)
    if delay:
        time.sleep(delay / 1000)


def sync_metrics(hub):
    """Move the scraper's counters (captcha_ok, http_429, ...) to the hub as deltas since the last call."""
    with so._metrics_lock:
        snap = dict(so.METRICS)
    with _seen_lock:
        for k, v in snap.items():
            d = v - _seen.get(k, 0)
            if d:
                hub.metric(k, d)
                _seen[k] = v


def list_tenders(org_id, out_dir, max_tenders, retries):
    """All tender rows for the organisation in the window (paged search results)."""
    s = requests.Session()
    s.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=4, max_retries=3))
    s.cookies.set("cookieWorked", "yes", domain="eprocure.gov.in", path="/")
    s.headers.update({"User-Agent": so.USER_AGENT, "Accept-Language": "en-US,en;q=0.5"})
    html = so.fetch_search_page(s, org_id=org_id, max_retries=retries, output_dir=out_dir, from_date=FROM_DATE, to_date=TO_DATE)
    out = []
    while True:
        rows, nxt = so.parse_results_page(html)
        out.extend(rows)
        if not nxt or (max_tenders and len(out) >= max_tenders):
            break
        html = so.safe_request(s, "GET", nxt).text
        time.sleep(0.4)
    return out[:max_tenders] if max_tenders else out


_LIVE = {}


def label_matches(org_id, name):
    """The portal's ids shift when organisations are added; never crawl an id that now means something else."""
    if not _LIVE:
        _LIVE.update(orgs_mod.live_options())
    return orgs_mod.norm(_LIVE.get(org_id, "")) == orgs_mod.norm(name)


def crawl_org(hub, item, args, deadline, gate):
    """Returns (status, error, fetched) for hub.complete()."""
    org_id, name = item["payload"]["org_id"], item["payload"]["org_name"]
    try:
        ok = label_matches(org_id, name)
    except Exception as e:
        hub.block()
        return "failed", f"could not read the portal's organisation list ({type(e).__name__})", 0
    if not ok:
        hub.block()
        return "failed", f"portal id {org_id} now points to {_LIVE.get(org_id, 'nothing')!r}; reseed needed", 0

    out_dir = tempfile.mkdtemp(prefix=f"org{org_id}_")
    expected = int(item["payload"].get("expected") or 0)
    tenders = []
    for _attempt in range(2):  # an empty result for a populated org can be a transient block; retry on a fresh session
        try:
            tenders = list_tenders(org_id, out_dir, args.max_tenders, args.retries)
        except Exception as e:
            hub.block()
            sync_metrics(hub)
            return "failed", f"search failed ({type(e).__name__}: {str(e)[:120]})", 0
        sync_metrics(hub)
        if tenders or not expected:
            break
    short = not args.max_tenders and expected and len(tenders) < expected * 0.9
    if short:
        hub.block()
        if not tenders:
            return "failed", f"portal listed 0 of {expected} expected tenders", 0
    hub.note(f"{name[:60]}: {len(tenders)} tenders" + (f" (expected {expected})" if expected else ""))
    state = {"ok": 0, "failed": 0}
    pool = SessionPool()

    def one(t):
        if time.time() > deadline:
            state["failed"] += 1
            return
        obey_hub(hub, gate)
        try:
            details, *_ = fetch_pooled(pool, gate, t.get("view_link"), t["tender_id"], org_id=org_id,
                                       output_dir=out_dir, from_date=FROM_DATE, to_date=TO_DATE)
            if not details:
                raise RuntimeError("no details parsed")
            hub.record(t["tender_id"], {"org_id": org_id, "org_name": name, "list": t, "details": details})
            state["ok"] += 1
        except Exception:
            state["failed"] += 1
            hub.error()
        sync_metrics(hub)

    with ThreadPoolExecutor(max_workers=MAX_POOL) as ex:
        list(ex.map(one, tenders))
    hub.flush()
    if state["failed"]:
        return "failed", f"{state['failed']} of {len(tenders)} tender pages failed", state["ok"]
    if short:
        return "done", f"listed {len(tenders)} of {expected} expected", state["ok"]
    return "done", "", state["ok"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-index", type=int, default=0)
    ap.add_argument("--total-jobs", type=int, default=1)
    ap.add_argument("--threads", type=int, default=4, help="starting threads per runner; the dashboard setting overrides it")
    ap.add_argument("--retries", type=int, default=10)
    ap.add_argument("--max-tenders", type=int, default=0, help="cap tenders per org (smoke tests)")
    ap.add_argument("--max-orgs", type=int, default=0, help="stop after this many orgs (smoke tests)")
    ap.add_argument("--max-hours", type=float, default=5.5)
    args = ap.parse_args()

    deadline = time.time() + args.max_hours * 3600
    hub = HubClient(PROJECT, args.job_index, args.total_jobs, note="fy2025-26 crawl")
    hub.settings["threads"] = args.threads   # starting value; the hub's setting replaces it on the first response
    gate = Gate(args.threads)
    done = 0
    try:
        while time.time() < deadline and not (args.max_orgs and done >= args.max_orgs):
            items = hub.claim(1)
            if hub.settings.get("paused"):
                time.sleep(5)          # paused from the dashboard: hold, keep the heartbeat alive, then ask again
                continue
            if not items:
                break
            item = items[0]
            status, error, fetched = crawl_org(hub, item, args, deadline, gate)
            hub.complete([item["key"]], status, error=error, fetched=fetched)
            done += 1
        hub.close("finished", f"{done} orgs")
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    main()
