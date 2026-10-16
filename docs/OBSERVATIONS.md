# Scrape observations and optimisation log

Rule for this project: **observe, write it down, optimise everything known, verify with a small test, then run.** Do not cancel or
restart a healthy big run on a guess. Update this file before every large run.

## Run 1: 2026-10-16, 12:33:55 to 12:59 (stopped by the operator at 26 minutes)

Setup: 20 GitHub runners, one Python process each, no caps, documents on. Speed 4 threads per runner (Normal) until 12:48:57,
then 16 (Max). Queue: 1,485 windows, 895,058 tenders, balanced 74 to 75 windows per slice.

Result at the stop: **30,424 tenders stored**, 18 windows finished, about 65,000 documents stored and 15,500 refused (19%).

### Measured (facts)
| What | Value |
|---|---|
| Rate at 4 threads, all 20 runners working | 1,650 to 2,010 tenders/min (12:42 to 12:48) |
| Per active runner | 82 to 105 tenders/min |
| Per active runner after 4 -> 16 threads | 87 to 105 tenders/min (**no change**) |
| Runners storing nothing in a given minute | 0 to 1 until 12:49, then 8 to 11 of 20 |
| Total rate after the 12:49 window turnover | 630 to 1,260 tenders/min |
| Portal pushback (429/403/503/blocked) | **none**, 0 blocks, 1 connection error in 26 min |
| Hub load | CPU idle, about 14 requests/s, Postgres 1 active connection, 0 errors |
| Parsed fields | 100% of 30,018 checked tenders had type and publish date, 0 parse errors |
| Document refusals | 1% in the first minute, 17 to 22% later: depends on organisation and year |
| Captcha first-try success | 55 to 60%; bursts of 26 attempts/min when windows start |
| CPU per tender in Python (this VPS, 6 cores) | about 170 ms: 59 ms three html.parser soups, 25 ms link search, 30 ms document search, 53 ms September parser, 3 ms gzip |
| Failures | 1 tender (`ChunkedEncodingError`, IncompleteRead), documents refused are in the failures table |

### Interpretation (what the facts suggest)
- Threads did not raise a runner's speed, so something per runner is the limit. A single Python process parsing about 170 ms per
  tender on this fast machine tops out near 350 tenders/min before network time; slower GitHub CPUs and the GIL would put it near
  the observed 100/min. **This is the leading hypothesis and it is NOT verified** (see below).
- The drop after 12:49 comes from window boundaries: a runner that finishes a window pages through that window's whole result list
  (about 120 pages, serially) and builds a fresh captcha-solved session per thread before fetching anything. All 20 runners started on
  similar windows, so they hit the boundary together and about half sat idle at any moment.
- Raising threads therefore added captcha sessions (more start-up work per window) without adding throughput.

### NOT verified (do not treat as fact)
1. That runners are CPU-bound. GitHub runner CPU count and utilisation were never measured. A per-IP rate limit on the portal that is
   silent (no 429) would look the same and was not ruled out.
2. That 4 processes per runner scales (the code exists; it was started and stopped within a minute, no data).
3. The split of time per phase on a runner (list pages, fetch, parse, documents, upload, hub calls). Nothing is timed yet.
4. That a GitHub-hosted runner has 4 cores (documentation says so for public repos; not checked in a run).

## Bugs found and fixed so far
- Cancelled/Retender tenders returned no fields: the details link was the last `$DirectLink` on the status page (a signature pop-up).
  Same cause as the 8,818 empty rows in the September data (6,554 Cancelled + 2,264 Retender). Fixed, with the cancellation notice
  now stored as a document.
- 43% of captured "documents" were digital-signature pop-ups; the BOQ chart is an Excel file named .pdf. Fixed, identified by bytes.
- Some documents are refused by the portal itself (its download servlet redirects to `CommonErrorPage`, same in a real browser).
- The database wipe at 12:33 silently rolled back (savepoint inside an implicit transaction); fixed by committing explicitly and
  verifying from a second connection. Lesson: verify destructive operations from a fresh connection.
- Hub latency metric was always 0 (timed before sending). Fixed.

## Optimisation backlog (ranked by expected gain; none applied yet unless marked)
1. **Instrument first**: per-phase timers (list, fetch, parse, documents, upload) and runner CPU%/cores as metrics. Prerequisite for
   everything else, so the next decision is made on data.
2. **Overlap listing with fetching**: list the next window while the current one is being fetched. Targets the 8 to 11 idle runners.
3. **Parse each page once**: the pages are parsed about 8 times per tender (3 soups, link search, two document searches, the parser).
   Share one lxml tree; expected 170 -> roughly 60 to 80 ms (an estimate to verify).
4. **Several processes per runner** (implemented, unverified; needs experiment 1 below).
5. **Reuse authenticated sessions across windows** of the same organisation to avoid re-solving about 16 x 1.75 captchas per window.
   Untested; earlier evidence is encouraging (detail links worked in a different session).
6. Pipeline document downloads and uploads so they overlap the next tender's fetch.
7. Captcha model accuracy (55 to 60% first try).
8. Done: skip tenders already stored when a window is retried or resumed (`--rescrape` overrides).

## Experiments to run before the next big run
1. **1 vs 4 processes on the same windows**: 2 runners, capped, same windows. Compare tenders/min per runner and CPU%.
   Decides whether the processes-per-runner change is worth keeping.
2. **Phase timing** from the instrumented crawler on one runner: where the 100 tenders/min actually goes.
3. After optimisations: repeat 1 and confirm a gain before launching the full run.

## Checklist before any large run
- Observations of the last run written here.
- Known optimisations applied, each verified by a small test or marked as unverified.
- Hub backup taken (nightly timer; take one manually before a wipe) and a restore known to work.
- Database changes verified from a fresh connection.
- Speed set on the dashboard; auto-backoff on.
