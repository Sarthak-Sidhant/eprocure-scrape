import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import windows  # noqa: E402
from plan import remap_by_name  # noqa: E402


def test_month_windows_cover_the_year_exactly_including_leap_february():
    ms = windows.month_windows(2024)
    assert len(ms) == 12 and ms[0] == ("01/01/2024", "31/01/2024") and ms[1] == ("01/02/2024", "29/02/2024") and ms[-1] == ("01/12/2024", "31/12/2024")
    assert windows.month_windows(2023)[1][1] == "28/02/2023"


def test_split_window_halves_are_contiguous_and_exhaustive():
    (a1, b1), (a2, b2) = windows.split_window("01/01/2024", "31/01/2024")
    assert a1 == "01/01/2024" and b2 == "31/01/2024"
    assert (windows.parse(a2) - windows.parse(b1)).days == 1        # the second half starts the day after the first ends


def test_splitting_repeatedly_ends_at_single_days_and_never_loses_a_day():
    days, todo = 0, [("01/03/2024", "31/03/2024")]
    while todo:
        f, t = todo.pop()
        halves = windows.split_window(f, t)
        if halves is None:
            assert f == t
            days += 1
        else:
            todo.extend(halves)
    assert days == 31


def test_single_day_window_cannot_be_split():
    assert windows.split_window("05/05/2024", "05/05/2024") is None


def test_keys_are_sortable_and_distinct_for_counts_and_crawls():
    c = windows.crawl_item("12", "Org", "01/02/2024", "29/02/2024", 40)
    k = windows.count_item("12", "Org", "01/02/2024", "29/02/2024", 1200)
    assert c["key"] == "12:2024-02-01:2024-02-29" and k["key"] == "count:12:2024-02-01:2024-02-29"
    assert k["payload"]["kind"] == "count" and c["payload"]["expected"] == 40


def test_plan_scrapes_small_org_years_whole_and_counts_big_ones_by_month():
    orgs = {"1": {"name": "Small", "years": {"2018": 500, "2019": 0}}, "2": {"name": "Big", "years": {"2018": 5000, "2010": 99}}}
    crawl, counts, s = windows.build_plan(orgs, 2011, 2026, split_over=600, chunk_max=1200)
    assert [c["key"] for c in crawl] == ["1:2018-01-01:2018-12-31"]        # zero years and out-of-range years are dropped
    assert len(counts) == 12 and all(c["payload"]["org_id"] == "2" for c in counts)
    assert s["direct_tenders"] == 500 and s["split_tenders"] == 5000 and s["count_tasks"] == 12


def test_plan_ranks_crawl_chunks_biggest_first():
    orgs = {str(i): {"name": f"O{i}", "years": {"2020": n}} for i, n in enumerate([10, 500, 50])}
    crawl, _, _ = windows.build_plan(orgs, 2011, 2026)
    assert [c["payload"]["expected"] for c in crawl] == [500, 50, 10] and [c["partition_id"] for c in crawl] == [0, 1, 2]


def test_ids_are_rekeyed_by_name_and_ambiguous_names_skipped():
    saved = {"222": {"name": "DG,BSF,MHA", "years": {"2020": 5}}, "9": {"name": "Dup", "years": {"2020": 1}}, "8": {"name": "Gone", "years": {"2020": 1}}}
    live = {"223": "DG,BSF,MHA", "10": "Dup", "11": "dup"}
    out, moved, skipped = remap_by_name(saved, live)
    assert set(out) == {"223"} and moved == 1 and {s[0] for s in skipped} == {"9", "8"}


def test_count_workers_obey_the_dashboard_speed_setting():
    import count

    class H:
        settings = {"threads": 2, "paused": False}
    h = H()
    assert [count.should_idle(h, i) for i in range(4)] == [False, False, True, True]
    h.settings = {"threads": 8, "paused": True}
    assert all(count.should_idle(h, i) for i in range(4))          # paused: everyone idles
