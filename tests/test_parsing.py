import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import parsing  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "pages")
TENDERS = sorted(os.path.basename(p) for p in glob.glob(os.path.join(FIX, "20*")))


def load(tid):
    rd = lambda n: open(os.path.join(FIX, tid, n), encoding="utf-8", errors="ignore").read()
    return rd("status.html"), rd("details.html"), rd("summary.html"), json.load(open(os.path.join(FIX, tid, "details.json"))), \
        json.load(open(os.path.join(FIX, tid, "golden_from_september_parser.json")))


def test_fixtures_exist():
    assert len(TENDERS) == 3


def test_every_field_matches_what_the_september_parser_produced():
    for tid in TENDERS:
        status, details, summary, dj, gold = load(tid)
        fields, d2, out = parsing.parse_tender(tid, gold["fields"]["org_id"], gold["fields"]["org_name"], dj, status, details, summary, gold["files"])
        assert fields == gold["fields"], tid
        assert d2 == gold["procurement_details"], tid
        assert {k: v for k, v in out.items() if k != "commercial_files"} == gold["outcomes_without_files"], tid
        assert sorted(out["commercial_files"]) == sorted(gold["commercial_files"]), tid     # the original listed a folder, so its order was arbitrary


def test_the_fields_are_actually_filled_in_not_just_equal_empties():
    status, details, summary, dj, gold = load("2023_NTA_745082_1")
    f, _, _ = parsing.parse_tender("2023_NTA_745082_1", "", "NTA", dj, status, details, summary, [])
    assert f["tender_type"] == "Limited" and f["tender_category"] == "Services" and f["location"] == "Okhla, New Delhi"
    assert f["published_date"] == "16-Mar-2023 11:00 AM" and f["bid_submission_end_date"] == "22-Mar-2023 09:00 AM"
    assert list(f) == parsing.COLUMNS and len(parsing.COLUMNS) == 62


def test_a_missing_page_gives_empty_fields_not_an_error():
    f, d2, out = parsing.parse_tender("T", "1", "Org", {"Tender Title": "x", "bids": []}, "", "", "", [])
    assert f["tender_title"] == "x" and f["tender_type"] == "" and f["bids_count"] == 0 and d2 == {} and out["stages"] == []
