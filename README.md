# eprocure-scrape

Scrapes tenders from [eprocure.gov.in](https://eprocure.gov.in) (GePNIC) for FY 2025-26 in GitHub Actions and reports to
[scrape-hub](https://github.com/Sarthak-Sidhant/scrape-hub), which stores the records in Postgres and shows the live dashboard
at https://scrape.s1d.me. This repo holds only the scraping code; the hub never contains scraper logic.

## How a run works

1. **Seed** (`seed.py`): registers the project `eprocure-fy2526` with the hub and queues one item per organisation that has tenders
   in the window (428 organisations, about 47,973 tenders). The portal's organisation ids shift when organisations are added, so the
   September counts in `data/` are re-keyed by name against today's dropdown.
2. **Crawl** (`crawl.py`, 20 parallel slices): each runner claims organisations from the hub queue (slice `i` takes queue partitions
   where `partition % total_jobs == i`), solves the portal captcha with the bundled CNN (`captcha/`), lists every tender in the date
   window, fetches the status, details and summary pages, and uploads one JSON record per tender.
3. **Report**: records, errors, blocks and custom counters (`captcha_ok`, `captcha_fail`, `http_429`, ...) go to the hub through
   [`scrape-hub-client`](https://github.com/Sarthak-Sidhant/scrape-hub/tree/main/client). The runner authenticates with a short-lived
   GitHub OIDC token, so the hub knows which repository is calling and no secrets are stored here.

Safety checks: an organisation whose live portal label no longer matches its queued name is failed instead of crawled, and one that
lists fewer than 90% of its expected tenders is flagged rather than marked done.

## Run it

Actions tab, **Crawl eprocure FY 2025-26**, Run workflow. For a smoke test use `total_jobs=2`, `max_orgs=1`, `max_tenders=5`.
The default (20 runners, no caps) crawls everything and takes hours. Failed organisations stay failed until you tick `reset_failed`
or press Retry on the dashboard.

Documents (PDF/ZIP) are not downloaded, only their links are stored in each record.

## Add another scraper

Make a new repo with its own workflow that has `permissions: id-token: write`, install `scrape-hub-client`, then:

```python
from scrape_hub_client import HubClient, register_project, seed_queue
register_project("my-project", title="...", unit_label="page", record_label="row")
seed_queue("my-project", [{"key": "1", "payload": {"expected": 100}}])
hub = HubClient("my-project", job_index=0, total_jobs=1)
for item in hub.claim(1):
    ...                                  # scrape
    hub.record("row-id", {...})
    hub.metric("captcha_ok")
    hub.complete([item["key"]], "done", fetched=100)
hub.close()
```

The first repo to use a project name owns it; other repos get a 403 for it.

## Develop

`pip install -r requirements.txt pytest && pytest` (the tests cover the id remapping; there is no network access in them).
