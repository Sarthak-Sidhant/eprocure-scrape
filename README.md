# eprocure-scrape

Scrapes tenders from [eprocure.gov.in](https://eprocure.gov.in) (GePNIC), 2011 to 2026, in GitHub Actions and reports to
[scrape-hub](https://github.com/Sarthak-Sidhant/scrape-hub), which stores the records in Postgres and shows the live dashboard
at https://scrape.s1d.me. This repo holds only the scraping code; the hub never contains scraper logic.

## The idea: plan by window, then scrape

Scraping one organisation as a single unit leaves the biggest ones (one org-year has 36,000 tenders) pinned to one runner. So the
work is split into **windows** (organisation + date range) first.

1. **Plan** (`plan.py`, then the *Plan* workflow). `data/org_year_counts.json` holds tenders per organisation per year (894,668
   tenders, 2011 to 2026, 733 organisations). An org-year with at most 600 tenders becomes one scrape window. A bigger one gets
   **12 count tasks, one per month**. A count task is one portal search (the results footer says "Total records: N"); if the
   month is still over 1,200 tenders it is **halved** until every window fits. Every count is stored as a record in the hub project
   `eprocure-plan`, which is the tenders-per-window table.
2. **Scrape** (`crawl.py`, the *Scrape* workflow). Each runner claims windows from `eprocure-tenders`, lists the window, fetches each
   tender's status, details and summary pages, and uploads one record per tender (the record carries its window). A runner that
   runs out of its own share takes windows from other slices, so no runner idles while others still have work.

The portal's organisation ids shift when organisations are added, so ids are re-keyed by name against the live dropdown when seeding,
and a window whose organisation label no longer matches is failed rather than scraped.

## Run it

Actions tab:
1. **Plan eprocure windows**: counts the tenders and builds the scrape queue. Smoke test: `max_items=5`. Watch `eprocure-plan` on the
   dashboard; when it finishes, `eprocure-tenders` shows exactly how many windows and tenders will be scraped.
2. **Scrape eprocure windows**: the actual scrape. Smoke test: `total_jobs=2`, `max_items=2`, `max_tenders=5`.

Speed, pause and auto-backoff are set on the dashboard, not here. Documents (PDF/ZIP) are not downloaded, only their links are stored.

## Add another scraper

Make a new repo with its own workflow that has `permissions: id-token: write`, install `scrape-hub-client`, then:

```python
from scrape_hub_client import HubClient, register_project, seed_queue
register_project("my-project", title="...", unit_label="page", record_label="row")
seed_queue("my-project", [{"key": "1", "payload": {"expected": 100}}])
hub = HubClient("my-project", job_index=0, total_jobs=1)
for item in hub.claim(1, steal=True):
    ...                                  # scrape
    hub.record("row-id", {...})
    hub.metric("captcha_ok")
    hub.complete([item["key"]], "done", fetched=100)
hub.close()
```

The first repo to use a project name owns it; other repos get a 403 for it.

## Develop

`pip install -r requirements.txt pytest && pytest` (no network in the tests).
